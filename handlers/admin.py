import datetime
import logging
import os
from urllib.parse import unquote

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import APP_TZ, DB_PATH, is_owner
from services import db
from services.ai import ai_presets
from services.utils.helpers import _edit_or_send, _send_with_retry
from handlers.admin_stats import handle_admin_stats
from handlers.admin_cost import (
    _handle_cost_text_input,
    _handle_llm_callback,
    _llm_cost_set_state,
    _llm_pricing_text,
    _show_llm_cost_dashboard,
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
)
from config.keyboards import (
    admin_panel_keyboard,
    main_menu,
    admin_awaiting_inline_keyboard,
    llm_cost_pricing_keyboard,
    phonetic_settings_keyboard,
    admin_cost_keyboard,
    log_level_keyboard,
    user_activity_keyboard,
)

logger = logging.getLogger(__name__)
_app_timezone = APP_TZ


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


def _phonetic_settings_text() -> str:
    settings = db.get_phonetic_display_settings()
    tts_access = db.get_setting("tts_access", "premium")
    tts_labels = {"none": "❌ غیرفعال", "premium": "🥈 نقره‌ای و طلایی", "all": "✅ همه"}
    return (
        "تنظیم نمایش تلفظ‌ها:\n"
        f"IPA: {'روشن' if settings['ipa'] else 'خاموش'}\n"
        f"🔊 تلفظ صوتی: {tts_labels.get(tts_access, tts_access)}"
    )


