"""Admin backup/restore domain module (phase 02 archive-extract, R1).

Migrate step: ``handle_admin_backup_callback`` owns the ``backup_restore``
handling that used to be inline in the admin monolith's
``_handle_admin_callback``. ``cmd_backup`` / ``cmd_restore`` /
``handle_restore_doc`` / ``_create_auto_backup`` / ``auto_backup_job`` and the
``admin_restore`` / ``admin_archive_chat_id`` awaiting flows move here
unchanged (route-delete rule: deleted from ``handlers/admin.py`` in the same
change). Behavior is unchanged; the admin monolith delegates to this module.
"""

import asyncio
import datetime
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from config import (
    APP_TZ,
    ARCHIVE_AUTO_BACKUP_RETENTION_DAYS,
    ARCHIVE_BACKUP_DIR,
    DB_PATH,
    is_owner,
)
from services import db
from services.archive import clear_archive_error, report_archive_error
from services.send_pretty import RawFormat, say
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers import _edit_or_send, _store_awaiting_msg
from config.keyboards import main_menu
from config.keyboards.admin import backup_restore_keyboard
from config.keyboards import admin_awaiting_inline_keyboard

logger = logging.getLogger(__name__)
_app_timezone = APP_TZ

__all__ = [
    "handle_admin_backup_callback",
    "cmd_backup",
    "cmd_restore",
    "handle_restore_doc",
    "auto_backup_job",
    "_create_auto_backup",
    "_handle_admin_restore",
    "_handle_admin_archive_chat_id",
    "register_backup_flows",
]


async def _show_backup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_arch = db.get_setting("archive_chat_id", "") or ""
    arch = raw_arch or "-"
    warning = ""
    if raw_arch:
        from services.archive import validate_archive_chat_id

        if not validate_archive_chat_id(raw_arch):
            warning = f"\n⚠️ مقدار ذخیره‌شده نامعتبر است: {raw_arch}"
            last_err = db.get_setting("archive_last_error", "")
            if last_err:
                warning += f"\n({last_err})"
    await _edit_or_send(update, context, f"💾 پشتیبان & بازیابی\nآرشیو فعلی: {arch}{warning}", reply_markup=backup_restore_keyboard())
    await notify_callback(update.callback_query)


async def handle_admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Handle the ``backup_restore`` menu and its sub-actions."""
    if action == "backup_restore":
        await _show_backup_menu(update, context)
        return
    if not action.startswith("backup_restore:"):
        await notify_callback(update.callback_query, "عملیات نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    sub = action[len("backup_restore:"):]
    if not sub:
        # Parity with the pre-extract monolith (lstrip(":") treated
        # "backup_restore:" as the menu): empty sub renders the menu.
        await _show_backup_menu(update, context)
        return
    if sub == "backup_now":
        await notify_callback(update.callback_query, "در حال تهیه پشتیبان…", intent=CallbackNoticeIntent.INFO)
        try:
            from services.archive import do_backup
            await do_backup(context.bot, update.effective_user.id)
            await notify_callback(update.callback_query, "ارسال شد.", intent=CallbackNoticeIntent.SUCCESS)
        except Exception as exc:
            logger.exception("Backup failed")
            await _edit_or_send(update, context, f"خطا در تهیه پشتیبان: {exc}", reply_markup=backup_restore_keyboard())
        return
    elif sub == "restore":
        context.user_data["awaiting"] = "admin_restore"
        await notify_callback(update.callback_query)
        await _edit_or_send(update, context, "فایل دیتابیس (.db) را آپلود کنید.\n⚠️ این کار دیتابیس فعلی را کاملاً جایگزین می‌کند.", reply_markup=admin_awaiting_inline_keyboard())
        return
    elif sub == "set_archive":
        context.user_data["awaiting"] = "admin_archive_chat_id"
        await notify_callback(update.callback_query)
        await say(update, context, "آیدی گروه آرشیو را بفرست (مثلاً -100123...). برای لغو /cancel:", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
        return
    elif sub == "clear_archive":
        db.set_setting("archive_chat_id", "")
        clear_archive_error()
        await _edit_or_send(update, context, "آرشیو پاک شد.", reply_markup=backup_restore_keyboard())
        await notify_callback(update.callback_query, "پاک شد", intent=CallbackNoticeIntent.SUCCESS)
        return
    elif sub == "test_archive":
        from services.archive import resolved_archive_chat_id, is_bot_admin

        cid = resolved_archive_chat_id()
        if not cid:
            raw = db.get_setting("archive_chat_id", "")
            if raw and raw.strip():
                await notify_callback(update.callback_query, f"مقدار ذخیره‌شده نامعتبر است: {raw}", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            else:
                await notify_callback(update.callback_query, "آرشیو تنظیم نشده.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        try:
            ok = await is_bot_admin(context.bot, cid)
        except Forbidden as exc:
            logger.warning("test_archive Forbidden chat_id=%s raw=%s: %s", cid, cid, exc, exc_info=True)
            report_archive_error(f"Forbidden: {exc}")
            await notify_callback(update.callback_query, f"دسترسی ممنوع (Forbidden): {exc}", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        except BadRequest as exc:
            logger.warning("test_archive BadRequest chat_id=%s raw=%s: %s", cid, cid, exc, exc_info=True)
            report_archive_error(f"BadRequest: {exc}")
            await notify_callback(update.callback_query, f"آیدی نامعتبر (BadRequest): {exc}", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        except Exception as exc:
            logger.warning("test_archive error chat_id=%s: %s", cid, exc, exc_info=True)
            report_archive_error(str(exc))
            await notify_callback(update.callback_query, f"خطا در بررسی: {exc}", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        await notify_callback(update.callback_query, "ربات ادمین است ✅" if ok else "ربات ادمین نیست ❌ — دسترسی ارسال ندارد", intent=CallbackNoticeIntent.INFO)
        return
    else:
        await notify_callback(update.callback_query, "عملیات نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the current database file to the admin (via archive service)."""
    if not is_owner(update.effective_user.id):
        await say(update, context, "فقط مالک ربات دسترسی داره.", raw=RawFormat.PLAIN, mode="send")
        return
    try:
        from services.archive import do_backup
        await do_backup(context.bot, update.effective_user.id)
    except Exception as exc:
        logger.exception("Backup failed")
        await say(update, context, f"خطا در تهیه پشتیبان: {exc}", raw=RawFormat.PLAIN, mode="send")


