import asyncio
import datetime
import io
import logging
import os
from pathlib import Path

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import APP_TZ, DB_PATH, is_owner
from services import db
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers import _edit_or_send, _exit_awaiting_flow, _send_with_retry
from handlers.admin_stats import handle_admin_stats
from handlers.admin_cost import (
    _handle_cost_text_input,
    _handle_llm_callback,
    _llm_cost_set_state,
    _llm_pricing_text,
    _show_llm_cost_dashboard,
    handle_cost_callback,
)
from handlers.admin_plans import (
    _handle_plan_set_active,
    _handle_plan_wizard_back,
    _handle_plan_wizard_cancel,
    _handle_plan_wizard_input,
    _handle_plan_wizard_next,
    _handle_plan_wizard_save,
    _handle_plans_text_input,
    _show_plan_list,
    _show_plan_view,
    _show_plan_wizard_field,
    _show_plan_wizard_summary,
    _start_plan_wizard,
    _validate_plan_wizard_value,
    handle_plan_callback,
)
from handlers.admin_ai import (
    _activate_ai_preset,
    _add_ai_preset,
    _confirm_save_preset,
    _custom_test_step_lang,
    _delete_ai_preset,
    _detect_key_groups,
    _discard_all_preset_changes,
    _edit_ai_preset,
    _edit_ai_preset_field,
    _handle_ai_fallback,
    _handle_ai_preset_field_input,
    _handle_ai_preset_new_name,
    _handle_ai_text_input,
    _handle_custom_test_wizard,
    _handle_fallback_rank,
    _handle_full_edit_cancel,
    _handle_full_edit_input,
    _handle_full_edit_next,
    _handle_full_edit_pick_group,
    _handle_full_edit_save,
    _handle_full_edit_skip,
    _handle_group_batch_key,
    _handle_group_manager_clear,
    _handle_group_manager_rename,
    _handle_group_set_label,
    _handle_group_view,
    _save_ai_preset,
    _show_ai_fallback,
    _show_ai_preset_view,
    _show_ai_presets,
    _show_ai_settings,
    _show_fallback_chain,
    _show_fallback_usage_details,
    _show_group_manager,
    _show_grouped_presets,
    _show_help_fallback_chain,
    _show_help_presets,
    _show_linear_presets,
    _start_custom_test_wizard,
    _start_full_edit_wizard,
    _test_ai_connection,
    _toggle_preset_view_mode,
    handle_ai_callback,
)
from config.keyboards import (
    admin_panel_keyboard,
    main_menu,
    admin_awaiting_inline_keyboard,
    phonetic_settings_keyboard,
    log_level_keyboard,
    user_activity_keyboard,
)

logger = logging.getLogger(__name__)
_app_timezone = APP_TZ

# Single source of truth for "is this user_data['awaiting'] an admin flow state".
# Every admin awaiting key — set across handlers/admin.py and its domain
# submodules — is covered here so the router never silently drops a new key
# (this is the root-cause fix for the ai_fallback_rank: routing gap, Finding #6).
_ADMIN_AWAITING_PREFIXES = (
    "admin_",            # admin_set_plan, admin_broadcast, admin_restore,
                         # admin_plan_full_edit:, admin_ai_preset_new_name,
                         # admin_group_batch_key:, admin_group_set_label:,
                         # admin_group_manager_rename:
    "ai_preset_",        # ai_preset_new_name, ai_preset_edit:, ai_preset_full_edit:
    "ai_custom_test_",   # ai_custom_test_prompt
    "ai_fallback_rank:",  # ai_fallback_rank:{preset_name}
    "llm_cost_",         # llm_cost_user, llm_cost_model
    "llm_price_",        # llm_price_input, llm_price_output, llm_price_rate
)


def is_admin_awaiting(awaiting: str) -> bool:
    """Return True if *awaiting* is an admin-panel text-input flow state.

    Centralizes the admin awaiting-key namespace so bot.py's text_router no
    longer hard-codes a prefix list (and can never miss a key again).
    """
    return bool(awaiting) and awaiting.startswith(_ADMIN_AWAITING_PREFIXES)


async def open_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text("پنل مدیریت ربات:", reply_markup=admin_panel_keyboard())


