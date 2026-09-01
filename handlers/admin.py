import asyncio
import datetime
import io
import logging
import os
from pathlib import Path

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from config import APP_TZ, BROADCAST_MAX_CONCURRENCY, DB_PATH, is_owner
from services import db, send_pretty
from services.send_pretty import RawFormat, say
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.formatting import html_escape
from services.utils.helpers import _clear_awaiting_prompt, _edit_or_send, _exit_awaiting_flow, _send_with_retry, _store_awaiting_msg, clear_admin_pending_state
from handlers.admin_stats import handle_admin_stats
from handlers.admin_users import handle_admin_user
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
    BTN_ADMIN_USER_MANAGE,
    admin_panel_keyboard,
    broadcast_preview_keyboard,
    main_menu,
    admin_awaiting_inline_keyboard,
    maintenance_keyboard,
    log_level_keyboard,
    user_activity_keyboard,
    user_management_keyboard,
)

logger = logging.getLogger(__name__)
_app_timezone = APP_TZ

# Admin awaiting flows are registered in handlers/flows.py (R2) by each owning
# module at import time. is_admin_awaiting (imported by bot.py and the wiring
# guard from handlers.flows) delegates to that registry so bot.py never
# hard-codes a prefix list (and can never miss a key again). This replaces the
# old _ADMIN_AWAITING_PREFIXES allowlist (root-cause fix for Finding #6).
from handlers.flows import mark_awaiting_consumed, register_flow  # noqa: E402

#: Guard so _register_admin_flows() (import-time + test-triggered) never
#: duplicates flow entries in the central registry.
_ADMIN_FLOWS_REGISTERED = False

#: Re-entry guard for the admin broadcast (RT-BN1): set before the first await
#: and released in ``finally`` so a second broadcast cannot double-send.
_BROADCAST_RUNNING = False


async def _broadcast_send_one(bot, uid: int, text: str, sem: asyncio.Semaphore, kwargs: dict) -> bool:
    async with sem:
        try:
            await _send_with_retry(bot, uid, text, **kwargs)
            return True
        except Exception:
            logger.exception("Broadcast failed for user %s", uid)
            return False


async def open_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await say(update, context, "پنل مدیریت ربات:", raw=RawFormat.PLAIN, keyboard=admin_panel_keyboard(), mode="send")


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


def _maintenance_status_text() -> str:
    active = db.is_maintenance_mode()
    msg = db.get_maintenance_message()
    state = "🟢 فعال" if active else "⚫ غیرفعال"
    body = (
        "🔧 حالت تعمیر\n\n"
        f"وضعیت: {state}\n"
        f"پیام نمایشی: {msg}"
    )
    return body