async def cmd_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start restore flow — expect a .db file upload."""
    if not is_owner(update.effective_user.id):
        await say(update, context, "فقط مالک ربات دسترسی داره.", raw=RawFormat.PLAIN, mode="send")
        return
    context.user_data["awaiting"] = "admin_restore"
    msg = await say(update, context, "فایل دیتابیس (.db) را آپلود کنید.\n"
        "⚠️ این کار دیتابیس فعلی را کاملاً جایگزین می‌کند.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
    _store_awaiting_msg(context, update, msg)


async def handle_restore_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded database file for restore.

    Contract L3: unified flow works in both PV and group for owner.
    Intentionally no strict awaiting gate — owner check is the safety
    boundary; file is still validated (size + SQLite header) before
    import. Pop awaiting if present so retry upload works without
    re-issuing /restore.
    """
    if not is_owner(update.effective_user.id):
        await say(update, context, "فقط مالک ربات دسترسی داره.", raw=RawFormat.PLAIN, mode="send")
        return
    # Audit log of restore attempt (P0) — include effective_chat.id
    try:
        cid = getattr(update.effective_chat, "id", None)
        logger.info("restore attempt by owner %s in chat %s effective_chat.id=%s", update.effective_user.id, cid, cid)
    except Exception:
        logger.debug("restore attempt log failed", exc_info=True)
        pass
    # Per contract: allow owner .db upload in PV or group without
    # requiring awaiting == admin_restore (group flow would otherwise
    # need extra gate). Validation below is the destructive-op guard.
    context.user_data.pop("awaiting", None)

    _MAX_RESTORE_BYTES = 100 * 1024 * 1024
    try:
        doc = update.effective_message.document
        file_size = getattr(doc, "file_size", None)
        if isinstance(file_size, int) and file_size > _MAX_RESTORE_BYTES:
            raise ValueError("حجم فایل بیش از 100 مگابایت است.")
        file = await doc.get_file()
        data = await file.download_as_bytearray()
        if len(data) > _MAX_RESTORE_BYTES:
            raise ValueError("حجم فایل بیش از 100 مگابایت است.")
        if len(data) < 100 or data[:16] != b"SQLite format 3\x00":
            raise ValueError("فایل معتبر SQLite نیست.")
        backup_path = f"{DB_PATH}.pre_restore"
        await asyncio.to_thread(db.import_db_bytes, bytes(data), backup_path)
        db.set_maintenance_mode(False)  # A2-1-7: auto-exit maintenance after restore
        await say(update, context, "✅ دیتابیس با موفقیت بازگردانی شد.\n"
            f"یک نسخه پشتیبان از دیتابیس قبلی در {backup_path} ذخیره شد.", raw=RawFormat.PLAIN, keyboard=main_menu(True), mode="send")
    except Exception as exc:
        logger.exception("Restore failed")
        await say(update, context, f"❌ خطا در بازگردانی: {exc}", raw=RawFormat.PLAIN, mode="send")