async def _show_user_activity_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the USER_ACTIVITY log toggle with current on/off status."""
    current = db.get_setting("user_activity_log", "off")
    status = "روشن" if current == "on" else "خاموش"
    text = (
        "👤 <b>لاگ فعالیت کاربر</b>\n\n"
        f"وضعیت فعلی: <b>{status}</b>\n\n"
        "این لاگ تمام درخواست‌های کاربران را ثبت می‌کند:\n"
        "• درخواست فلش‌کارت روزانه\n"
        "• پرسیدن واژه\n"
        "• مرور SRS\n"
        "• تغییر تنظیمات\n"
        "• و سایر فعالیت‌ها\n\n"
        "این لاگ در سطح <b>👤 USER</b> ثبت می‌شود و برای عیب‌یابی و بررسی رفتار کاربران مفید است."
    )
    await _edit_or_send(update, context, text, reply_markup=user_activity_keyboard(current))


async def _show_log_level_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the log-level picker with current level pre-selected."""
    current = db.get_setting("log_level", "") or logging.getLevelName(logging.getLogger().getEffectiveLevel())
    text = (
        "📋 <b>تنظیم سطح لاگ</b>\n\n"
        f"سطح فعلی: <b>{current}</b>\n\n"
        "سطوح پایین‌تر جزئیات بیشتر و سطوح بالاتر جزئیات کمتر:\n"
        "• DEBUG (10) — جزئیات فنی کامل\n"
        "• INFO (20) — وضعیت عادی\n"
        "• WARNING (30) — فقط هشدارها\n"
        "• ERROR (40) — فقط خطاها\n"
        "• CRITICAL (50) — فقط خطاهای بحرانی"
    )
    await _edit_or_send(update, context, text, reply_markup=log_level_keyboard(current))


def _phonetic_ipa_default() -> bool:
    """Admin-global phonetic display-toggle default (single source of truth)."""
    return db.get_display_toggle_defaults().get("phonetic", True)


def _phonetic_settings_text() -> str:
    ipa = _phonetic_ipa_default()
    tts_access = db.get_setting("tts_access", "premium")
    tts_labels = {"none": "❌ غیرفعال", "premium": "🥈 نقره‌ای و طلایی", "all": "✅ همه"}
    return (
        "تنظیم نمایش تلفظ‌ها:\n"
        f"IPA: {'روشن' if ipa else 'خاموش'}\n"
        f"🔊 تلفظ صوتی: {tts_labels.get(tts_access, tts_access)}"
    )


async def _handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    if not is_owner(update.effective_user.id):
        await notify_callback(update.callback_query, "فقط مالک ربات دسترسی داره.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if action == "stats" or action.startswith("stats:"):
        await handle_admin_stats(update, context, action)
    elif action == "plans" or action.startswith("plans:") or action == "set_plan":
        await handle_plan_callback(update, context, action)
    elif action in ("cost_dashboard", "llm_costs", "llm_pricing"):
        await handle_cost_callback(update, context, action)
    elif action.startswith("ai_") or action.startswith("fallback") or action in ("help:presets", "help:fallback_chain"):
        await handle_ai_callback(update, context, action)
    elif action == "back":
        context.user_data.pop("awaiting", None)
        await _edit_or_send(update, context, "پنل مدیریت ربات:", reply_markup=admin_panel_keyboard())
        await notify_callback(update.callback_query, "بازگشت", intent=CallbackNoticeIntent.INFO)
    elif action == "cancel":
        context.user_data.pop("awaiting", None)
        context.user_data.pop("preset_edits", None)
        context.user_data.pop("full_edit", None)
        await _edit_or_send(update, context, "عملیات لغو شد.", reply_markup=admin_panel_keyboard())
        await notify_callback(update.callback_query, "لغو شد", intent=CallbackNoticeIntent.INFO)
    elif action == "phonetics":
        await _edit_or_send(
            update,
            context,
            _phonetic_settings_text(),
            reply_markup=phonetic_settings_keyboard({"ipa": _phonetic_ipa_default()}),
        )
        await notify_callback(update.callback_query, "تنظیم شد.", intent=CallbackNoticeIntent.SUCCESS)
    elif action.startswith("phonetics:"):
        _, setting = action.split(":", 1)
        if setting != "ipa":
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        current = _phonetic_ipa_default()
        db.set_display_toggle_defaults({"phonetic": not current})
        await _edit_or_send(
            update,
            context,
            _phonetic_settings_text(),
            reply_markup=phonetic_settings_keyboard({"ipa": _phonetic_ipa_default()}),
        )
        await notify_callback(update.callback_query, "تنظیم شد.", intent=CallbackNoticeIntent.SUCCESS)
    elif action == "broadcast":
        context.user_data["awaiting"] = "admin_broadcast"
        await notify_callback(update.callback_query)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="متن پیام همگانی رو بفرست:",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
    elif action == "show_settings":
        try:
            preset = db.get_active_preset()
        except db.NoActivePresetError:
            await _edit_or_send(
                update,
                context,
                "🤖 هیچ پیش‌تنظیم فعالی وجود ندارد. برای استفاده از هوش مصنوعی، "
                "یک پیش‌تنظیم بسازید و فعال کنید.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back to Admin Panel", callback_data="admin:back")]]),
            )
            return
        masked = db.mask_key(db.resolve_preset_key(preset))
        from services.utils.formatting import html_escape
        await _edit_or_send(
            update,
            context,
            f"🤖 پیش‌تنظیم فعال: <b>{html_escape(str(preset.get('name', 'gapgpt'))) }</b>\n"
            f"📋 مدل: <b>{html_escape(str(preset.get('model', '—'))) }</b>\n"
            f"🌐 Base URL: <b>{html_escape(str(preset.get('base_url', '—'))) }</b>\n"
            f"🔑 API Key: <code>{html_escape(masked)}</code>\n"
            f"🗣 IPA: {'روشن' if _phonetic_ipa_default() else 'خاموش'}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back to Admin Panel", callback_data="admin:back")]]),
        )
    elif action == "noop":
        await notify_callback(update.callback_query)
    elif action == "log_level":
        await _show_log_level_settings(update, context)
    elif action.startswith("log_level:set:"):
        level_name = action.split(":", 2)[2]
        db.set_setting("log_level", level_name)
        from services.utils.helpers import apply_log_level
        apply_log_level(level_name)
        await _show_log_level_settings(update, context)
    elif action == "user_activity_log":
        await _show_user_activity_settings(update, context)
    elif action == "user_activity:toggle":
        current = db.get_setting("user_activity_log", "off")
        new_value = "off" if current == "on" else "on"
        db.set_setting("user_activity_log", new_value)
        await _show_user_activity_settings(update, context)