async def _handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    if not is_owner(update.effective_user.id):
        await notify_callback(update.callback_query, "فقط مالک ربات دسترسی داره.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if action == "stats" or action.startswith("stats:"):
        await handle_admin_stats(update, context, action)
    elif action == "user" or action.startswith("user:"):
        await handle_admin_user(update, context, action)
    elif action == "plans" or action.startswith("plans:") or action == "set_plan":
        await handle_plan_callback(update, context, action)
    elif action in ("cost_dashboard", "llm_costs", "llm_pricing"):
        await handle_cost_callback(update, context, action)
    elif action.startswith("ai_") or action.startswith("fallback") or action in ("help:presets", "help:fallback_chain"):
        await handle_ai_callback(update, context, action)
    elif action == "back":
        awaiting = context.user_data.get("awaiting", "") or ""
        has_pending_user = any(context.user_data.get(k) for k in ("pending_dm", "pending_plan", "pending_block"))
        has_pending_broadcast = bool(context.user_data.get("pending_broadcast"))
        # User-management awaiting or preview pending → back to user management
        if (
            awaiting.startswith("admin_user_search")
            or awaiting.startswith("admin_user_set_plan")
            or awaiting.startswith("admin_user_message")
            or has_pending_user
        ):
            clear_admin_pending_state(context)
            await _clear_awaiting_prompt(context)
            await _edit_or_send(update, context, BTN_ADMIN_USER_MANAGE, reply_markup=user_management_keyboard())
            await notify_callback(update.callback_query, "بازگشت", intent=CallbackNoticeIntent.INFO)
        elif awaiting.startswith("admin_broadcast") or has_pending_broadcast:
            clear_admin_pending_state(context)
            await _clear_awaiting_prompt(context)
            await _edit_or_send(update, context, "پنل مدیریت ربات:", reply_markup=admin_panel_keyboard())
            await notify_callback(update.callback_query, "بازگشت", intent=CallbackNoticeIntent.INFO)
        elif awaiting.startswith("llm_cost") or awaiting == "llm_price_rate":
            clear_admin_pending_state(context)
            await _clear_awaiting_prompt(context)
            await _show_llm_cost_dashboard(update, context)
            await notify_callback(update.callback_query, "بازگشت", intent=CallbackNoticeIntent.INFO)
        elif awaiting.startswith("ai_preset_edit:"):
            parts = awaiting.split(":", 2)
            preset_name = parts[1] if len(parts) == 3 else ""
            clear_admin_pending_state(context)
            await _clear_awaiting_prompt(context)
            if preset_name:
                await _edit_ai_preset(update, context, preset_name)
            else:
                await _show_ai_settings(update, context)
            await notify_callback(update.callback_query, "بازگشت", intent=CallbackNoticeIntent.INFO)
        elif awaiting.startswith("ai_preset_full_edit:"):
            parts = awaiting.split(":", 2)
            preset_name = parts[1] if len(parts) >= 2 else ""
            clear_admin_pending_state(context)
            await _clear_awaiting_prompt(context)
            if preset_name:
                await _edit_ai_preset(update, context, preset_name)
            else:
                await _show_ai_settings(update, context)
            await notify_callback(update.callback_query, "بازگشت", intent=CallbackNoticeIntent.INFO)
        elif awaiting.startswith("admin_plan_full_edit:"):
            clear_admin_pending_state(context)
            await _clear_awaiting_prompt(context)
            await _exit_awaiting_flow(update, context, via_callback=True)
        elif awaiting.startswith("ai_") or awaiting.startswith("admin_group") or awaiting.startswith("admin_ai"):
            clear_admin_pending_state(context)
            await _clear_awaiting_prompt(context)
            await _show_ai_settings(update, context)
            await notify_callback(update.callback_query, "بازگشت", intent=CallbackNoticeIntent.INFO)
        else:
            clear_admin_pending_state(context)
            await _clear_awaiting_prompt(context)
            await _edit_or_send(update, context, "پنل مدیریت ربات:", reply_markup=admin_panel_keyboard())
            await notify_callback(update.callback_query, "بازگشت", intent=CallbackNoticeIntent.INFO)
    elif action == "cancel":
        clear_admin_pending_state(context)
        await _clear_awaiting_prompt(context)
        await _edit_or_send(update, context, "عملیات لغو شد.", reply_markup=admin_panel_keyboard())
        await notify_callback(update.callback_query, "لغو شد", intent=CallbackNoticeIntent.INFO)
    elif action == "broadcast":
        context.user_data["awaiting"] = "admin_broadcast"
        await notify_callback(update.callback_query)
        msg = await send_pretty.send(
            update.effective_chat.id,
            "متن پیام همگانی رو بفرست:",
            bot=context.bot,
            raw=send_pretty.RawFormat.PLAIN,
            keyboard=admin_awaiting_inline_keyboard(),
        )
        _store_awaiting_msg(context, update, msg)
    elif action == "broadcast_confirm":
        pending = context.user_data.get("pending_broadcast")
        if not pending or not pending.get("text"):
            await notify_callback(update.callback_query, "پیش‌نمایشی یافت نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        global _BROADCAST_RUNNING
        if _BROADCAST_RUNNING:
            await notify_callback(update.callback_query, "یک ارسال همگانی در حال انجام است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        await notify_callback(update.callback_query, "در حال ارسال…", intent=CallbackNoticeIntent.INFO)
        _BROADCAST_RUNNING = True
        try:
            users = db.all_active_users()
            mark_awaiting_consumed(context)
            context.user_data.pop("pending_broadcast", None)
            context.user_data.pop("awaiting", None)
            html = pending.get("html") or pending.get("text", "")
            text_val = pending.get("text", "")
            use_html = bool(html and html != text_val)
            send_text = html if use_html else text_val
            send_kwargs: dict = {}
            if use_html:
                send_kwargs["parse_mode"] = ParseMode.HTML
            sem = asyncio.Semaphore(BROADCAST_MAX_CONCURRENCY)
            sent = 0
            for i in range(0, len(users), 100):
                chunk = users[i : i + 100]
                results = await asyncio.gather(
                    *(_broadcast_send_one(context.bot, u["user_id"], send_text, sem, send_kwargs) for u in chunk)
                )
                sent += sum(1 for r in results if r)
            try:
                await notify_callback(update.callback_query, "ارسال شد.", intent=CallbackNoticeIntent.SUCCESS)
            except BadRequest:
                pass
            await send_pretty.say(
                update,
                context,
                f"پیام برای {sent} کاربر ارسال شد.",
                raw=send_pretty.RawFormat.PLAIN,
            )
        finally:
            _BROADCAST_RUNNING = False
        return
    elif action == "broadcast_cancel":
        clear_admin_pending_state(context)
        await _clear_awaiting_prompt(context)
        await _edit_or_send(update, context, "لغو شد.", reply_markup=admin_panel_keyboard())
        await notify_callback(update.callback_query, "لغو شد.", intent=CallbackNoticeIntent.INFO)
        return
    elif action == "broadcast_edit":
        context.user_data.pop("pending_broadcast", None)
        context.user_data["awaiting"] = "admin_broadcast"
        await notify_callback(update.callback_query)
        msg = await send_pretty.send(
            update.effective_chat.id,
            "متن پیام همگانی را دوباره بفرست:",
            bot=context.bot,
            raw=send_pretty.RawFormat.PLAIN,
            keyboard=admin_awaiting_inline_keyboard(),
        )
        _store_awaiting_msg(context, update, msg)
        return
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
            f"🔑 API Key: <code>{html_escape(masked)}</code>",
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
    elif action == "maintenance":
        active = db.is_maintenance_mode()
        await _edit_or_send(
            update,
            context,
            _maintenance_status_text(),
            reply_markup=maintenance_keyboard(active),
        )
        await notify_callback(update.callback_query, "حالت تعمیر", intent=CallbackNoticeIntent.INFO)
    elif action == "maintenance:toggle":
        active = db.is_maintenance_mode()
        db.set_maintenance_mode(not active)
        await _edit_or_send(
            update,
            context,
            _maintenance_status_text(),
            reply_markup=maintenance_keyboard(db.is_maintenance_mode()),
        )
        await notify_callback(
            update.callback_query,
            "فعال شد" if db.is_maintenance_mode() else "غیرفعال شد",
            intent=CallbackNoticeIntent.SUCCESS,
        )
    elif action == "maintenance:edit":
        context.user_data["awaiting"] = "admin_maintenance_msg"
        await notify_callback(update.callback_query)
        msg = await say(update, context, "متن پیام حالت تعمیر را بنویسید (برای کاربران هنگام تعمیر نمایش داده می‌شود):", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
        _store_awaiting_msg(context, update, msg)
    elif action == "tts_cache":
        from config import resolve_tts_cache_chat_id
        cur = resolve_tts_cache_chat_id() or db.get_setting("tts_cache_chat_id", "")
        from config.keyboards.admin import tts_cache_keyboard
        await _edit_or_send(update, context, f"🎙 کش TTS\nکانال فعلی: {cur or '—'}\nبرای تنظیم آیدی کانال (مثلاً -100...) دکمه تنظیم را بزنید.", reply_markup=tts_cache_keyboard(cur))
    elif action == "tts_cache:set":
        context.user_data["awaiting"] = "admin_tts_cache_chat_id"
        await notify_callback(update.callback_query)
        await say(update, context, "آیدی کانال کش TTS را بفرست (مثلاً -100123...). برای غیرفعال کردن خالی بفرست.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
    elif action == "tts_cache:clear":
        db.set_setting("tts_cache_chat_id", "")
        from config.keyboards.admin import tts_cache_keyboard
        await _edit_or_send(update, context, "🗑 کش TTS غیرفعال شد.", reply_markup=tts_cache_keyboard(""))
        await notify_callback(update.callback_query, "پاک شد", intent=CallbackNoticeIntent.SUCCESS)
    elif action == "tts_cache:test":
        from config import resolve_tts_cache_chat_id
        cid = resolve_tts_cache_chat_id()
        if not cid:
            await notify_callback(update.callback_query, "کانال تنظیم نشده.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        else:
            try:
                await context.bot.send_message(chat_id=cid, text="🧪 تست کش TTS")
                await notify_callback(update.callback_query, "تست ارسال شد", intent=CallbackNoticeIntent.SUCCESS)
            except Exception as e:
                await notify_callback(update.callback_query, f"خطا: {e}", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
    elif action == "backup":
        # O-backup-panel: callback entry that mirrors /backup command
        await notify_callback(update.callback_query, "در حال تهیه پشتیبان…", intent=CallbackNoticeIntent.INFO)
        try:
            data = await asyncio.to_thread(db.export_db_bytes)
            await update.effective_message.reply_document(
                document=io.BytesIO(data),
                filename=f"hamzaban_backup_{datetime.datetime.now(_app_timezone).strftime('%Y%m%d_%H%M%S')}.db",
                caption="📦 پشتیبان دیتابیس",
            )
        except Exception as exc:
            logger.exception("Backup failed")
            await _edit_or_send(update, context, f"خطا در تهیه پشتیبان: {exc}", reply_markup=admin_panel_keyboard())
    elif action == "restore":
        context.user_data["awaiting"] = "admin_restore"
        await notify_callback(update.callback_query)
        msg = await _edit_or_send(
            update, context,
            "فایل دیتابیس (.db) را آپلود کنید.\n⚠️ این کار دیتابیس فعلی را کاملاً جایگزین می‌کند.",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
        _store_awaiting_msg(context, update, msg)
    elif action.startswith("display_toggle:confirm:"):
        field = action.split(":", 2)[2]
        from config.catalog import DISPLAY_TOGGLE_FIELDS, HIGH_VALUE_TOGGLES
        if field not in DISPLAY_TOGGLE_FIELDS or field not in HIGH_VALUE_TOGGLES:
            await notify_callback(update.callback_query, "فیلد نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        from services.db.display_toggles import get_global_defaults, set_global_defaults
        current = get_global_defaults()
        current[field] = False
        set_global_defaults(current)
        from config.keyboards import display_toggles_keyboard
        await _edit_or_send(
            update, context,
            "🎛 تنظیمات نمایش کارت — روی هر فیلد بزن تا روشن/خاموش شود.",
            reply_markup=display_toggles_keyboard(current),
        )
        await notify_callback(update.callback_query, "خاموش شد.", intent=CallbackNoticeIntent.SUCCESS)
    elif action == "display_toggle:cancel":
        from services.db.display_toggles import get_global_defaults
        from config.keyboards import display_toggles_keyboard
        current = get_global_defaults()
        await _edit_or_send(
            update, context,
            "🎛 تنظیمات نمایش کارت — روی هر فیلد بزن تا روشن/خاموش شود.",
            reply_markup=display_toggles_keyboard(current),
        )
        await notify_callback(update.callback_query, "انصراف", intent=CallbackNoticeIntent.INFO)
    elif action.startswith("display_toggle:"):
        field = action.split(":", 1)[1]
        if ":" in field:
            await notify_callback(update.callback_query, "فیلد نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        from config.catalog import DISPLAY_TOGGLE_FIELDS, HIGH_VALUE_TOGGLES
        if field not in DISPLAY_TOGGLE_FIELDS:
            await notify_callback(update.callback_query, "فیلد نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        from services.db.display_toggles import get_global_defaults, set_global_defaults
        current = get_global_defaults()
        currently_enabled = bool(current.get(field, True))
        if currently_enabled and field in HIGH_VALUE_TOGGLES:
            from config.keyboards import DISPLAY_TOGGLE_FA_LABELS, display_toggle_confirm_keyboard
            label = DISPLAY_TOGGLE_FA_LABELS.get(field, field)
            await _edit_or_send(
                update,
                context,
                f"⚠️ خاموش کردن «{label}» کیفیت یادگیری همه کاربران را کاهش میدهد (پیش‌فرض سراسری). باز هم خاموشش میکنید؟",
                reply_markup=display_toggle_confirm_keyboard(field, is_admin=True),
            )
            await notify_callback(update.callback_query, "تأیید لازم است", intent=CallbackNoticeIntent.INFO)
            return
        new_val = not currently_enabled
        current[field] = new_val
        set_global_defaults(current)
        from config.keyboards import display_toggles_keyboard
        await _edit_or_send(
            update, context,
            "🎛 تنظیمات نمایش کارت — روی هر فیلد بزن تا روشن/خاموش شود.",
            reply_markup=display_toggles_keyboard(current),
        )
        await notify_callback(update.callback_query, "ذخیره شد.", intent=CallbackNoticeIntent.SUCCESS)
    elif action == "display_toggles":
        from services.db.display_toggles import get_global_defaults
        from config.keyboards import display_toggles_keyboard
        current = get_global_defaults()
        await _edit_or_send(
            update, context,
            "🎛 تنظیمات نمایش کارت — روی هر فیلد بزن تا روشن/خاموش شود.",
            reply_markup=display_toggles_keyboard(current),
        )


async def handle_flow_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the ``flow:back`` callback by resuming the previous editing flow.

    Encapsulates the awaiting-key-aware back-navigation logic that previously
    lived inline in ``bot.py``'s callback_router. Handles all awaiting states,
    not only admin ones (e.g., ``ask_word`` is also supported). Behavior is
    unchanged.
    """
    awaiting = context.user_data.get("awaiting", "") or ""
    clear_admin_pending_state(context)
    await _clear_awaiting_prompt(context)
    if awaiting.startswith("ai_preset_edit:"):
        parts = awaiting.split(":", 2)
        preset_name = parts[1] if len(parts) == 3 else ""
        if preset_name:
            await _edit_ai_preset(update, context, preset_name)
        else:
            await _show_ai_settings(update, context)
    elif awaiting.startswith("ai_preset_full_edit:"):
        parts = awaiting.split(":", 2)
        preset_name = parts[1] if len(parts) >= 2 else ""
        if preset_name:
            await _edit_ai_preset(update, context, preset_name)
        else:
            await _show_ai_settings(update, context)
    elif awaiting.startswith("admin_plan_full_edit:"):
        context.user_data.pop("plan_full_edit", None)
        await _exit_awaiting_flow(update, context, via_callback=True)
    elif awaiting:
        await _exit_awaiting_flow(update, context, via_callback=True)
    else:
        await notify_callback(update.callback_query, "فعلاً چیزی برای لغو نیست.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)


def _register_admin_flows() -> None:
    """Register every admin-domain awaiting flow with the central registry.

    Prefixes map to the domain sub-router handlers (cost/plans/ai) or to small
    local adapters for the exact-key infra flows (broadcast/restore/set_plan).
    The registry owns longest-prefix routing, so no manual ``startswith``
    dispatch survives here.
    """
    global _ADMIN_FLOWS_REGISTERED
    if _ADMIN_FLOWS_REGISTERED:
        return
    _ADMIN_FLOWS_REGISTERED = True

    async def _handle_plans_set_plan(update, context, awaiting, text):
        await _handle_plans_text_input(update, context, text)

    async def _handle_admin_broadcast(update, context, awaiting, text):
        if _BROADCAST_RUNNING:
            mark_awaiting_consumed(context)
            await _clear_awaiting_prompt(context)
            await send_pretty.say(
                update,
                context,
                "یک ارسال همگانی در حال انجام است؛ کمی بعد دوباره تلاش کن.",
                raw=send_pretty.RawFormat.PLAIN,
            )
            return
        msg = text.strip() if isinstance(text, str) else ""
        if not msg:
            await _clear_awaiting_prompt(context)
            context.user_data["awaiting"] = awaiting
            m = await send_pretty.say(
                update,
                context,
                "متن پیام خالی است. دوباره بفرستید یا لغو کنید.",
                raw=send_pretty.RawFormat.PLAIN,
            )
            _store_awaiting_msg(context, update, m)
            return
        if len(msg) > 4000:
            await _clear_awaiting_prompt(context)
            context.user_data["awaiting"] = awaiting
            m = await say(update, context, "متن طولانی است (حداکثر ۴۰۰۰ کاراکتر). لطفاً کوتاه‌تر بفرستید.", raw=RawFormat.PLAIN, mode="send")
            _store_awaiting_msg(context, update, m)
            return
        # Capture HTML-preserving representation (R3/R4).
        html = None
        try:
            em = getattr(update, "effective_message", None) or getattr(update, "message", None)
            html = getattr(em, "text_html", None) if em is not None else None
        except Exception:
            html = None
        if not html:
            html = msg
        # Store pending for preview+confirm (no transaction held across await).
        # Count is cached in pending_broadcast so preview needs only one DB scan;
        # confirm re-queries for a fresh recipient list (users may have changed).
        count = len(db.all_active_users())
        context.user_data["pending_broadcast"] = {"text": msg, "html": html, "count": count}
        mark_awaiting_consumed(context)
        await _clear_awaiting_prompt(context)
        use_html = bool(html and html != msg)
        preview_text = f"{html_escape('👁 پیش‌نمایش پیام همگانی (')}{count}{html_escape(' کاربر):')}\n\n{html}\n\n{html_escape('تایید می‌کنید؟')}"
        await send_pretty.say(
            update,
            context,
            preview_text,
            raw=send_pretty.RawFormat.HTML if use_html else send_pretty.RawFormat.PLAIN,
            keyboard=broadcast_preview_keyboard(),
        )

    async def _handle_admin_maintenance_msg(update, context, awaiting, text):
        db.set_maintenance_message(text)
        mark_awaiting_consumed(context)  # DB write is irreversible (B5/Kilo CRITICAL)
        context.user_data["awaiting"] = None
        await say(update, context, "✅ پیام حالت تعمیر ذخیره شد.", raw=RawFormat.PLAIN, keyboard=main_menu(is_owner(update.effective_user.id)), mode="send")

    async def _handle_admin_tts_cache(update, context, awaiting, text):
        val = (text or "").strip()
        db.set_setting("tts_cache_chat_id", val)
        mark_awaiting_consumed(context)
        context.user_data["awaiting"] = None
        from config.keyboards.admin import tts_cache_keyboard
        await _edit_or_send(update, context, f"✅ کانال کش TTS: {val or '— (غیرفعال)'}", reply_markup=tts_cache_keyboard(val))

    async def _handle_admin_restore(update, context, awaiting, text):
        mark_awaiting_consumed(context)  # terminal re-prompt (B5/Kilo CRITICAL)
        context.user_data["awaiting"] = None
        await say(update, context, "لطفاً یک فایل دیتابیس (.db) آپلود کنید.\n"
            "دوباره /restore را بزنید.", raw=RawFormat.PLAIN, mode="send")

    async def _handle_ai_preset_name(update, context, awaiting, text):
        await _handle_ai_preset_new_name(update, context, text)

    async def _handle_custom_test_prompt(update, context, awaiting, text):
        state = context.user_data.setdefault("custom_test_state", {})
        state["prompt"] = text
        context.user_data["custom_test_state"] = state
        await _custom_test_step_lang(update, context)

    async def _handle_ai_preset_edit(update, context, awaiting, text):
        parts = awaiting.split(":", 2)
        if len(parts) == 3:
            await _handle_ai_preset_field_input(update, context, parts[1], parts[2], text)

    async def _handle_cost_text(update, context, awaiting, text):
        await _handle_cost_text_input(update, context, awaiting, text)

    async def _handle_ai_text(update, context, awaiting, text):
        await _handle_ai_text_input(update, context, awaiting, text)

    async def _handle_plan_full_edit(update, context, awaiting, text):
        parts = awaiting.split(":", 3)
        if len(parts) == 3:
            plan_name, field_idx = parts[1], parts[2]
            await _handle_plan_wizard_input(update, context, plan_name, int(field_idx), text)

    async def _handle_ai_full_edit(update, context, awaiting, text):
        parts = awaiting.split(":", 3)
        if len(parts) == 3:
            preset_name, field_idx = parts[1], parts[2]
            await _handle_full_edit_input(update, context, preset_name, int(field_idx), text)

    for key in ("llm_cost_user", "llm_cost_model", "llm_price_rate"):
        register_flow(key, _handle_cost_text)

    register_flow("admin_set_plan", _handle_plans_set_plan)
    register_flow("admin_broadcast", _handle_admin_broadcast)
    register_flow("admin_restore", _handle_admin_restore)
    register_flow("admin_maintenance_msg", _handle_admin_maintenance_msg)
    register_flow("admin_tts_cache_chat_id", _handle_admin_tts_cache)
    register_flow("ai_preset_new_name", _handle_ai_preset_name)
    register_flow("admin_ai_preset_new_name", _handle_ai_preset_name)
    register_flow("ai_custom_test_prompt", _handle_custom_test_prompt)

    for prefix in (
        "admin_group_batch_key:",
        "admin_group_set_label:",
        "admin_group_manager_rename:",
        "ai_fallback_rank:",
        "ai_preset_create_priority:",
    ):
        register_flow(prefix, _handle_ai_text)

    register_flow("ai_preset_edit:", _handle_ai_preset_edit)
    register_flow("admin_plan_full_edit:", _handle_plan_full_edit)
    register_flow("ai_preset_full_edit:", _handle_ai_full_edit)


_register_admin_flows()


# ======== AI Settings Panel Handlers ========


# ======== Backup / Restore ========

async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the current database file to the admin."""
    if not is_owner(update.effective_user.id):
        await say(update, context, "فقط مالک ربات دسترسی داره.", raw=RawFormat.PLAIN, mode="send")
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
    """Handle uploaded database file for restore."""
    if not is_owner(update.effective_user.id):
        await say(update, context, "فقط مالک ربات دسترسی داره.", raw=RawFormat.PLAIN, mode="send")
        return
    if context.user_data.get("awaiting") != "admin_restore":
        await say(update, context, "ابتدا /restore را بزنید.", raw=RawFormat.PLAIN, mode="send")
        return
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


# ======== Registry registration (R1, coarse) ========
#
# The admin and LLM-cost domains are registered as coarse routes in the central
# callback registry (services/routing.py). dispatch() performs the owner gate
# (admin is owner-only) and passes the sub-action (the remainder after the
# matched prefix) to each handler. This keeps the existing sub-router if/elif
# chains (admin_stats / admin_plans / admin_cost / admin_ai) intact while
# removing the duplicate empty-ack that used to fire in bot.py (the B1 fix).


async def _route_llm(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Adapter: rebuild the full ``llm:...`` data expected by ``_handle_llm_callback``."""
    await _handle_llm_callback(update, context, f"llm:{action}")


def register_admin_routes() -> None:
    """Register the admin and LLM-cost domains into the central routing registry.

    Called at import time so the registry is populated before any callback is
    routed. Idempotent: re-registration overwrites the same prefixes.
    """
    from services.routing import register

    register("admin", _handle_admin_callback, owner_only=True)
    register("llm", _route_llm, owner_only=True)


register_admin_routes()