_AUTO_BACKUP_LOCK = asyncio.Lock()

def _create_auto_backup() -> str | None:
    if not db.get_bool_setting("auto_backup_enabled", True):
        return None
    base_dir = os.path.realpath(os.path.dirname(DB_PATH) or ".")
    candidate = os.path.realpath(os.path.join(base_dir, ARCHIVE_BACKUP_DIR))
    if candidate != base_dir and not candidate.startswith(base_dir + os.sep):
        logger.warning("ARCHIVE_BACKUP_DIR=%r escapes DB dir; falling back to default", ARCHIVE_BACKUP_DIR)
        candidate = os.path.join(base_dir, "backups")
    backup_dir = candidate
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.datetime.now(_app_timezone).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"hamzaban_auto_{timestamp}.db")
    Path(backup_path).write_bytes(db.export_db_bytes())
    cutoff = datetime.datetime.now(_app_timezone).timestamp() - ARCHIVE_AUTO_BACKUP_RETENTION_DAYS * 86400
    for fname in os.listdir(backup_dir):
        fpath = os.path.join(backup_dir, fname)
        if fname.startswith("hamzaban_auto_") and fname.endswith(".db"):
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
            except OSError:
                pass
    return backup_path


async def auto_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic auto-backup: save locally and push to archive group if configured."""
    # decoupled from OWNER_ID gate: run if resolved archive or OWNER_ID
    from services.archive import resolved_archive_chat_id, do_backup
    from config import OWNER_ID as _OID
    if resolved_archive_chat_id() is None and _OID == 0:
        return
    if _AUTO_BACKUP_LOCK.locked():
        return
    async with _AUTO_BACKUP_LOCK:
        try:
            backup_path = await asyncio.to_thread(_create_auto_backup)
            if backup_path:
                logger.info("Auto-backup saved: %s", backup_path)
            # push to archive/PV without quote
            try:
                await do_backup(context.bot, _OID)
            except Exception as exc:
                logger.warning("Auto-backup push failed: %s", exc)
        except Exception as exc:
            logger.exception("Auto-backup failed: %s", exc)


async def _handle_admin_restore(update, context, awaiting, text):
    from handlers.flows import mark_awaiting_consumed
    mark_awaiting_consumed(context)  # terminal re-prompt (B5/Kilo CRITICAL)
    context.user_data["awaiting"] = None
    await say(update, context, "لطفاً یک فایل دیتابیس (.db) آپلود کنید.\n"
        "دوباره /restore را بزنید.", raw=RawFormat.PLAIN, mode="send")


async def _handle_admin_archive_chat_id(update, context, awaiting, text):
    from handlers.flows import mark_awaiting_consumed
    from services.archive import validate_archive_chat_id
    raw = text.strip()
    if raw in ("", "clear", "0", "-"):
        db.set_setting("archive_chat_id", "")
        clear_archive_error()
        mark_awaiting_consumed(context)
        await say(update, context, "✅ آرشیو پاک شد.", raw=RawFormat.PLAIN, mode="send")
        return
    if not validate_archive_chat_id(raw):
        report_archive_error(f"invalid archive_chat_id: {raw}")
        context.user_data["awaiting"] = awaiting
        await say(update, context, "آیدی نامعتبر است. باید ^-100\\d{5,}$ یا ^-\\d{5,}$ باشد. دوباره بفرست یا لغو کن.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
        return
    db.set_setting("archive_chat_id", raw)
    clear_archive_error()
    mark_awaiting_consumed(context)
    await say(update, context, f"✅ آرشیو روی {raw} تنظیم شد.", raw=RawFormat.PLAIN, mode="send")


#: Guard so register_backup_flows() (import-time + test-triggered) never
#: duplicates flow entries in the central registry.
_BACKUP_FLOWS_REGISTERED = False


def register_backup_flows() -> None:
    """Register the backup awaiting flows in the central registry.

    Called at import time so the registry is populated before any text is
    routed. Idempotent: re-registration is a no-op.
    """
    global _BACKUP_FLOWS_REGISTERED
    if _BACKUP_FLOWS_REGISTERED:
        return
    from handlers.flows import register_flow

    register_flow("admin_restore", _handle_admin_restore)
    register_flow("admin_archive_chat_id", _handle_admin_archive_chat_id)
    _BACKUP_FLOWS_REGISTERED = True


register_backup_flows()