async def handle_flow_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the ``flow:back`` callback by resuming the previous editing flow.

    Encapsulates the awaiting-key-aware back-navigation logic that previously
    lived inline in ``bot.py``'s callback_router. Handles all awaiting states,
    not only admin ones (e.g., ``ask_word`` is also supported). Behavior is
    unchanged.
    """
    awaiting = context.user_data.get("awaiting", "")
    if awaiting.startswith("ai_preset_edit:"):
        preset_name = awaiting.split(":", 1)[1].rsplit(":", 1)[0]
        context.user_data.pop("awaiting", None)
        await _edit_ai_preset(update, context, preset_name)
    elif awaiting.startswith("ai_preset_full_edit:"):
        preset_name = awaiting.split(":", 2)[1]
        context.user_data.pop("full_edit", None)
        context.user_data.pop("awaiting", None)
        await _edit_ai_preset(update, context, preset_name)
    elif awaiting.startswith("admin_plan_full_edit:"):
        context.user_data.pop("plan_full_edit", None)
        await _exit_awaiting_flow(update, context, via_callback=True)
    elif awaiting:
        await _exit_awaiting_flow(update, context, via_callback=True)
    else:
        await notify_callback(update.callback_query, "فعلاً چیزی برای لغو نیست.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)


async def _handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str, text: str):
    if awaiting in {"llm_cost_user", "llm_cost_model", "llm_price_input", "llm_price_output", "llm_price_rate"}:
        await _handle_cost_text_input(update, context, awaiting, text)
        return

    if awaiting == "admin_set_plan":
        await _handle_plans_text_input(update, context, text)
        return

    if awaiting == "admin_broadcast":
        users = db.all_active_users()
        sent = 0
        for u in users:
            try:
                await _send_with_retry(context.bot, u["user_id"], text)
                sent += 1
            except Exception:
                logger.exception("Broadcast failed for user %s", u["user_id"])
        await update.message.reply_text(f"پیام برای {sent} کاربر ارسال شد.")
        return

    # ======== AI Settings awaiting handlers ========

    if awaiting.startswith("admin_group_batch_key:") or awaiting.startswith("admin_group_set_label:") or awaiting.startswith("admin_group_manager_rename:") or awaiting.startswith("ai_fallback_rank:") or awaiting.startswith("ai_preset_create_priority:"):
        await _handle_ai_text_input(update, context, awaiting, text)
        return

    if awaiting == "ai_preset_new_name":
        await _handle_ai_preset_new_name(update, context, text)
        return

    if awaiting.startswith("ai_preset_edit:"):
        # format: ai_preset_edit:preset_name:field_name
        parts = awaiting.split(":", 2)
        if len(parts) == 3:
            await _handle_ai_preset_field_input(update, context, parts[1], parts[2], text)
        return

    if awaiting.startswith("admin_plan_full_edit:"):
        # format: admin_plan_full_edit:plan_name:field_idx
        parts = awaiting.split(":", 3)
        if len(parts) == 3:
            plan_name, field_idx = parts[1], parts[2]
            await _handle_plan_wizard_input(update, context, plan_name, int(field_idx), text)
        return

    if awaiting.startswith("ai_preset_full_edit:"):
        # format: ai_preset_full_edit:preset_name:field_idx
        parts = awaiting.split(":", 3)
        if len(parts) == 3:
            preset_name, field_idx = parts[1], parts[2]
            await _handle_full_edit_input(update, context, preset_name, int(field_idx), text)
        return

    if awaiting == "ai_custom_test_prompt":
        state = context.user_data.setdefault("custom_test_state", {})
        state["prompt"] = text
        context.user_data["custom_test_state"] = state
        await _custom_test_step_lang(update, context)
        return

    if awaiting == "admin_restore":
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            "لطفاً یک فایل دیتابیس (.db) آپلود کنید.\n"
            "دوباره /restore را بزنید.",
        )
        return

    if awaiting == "admin_ai_preset_new_name":
        await _handle_ai_preset_new_name(update, context, text)
        return


# ======== AI Settings Panel Handlers ========


# ======== Backup / Restore ========

async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the current database file to the admin."""
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("فقط مالک ربات دسترسی داره.")
        return
    try:
        data = await asyncio.to_thread(db.export_db_bytes)
        await update.message.reply_document(
            document=io.BytesIO(data),
            filename=f"hamzaban_backup_{datetime.datetime.now(_app_timezone).strftime('%Y%m%d_%H%M%S')}.db",
            caption="📦 پشتیبان دیتابیس",
        )
    except Exception as exc:
        logger.exception("Backup failed")
        await update.message.reply_text(f"خطا در تهیه پشتیبان: {exc}")