async def _handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    if not is_owner(update.effective_user.id):
        await update.callback_query.answer("فقط مالک ربات دسترسی داره.", show_alert=True)
        return
    if action == "stats" or action.startswith("stats:"):
        await handle_admin_stats(update, context, action)
    elif action == "back":
        await _edit_or_send(update, context, "پنل مدیریت ربات:", reply_markup=admin_panel_keyboard())
        await update.callback_query.answer("بازگشت")
    elif action == "cancel":
        context.user_data.pop("awaiting", None)
        await _edit_or_send(update, context, "عملیات لغو شد.", reply_markup=admin_panel_keyboard())
        await update.callback_query.answer("لغو شد")
    elif action == "llm_costs":
        await _show_llm_cost_dashboard(update, context)
    elif action == "llm_pricing":
        await _edit_or_send(
            update,
            context,
            _llm_pricing_text(),
            reply_markup=llm_cost_pricing_keyboard(),
        )
    elif action == "cost_dashboard":
        await _edit_or_send(
            update,
            context,
            "💰 مدیریت هزینه‌های LLM:",
            reply_markup=admin_cost_keyboard(),
        )
        await update.callback_query.answer()
    elif action == "set_plan":
        context.user_data["awaiting"] = "admin_set_plan"
        await update.callback_query.answer()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="فرمت را ارسال کنید:\n`user_id_or_username plan`\n\n"
            "مثال: `123456789 silver` یا `@username gold`\n"
            "پلن‌ها: free، bronze، silver، gold، emerald",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=admin_awaiting_inline_keyboard(),
        )
    elif action == "plans":
        await _show_plan_list(update, context)
    elif action.startswith("plans:view:"):
        name = action.split(":", 2)[2]
        await _show_plan_view(update, context, name)
    elif action.startswith("plans:edit:"):
        name = action.split(":", 2)[2]
        await _start_plan_wizard(update, context, name)
    elif action.startswith("plans:full_edit_back:"):
        name = action.split(":", 2)[2]
        await _handle_plan_wizard_back(update, context, name)
    elif action.startswith("plans:full_edit_skip:"):
        name = action.split(":", 2)[2]
        await _handle_plan_wizard_next(update, context, name)
    elif action.startswith("plans:full_edit_cancel:"):
        name = action.split(":", 2)[2]
        await _handle_plan_wizard_cancel(update, context, name)
    elif action.startswith("plans:full_edit_save:"):
        name = action.split(":", 2)[2]
        await _handle_plan_wizard_save(update, context, name)
    elif action.startswith("plans:set_active:"):
        name = action.split(":", 2)[2]
        await _handle_plan_set_active(update, context, name)
    elif action == "phonetics":
        await _edit_or_send(
            update,
            context,
            _phonetic_settings_text(),
            reply_markup=phonetic_settings_keyboard(db.get_phonetic_display_settings()),
        )
        await update.callback_query.answer("تنظیم شد.")
    elif action.startswith("phonetics:"):
        _, setting = action.split(":", 1)
        key_map = {
            "ipa": "phonetic_show_ipa",
        }
        setting_key = key_map.get(setting)
        if not setting_key:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        current = db.get_bool_setting(setting_key, True)
        db.set_bool_setting(setting_key, not current)
        await _edit_or_send(
            update,
            context,
            _phonetic_settings_text(),
            reply_markup=phonetic_settings_keyboard(db.get_phonetic_display_settings()),
        )
        await update.callback_query.answer("تنظیم شد.")
    elif action == "broadcast":
        context.user_data["awaiting"] = "admin_broadcast"
        await update.callback_query.answer()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="متن پیام همگانی رو بفرست:",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
    elif action == "show_settings":
        preset = db.get_active_preset()
        raw_key = ai_presets.resolve_api_key(preset)
        masked = (raw_key[:6] + "…" + raw_key[-4:]) if len(raw_key) > 12 else ("—" if not raw_key else raw_key)
        await _edit_or_send(
            update,
            context,
            f"🤖 پیش‌تنظیم فعال: `{preset.get('name', 'gapgpt')}`\n"
            f"📋 مدل: `{preset.get('model', '—')}`\n"
            f"🌐 Base URL: `{preset.get('base_url', '—')}`\n"
            f"🔑 API Key: `{masked}`\n"
            f"🗣 IPA: {'روشن' if db.get_bool_setting('phonetic_show_ipa', True) else 'خاموش'}",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back to Admin Panel", callback_data="admin:back")]]),
        )
    # ======== AI Settings / Presets ========
    elif action == "ai_settings":
        await _show_ai_settings(update, context)
    elif action == "ai_presets":
        await _show_ai_presets(update, context)
    elif action.startswith("ai_preset:view:"):
        preset_name = action.split(":", 2)[2]
        await _show_ai_preset_view(update, context, preset_name)
    elif action.startswith("ai_preset:activate:"):
        preset_name = action.split(":", 2)[2]
        await _activate_ai_preset(update, context, preset_name)
    elif action.startswith("ai_preset:edit:"):
        preset_name = action.split(":", 2)[2]
        await _edit_ai_preset(update, context, preset_name)
    elif action.startswith("ai_preset:edit_field:"):
        # format: ai_preset:edit_field:preset_name:field_name
        parts = action.split(":", 3)
        if len(parts) == 4:
            await _edit_ai_preset_field(update, context, parts[2], parts[3])
    elif action.startswith("ai_preset:full_edit:"):
        preset_name = action.split(":", 2)[2]
        await _start_full_edit_wizard(update, context, preset_name)
    elif action.startswith("ai_preset:full_edit_next:"):
        parts = action.split(":", 3)
        if len(parts) == 4:
            preset_name = parts[2]
            await _handle_full_edit_next(update, context, preset_name)
    elif action.startswith("ai_preset:full_edit_skip:"):
        parts = action.split(":", 3)
        if len(parts) == 4:
            preset_name = parts[2]
            await _handle_full_edit_skip(update, context, preset_name)
    elif action.startswith("ai_preset:full_edit_cancel:"):
        preset_name = action.split(":", 2)[2]
        await _handle_full_edit_cancel(update, context, preset_name)
    elif action.startswith("ai_preset:full_edit_pick_group:"):
        # format: ai_preset:full_edit_pick_group:preset_name:encoded_label
        parts = action.split(":", 3)
        if len(parts) == 4:
            preset_name = parts[2]
            label = unquote(parts[3])
            await _handle_full_edit_pick_group(update, context, preset_name, label)
    elif action.startswith("ai_preset:full_edit_save:"):
        preset_name = action.split(":", 2)[2]
        await _handle_full_edit_save(update, context, preset_name)
    elif action.startswith("ai_preset:save:"):
        preset_name = action.split(":", 2)[2]
        await _confirm_save_preset(update, context, preset_name)
    elif action.startswith("ai_preset:confirm_save_yes:"):
        preset_name = action.split(":", 2)[2]
        await _save_ai_preset(update, context, preset_name)
    elif action.startswith("ai_preset:confirm_save_no:"):
        preset_name = action.split(":", 2)[2]
        await _edit_ai_preset(update, context, preset_name)
    elif action.startswith("ai_preset:discard_all:"):
        preset_name = action.split(":", 2)[2]
        await _discard_all_preset_changes(update, context, preset_name)
    elif action.startswith("ai_preset:delete:"):
        preset_name = action.split(":", 2)[2]
        await _delete_ai_preset(update, context, preset_name)
    elif action == "ai_preset:add":
        await _add_ai_preset(update, context)
    elif action.startswith("ai_preset:page:"):
        page = int(action.split(":", 2)[2])
        await _show_linear_presets(update, context, page)
    elif action.startswith("ai_preset:view_mode:"):
        mode = action.split(":", 2)[2]
        await _toggle_preset_view_mode(update, context)
    elif action.startswith("ai_preset:group:"):
        key_hash = action.split(":", 2)[2]
        await _handle_group_view(update, context, key_hash)
    elif action.startswith("ai_preset:group_batch_key:"):
        key_hash = action.split(":", 2)[2]
        await _handle_group_batch_key(update, context, key_hash)
    elif action.startswith("ai_preset:group_set_label:"):
        key_hash = action.split(":", 2)[2]
        await _handle_group_set_label(update, context, key_hash)
    elif action == "ai_preset:group_manager":
        await _show_group_manager(update, context)
    elif action.startswith("ai_preset:group_manager_rename:"):
        parts = action.split(":", 2)
        if len(parts) == 3:
            label = unquote(parts[2])
            await _handle_group_manager_rename(update, context, label)
    elif action.startswith("ai_preset:group_manager_clear:"):
        parts = action.split(":", 2)
        if len(parts) == 3:
            label = unquote(parts[2])
            await _handle_group_manager_clear(update, context, label)
    elif action == "ai_test_connection":
        await _test_ai_connection(update, context)
    elif action == "ai_custom_test":
        await _start_custom_test_wizard(update, context)
    elif action.startswith("ai_custom_test:"):
        await _handle_custom_test_wizard(update, context, action)
    elif action == "ai_fallback":
        await _show_ai_fallback(update, context)
    elif action.startswith("ai_fallback:"):
        await _handle_ai_fallback(update, context, action)
    elif action == "fallback_chain":
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:move_up:"):
        name = action.split(":", 2)[2]
        chain = db.get_enabled_presets_ordered()
        idx = next((i for i, p in enumerate(chain) if p["name"] == name), None)
        if idx and idx > 0:
            above = chain[idx - 1]
            tmp = above["priority"]
            db.set_preset_priority(above["name"], chain[idx]["priority"])
            db.set_preset_priority(name, tmp)
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:move_down:"):
        name = action.split(":", 2)[2]
        chain = db.get_enabled_presets_ordered()
        idx = next((i for i, p in enumerate(chain) if p["name"] == name), None)
        if idx is not None and idx < len(chain) - 1:
            below = chain[idx + 1]
            tmp = below["priority"]
            db.set_preset_priority(below["name"], chain[idx]["priority"])
            db.set_preset_priority(name, tmp)
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:toggle:"):
        name = action.split(":", 2)[2]
        preset = db.get_preset(name)
        if preset:
            db.set_preset_enabled(name, not preset.get("enabled", 1))
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:set_emergency:"):
        name = action.split(":", 2)[2]
        chain = db.get_enabled_presets_ordered()
        for p in chain:
            db.set_preset_emergency(p["name"], p["name"] == name)
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:rank:"):
        name = action.split(":", 2)[2]
        await _handle_fallback_rank(update, context, name)
    elif action == "fallback:usage_details":
        await _show_fallback_usage_details(update, context)
    elif action == "help:presets":
        await _show_help_presets(update, context)
    elif action == "help:fallback_chain":
        await _show_help_fallback_chain(update, context)
    elif action == "noop":
        await update.callback_query.answer()
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

    if awaiting.startswith("admin_group_batch_key:") or awaiting.startswith("admin_group_set_label:") or awaiting.startswith("admin_group_manager_rename:") or awaiting.startswith("ai_fallback_rank:"):
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
        context.user_data["custom_test_prompt"] = text
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
        with open(DB_PATH, "rb") as f:
            await update.message.reply_document(
                document=f,
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
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        db.import_db_bytes(bytes(data))
        await update.message.reply_text(
            "✅ دیتابیس با موفقیت بازگردانی شد.\n"
            f"یک نسخه پشتیبان از دیتابیس قبلی در {backup_path} ذخیره شد.",
            reply_markup=main_menu(True),
        )
    except Exception as exc:
        logger.exception("Restore failed")
        await update.message.reply_text(f"❌ خطا در بازگردانی: {exc}")


async def auto_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic auto-backup: save a timestamped copy locally."""
    if not db.get_bool_setting("auto_backup_enabled", True):
        return
    try:
        backup_dir = os.path.join(os.path.dirname(DB_PATH) or ".", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.datetime.now(_app_timezone).strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"hamzaban_auto_{timestamp}.db")
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        cutoff = datetime.datetime.now(_app_timezone).timestamp() - 30 * 86400
        for fname in os.listdir(backup_dir):
            fpath = os.path.join(backup_dir, fname)
            if fname.startswith("hamzaban_auto_") and fname.endswith(".db"):
                try:
                    if os.path.getmtime(fpath) < cutoff:
                        os.remove(fpath)
                except OSError:
                    pass
        logger.info("Auto-backup saved: %s", backup_path)
    except Exception as exc:
        logger.exception("Auto-backup failed: %s", exc)