async def cmd_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start restore flow — expect a .db file upload."""
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("فقط مالک ربات دسترسی داره.")
        return
    context.user_data["awaiting"] = "admin_restore"
    await update.message.reply_text(
        "فایل دیتابیس (.db) را آپلود کنید.\n"
        "⚠️ این کار دیتابیس فعلی را کاملاً جایگزین می‌کند.",
        reply_markup=admin_awaiting_inline_keyboard(),
    )


async def handle_restore_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded database file for restore."""
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("فقط مالک ربات دسترسی داره.")
        return
    if context.user_data.get("awaiting") != "admin_restore":
        await update.message.reply_text("ابتدا /restore را بزنید.")
        return
    context.user_data.pop("awaiting", None)

    try:
        file = await update.effective_message.document.get_file()
        data = await file.download_as_bytearray()
        if len(data) < 100 or data[:16] != b"SQLite format 3\x00":
            raise ValueError("فایل معتبر SQLite نیست.")
        backup_path = f"{DB_PATH}.pre_restore"
        await asyncio.to_thread(db.import_db_bytes, bytes(data), backup_path)
        await update.message.reply_text(
            "✅ دیتابیس با موفقیت بازگردانی شد.\n"
            f"یک نسخه پشتیبان از دیتابیس قبلی در {backup_path} ذخیره شد.",
            reply_markup=main_menu(True),
        )
    except Exception as exc:
        logger.exception("Restore failed")
        await update.message.reply_text(f"❌ خطا در بازگردانی: {exc}")


def _create_auto_backup() -> str | None:
    if not db.get_bool_setting("auto_backup_enabled", True):
        return None
    backup_dir = os.path.join(os.path.dirname(DB_PATH) or ".", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.datetime.now(_app_timezone).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"hamzaban_auto_{timestamp}.db")
    Path(backup_path).write_bytes(db.export_db_bytes())
    cutoff = datetime.datetime.now(_app_timezone).timestamp() - 30 * 86400
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
    """Periodic auto-backup: save a timestamped copy locally."""
    try:
        backup_path = await asyncio.to_thread(_create_auto_backup)
        if backup_path:
            logger.info("Auto-backup saved: %s", backup_path)
    except Exception as exc:
        logger.exception("Auto-backup failed: %s", exc)
