import asyncio
import calendar
import datetime
import hashlib
import logging
import os
from collections import defaultdict
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import APP_TIMEZONE, DB_PATH, OWNER_ID, PLANS, is_owner
from services import db
from services.ai import ai
from services.ai import ai_presets
from services.ai import prompts
from services.utils.helpers import _edit_or_send, _send_with_retry
from config.catalog import GOALS, LANGUAGES, LEVELS
from config.keyboards import (
    BTN_BACK,
    IBTN_BACK,
    admin_panel_keyboard,
    main_menu,
    awaiting_inline_keyboard,
    admin_awaiting_inline_keyboard,
    llm_cost_dashboard_keyboard,
    llm_cost_kind_keyboard,
    llm_cost_plan_keyboard,
    llm_cost_pricing_keyboard,
    llm_cost_status_keyboard,
    phonetic_settings_keyboard,
    ai_settings_keyboard,
    ai_presets_list_keyboard,
    ai_preset_view_keyboard,
    ai_preset_edit_keyboard,
    ai_fallback_keyboard,
    ai_custom_test_wizard_keyboard,
    admin_cost_keyboard,
    fallback_chain_keyboard,
    log_level_keyboard,
    user_activity_keyboard,
    IBTN_FULL_EDIT_WIZARD,
    IBTN_FULL_EDIT_NEXT,
    IBTN_FULL_EDIT_SKIP,
    IBTN_FULL_EDIT_CANCEL_WIZARD,
    IBTN_FULL_EDIT_SAVE_ALL,
    IBTN_VIEW_MODE_LINEAR,
    IBTN_VIEW_MODE_GROUPED,
    IBTN_GROUP_BATCH_KEY,
    IBTN_GROUP_SET_LABEL,
    IBTN_GROUP_OPEN,
    IBTN_PAGE_PREV,
    IBTN_PAGE_NEXT,
    IBTN_RANK_JUMP,
    IBTN_CONSUMPTION_DETAILS,
    IBTN_HELP_PRESETS,
    IBTN_HELP_FALLBACK,
    stats_menu_keyboard,
    stats_back_keyboard,
)

logger = logging.getLogger(__name__)
_app_timezone = ZoneInfo(APP_TIMEZONE)

_FIELD_HELP = {
    "name": "نام یکتای پریست. فقط حروف انگلیسی (a-z)، اعداد (0-9) و زیرخط (_) مجاز است. بعد از ذخیره قابل تغییر نیست.",
    "api_key": "کلید API سرویس‌دهنده. می‌توانید مقدار ثابت (sk-...) یا متغیر محیطی (مثلاً $MY_KEY) وارد کنید.",
    "base_url": "آدرس سرور سازگار با OpenAI. نمونه: https://api.example.com/v1",
    "model": "نام دقیق مدل. نمونه: gpt-4o-mini یا gemini-2.0-flash-lite",
    "max_concurrency": "تعداد درخواست‌هایی که هم‌زمان به این سرویس‌دهنده فرستاده می‌شود. عدد ۲ یا ۳ معمول است.",
    "max_rpm": "بیشترین تعداد درخواست در هر دقیقه. صفر = بدون محدودیت.",
    "max_tpm": "بیشترین تعداد توکن ورودی و خروجی در هر دقیقه. صفر = بدون محدودیت.",
    "daily_batch_size": "تعداد کارت واژگان در هر دسته که یک‌جا از AI درخواست می‌شود. بین ۳ تا ۱۲.",
    "max_daily_req": "سقف تعداد درخواست به این پریست در هر روز. صفر = بدون محدودیت.",
    "timeout_seconds": "مدت زمان انتظار برای پاسخ از سرویس‌دهنده (به ثانیه). عدد اعشاری مجاز است.",
    "temperature": "میزان خلاقیت مدل. بین ۰.۰ (دقیق) تا ۲.۰ (خلاق). پیش‌فرض: ۰.۶",
    "max_output_tokens": "حداکثر تعداد توکن در هر پاسخ. پیش‌فرض: ۴۰۹۶",
    "priority": "اولویت در زنجیره فال‌بک. عدد کمتر = اولویت بیشتر. پریست با priority=۰ اولین نفری است که امتحان می‌شود.",
    "is_emergency": "آیا این پریست فقط برای مواقع اضطراری است؟ پریست‌های اضطراری همیشه بعد از پریست‌های عادی امتحان می‌شوند.",
    "in_fallback_chain": "آیا این پریست به‌صورت خودکار در زنجیره فال‌بک شرکت کند؟ اگر خاموش شود، فقط با انتخاب دستی قابل استفاده است.",
    "input_cost_per_million": "هزینه هر یک میلیون توکن ورودی (درخواست) به دلار. خالی = استفاده از مقدار سراسری تنظیم شده در داشبورد هزینه.",
    "output_cost_per_million": "هزینه هر یک میلیون توکن خروجی (پاسخ) به دلار. خالی = استفاده از مقدار سراسری.",
    "group_label": "برچسب دلخواه برای گروه‌بندی پریست‌هایی که کلید API مشترک دارند. نمونه: «سرویس‌دهنده اصلی» یا «پشتیبان رایگان»",
}


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
    if action == "stats":
        await _edit_or_send(
            update, context,
            "📊 آمار کاربران\n\nیکی از بخش‌ها را انتخاب کن:",
            reply_markup=stats_menu_keyboard(),
        )
    elif action.startswith("stats:"):
        sub = action.split(":", 1)[1]
        if sub == "overview":
            data = db.count_users_overview()
            await _edit_or_send(
                update, context,
                f"👥 نمای کلی کاربران\n\n"
                f"• کل کاربران: {data['total']}\n"
                f"• ثبت‌نام کامل: {data['onboarded']}\n"
                f"• بلاک کرده: {data['blocked']}",
                reply_markup=stats_back_keyboard(),
            )
        elif sub == "distribution":
            lines = ["📊 توزیع کاربران\n"]
            for label, field in [("پلن", "plan"), ("زبان مقصد", "target_lang"), ("هدف", "goal"), ("سطح", "level")]:
                rows = db.count_users_grouped(field)
                if not rows:
                    continue
                lines.append(f"{label}:")
                for r in rows:
                    val = r["val"] or "ناشناخته"
                    lines.append(f"  {val}: {r['cnt']}")
                lines.append("")
            await _edit_or_send(
                update, context,
                "\n".join(lines).strip(),
                reply_markup=stats_back_keyboard(),
            )
        elif sub == "activity":
            from datetime import timedelta, date
            today = date.today()
            today_str = today.isoformat()
            week_ago = (today - timedelta(days=7)).isoformat()
            month_ago = (today - timedelta(days=30)).isoformat()
            active_today = db.count_active_users_since(today_str)
            active_week = db.count_active_users_since(week_ago)
            active_month = db.count_active_users_since(month_ago)
            total_words = db.count_saved_words_total()
            today_llm = db.count_llm_requests_since(today_str)
            await _edit_or_send(
                update, context,
                f"📈 فعالیت کاربران\n\n"
                f"• فعال امروز: {active_today}\n"
                f"• فعال این هفته: {active_week}\n"
                f"• فعال این ماه: {active_month}\n\n"
                f"• کل لغات ذخیره‌شده: {total_words:,}\n"
                f"• درخواست‌های AI امروز: {today_llm}",
                reply_markup=stats_back_keyboard(),
            )
        else:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
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
            "پلن‌ها: free، silver، gold",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=admin_awaiting_inline_keyboard(),
        )
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
        from bot import _apply_log_level
        _apply_log_level(level_name)
        await _show_log_level_settings(update, context)
    elif action == "user_activity_log":
        await _show_user_activity_settings(update, context)
    elif action == "user_activity:toggle":
        current = db.get_setting("user_activity_log", "off")
        new_value = "off" if current == "on" else "on"
        db.set_setting("user_activity_log", new_value)
        await _show_user_activity_settings(update, context)


def _llm_cost_default_state() -> dict[str, object]:
    return {
        "range": "mtd",
        "detail": False,
        "plan": None,
        "user_id": None,
        "request_kind": None,
        "model": None,
        "outcome": None,
    }


def _llm_cost_state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    state = context.user_data.get("llm_cost_state")
    if not isinstance(state, dict):
        state = _llm_cost_default_state()
    else:
        merged = _llm_cost_default_state()
        merged.update({key: state.get(key, value) for key, value in merged.items()})
        state = merged
    context.user_data["llm_cost_state"] = state
    return state


def _llm_cost_set_state(
    context: ContextTypes.DEFAULT_TYPE,
    **updates,
) -> dict[str, object]:
    state = _llm_cost_state(context).copy()
    for key, value in updates.items():
        if value == "":
            value = None
        state[key] = value
    context.user_data["llm_cost_state"] = state
    return state


def _llm_cost_range_bounds(range_name: str) -> tuple[str, str, str]:
    today = datetime.datetime.now(_app_timezone).date()
    if range_name == "today":
        start = end = today
        label = "today"
    elif range_name == "7d":
        start = today - datetime.timedelta(days=6)
        end = today
        label = "7d"
    elif range_name == "30d":
        start = today - datetime.timedelta(days=29)
        end = today
        label = "30d"
    elif range_name == "all":
        return "", "", "ALL"
    else:
        start = today.replace(day=1)
        end = today
        label = "MTD"
    return start.isoformat(), end.isoformat(), label


def _llm_cost_query_filters(state: dict[str, object]) -> dict[str, object]:
    start_date, end_date, _ = _llm_cost_range_bounds(str(state.get("range") or "mtd"))
    filters: dict[str, object] = {
        "start_date": start_date,
        "end_date": end_date,
    }
    for key in ("plan", "user_id", "request_kind", "model", "outcome"):
        value = state.get(key)
        if value not in {None, "", "all"}:
            filters[key] = value
    return filters


def _llm_cost_currency_text(cost_usd: float, cost_toman: float) -> str:
    return f"${cost_usd:,.4f} / {round(cost_toman):,} Toman"


def _llm_cost_projection(filters: dict[str, object]) -> tuple[str, str, float] | None:
    month_start = datetime.datetime.now(_app_timezone).date().replace(day=1)
    today = datetime.datetime.now(_app_timezone).date()
    projection_filters = dict(filters)
    projection_filters["start_date"] = month_start.isoformat()
    projection_filters["end_date"] = today.isoformat()
    summary = db.summarize_llm_requests(projection_filters)
    request_count = int(summary.get("request_count") or 0)
    cost_usd = float(summary.get("cost_usd") or 0)
    cost_toman = float(summary.get("cost_toman") or 0)
    if request_count <= 0 or cost_usd <= 0:
        return None
    month_days = calendar.monthrange(today.year, today.month)[1]
    elapsed_days = max((today - month_start).days + 1, 1)
    linear_usd = (cost_usd / elapsed_days) * month_days
    linear_toman = (cost_toman / elapsed_days) * month_days
    daily_rows = db.recent_llm_requests(projection_filters, limit=5000)
    daily_costs: dict[str, float] = defaultdict(float)
    for row in daily_rows:
        daily_costs[str(row["request_date"])] += float(row["cost_usd"] or 0)
    recent_days = sorted(daily_costs)[-7:]
    if recent_days:
        rolling_usd = sum(daily_costs[day] for day in recent_days) / len(recent_days) * month_days
        rolling_toman = rolling_usd * (
            cost_toman / cost_usd if cost_usd else db.get_llm_cost_profile()["usd_to_toman_rate"]
        )
    else:
        rolling_toman = linear_toman
        rolling_usd = linear_usd
    ratio = rolling_usd / linear_usd if linear_usd else 1.0
    return (
        _llm_cost_currency_text(linear_usd, linear_toman),
        _llm_cost_currency_text(rolling_usd, rolling_toman),
        ratio,
    )


def _llm_cost_filter_label(value: object, fallback: str = "all") -> str:
    if value in {None, "", "all"}:
        return fallback
    return str(value)


def _llm_cost_state_label(state: dict[str, object]) -> str:
    parts = [
        f"range={state.get('range', 'mtd')}",
        f"plan={_llm_cost_filter_label(state.get('plan'))}",
        f"user={_llm_cost_filter_label(state.get('user_id'))}",
        f"kind={_llm_cost_filter_label(state.get('request_kind'))}",
        f"model={_llm_cost_filter_label(state.get('model'))}",
        f"status={_llm_cost_filter_label(state.get('outcome'))}",
    ]
    return " • ".join(parts)


def _llm_cost_percent(numerator: int | float, denominator: int | float) -> str:
    if not denominator:
        return "0.0%"
    return f"{(float(numerator) / float(denominator)) * 100:.1f}%"


def _llm_cost_status_icon(outcome: object) -> str:
    return {
        "success": "🟢",
        "failure_billed": "🔴",
        "failure_zero_cost": "⚪",
    }.get(str(outcome), "⚪")


def _llm_cost_report_text(state: dict[str, object]) -> str:
    filters = _llm_cost_query_filters(state)
    summary = db.summarize_llm_requests(filters)
    request_count = int(summary.get("request_count") or 0)
    prompt_tokens = int(summary.get("prompt_tokens") or 0)
    completion_tokens = int(summary.get("completion_tokens") or 0)
    total_tokens = int(summary.get("total_tokens") or 0)
    cost_usd = float(summary.get("cost_usd") or 0)
    cost_toman = float(summary.get("cost_toman") or 0)
    avg_latency = summary.get("avg_latency_ms")
    avg_cost = cost_usd / request_count if request_count else 0.0
    success_count = int(summary.get("success_count") or 0)
    billed_failures = int(summary.get("billed_failure_count") or 0)
    zero_cost_failures = int(summary.get("zero_cost_failure_count") or 0)
    billed_failure_cost_usd = float(summary.get("billed_failure_cost_usd") or 0)
    billed_failure_cost_toman = float(summary.get("billed_failure_cost_toman") or 0)
    success_rate = _llm_cost_percent(success_count, request_count)
    billed_failure_rate = _llm_cost_percent(billed_failures, request_count)
    range_label = str(state.get("range") or "mtd").upper()

    lines = [
        "📊 LLM Cost Dashboard",
        f"Scope: {_llm_cost_state_label(state)}",
        "",
        f"Overview — {range_label}",
        f"📨 Requests: {request_count:,}",
        f"💳 Spend: {_llm_cost_currency_text(cost_usd, cost_toman)}",
        f"🪙 Avg cost/request: {_llm_cost_currency_text(avg_cost, avg_cost * db.get_llm_cost_profile()['usd_to_toman_rate'])}",
        f"🟢 Success rate: {success_rate} ({success_count:,})",
        f"🔴 Billed failure rate: {billed_failure_rate} ({billed_failures:,})",
        "",
        f"🧮 Tokens: prompt {prompt_tokens:,} • completion {completion_tokens:,} • total {total_tokens:,}",
        f"⏱ Avg latency: {round(float(avg_latency), 1) if avg_latency is not None else 0.0} ms",
    ]

    if billed_failures > 0 or (request_count and billed_failures / request_count >= 0.2):
        lines.extend(
            [
                "",
                "⚠️ Attention required",
                f"💸 Billed failures: {billed_failures:,} "
                f"({_llm_cost_currency_text(billed_failure_cost_usd, billed_failure_cost_toman)})",
                f"⚪ Zero-cost failures: {zero_cost_failures:,}",
            ]
        )
    else:
        lines.extend(["", "🟢 System health: no billable failures"])

    projection = None
    if state.get("range") == "mtd":
        projection = _llm_cost_projection(filters)
    if projection:
        linear, rolling, ratio = projection
        lines.extend(
            [
                "",
                "📈 Month-end Projection",
                f"- Linear: {linear} (MTD run rate)",
                f"- Rolling 7-day: {rolling} (recent daily average)",
            ]
        )
        if ratio >= 2:
            lines.append(f"⚠️ Rolling projection is {ratio:.1f}× the linear projection")

    breakdown_specs = [
        ("📦 By plan", "plan"),
        ("🔧 By preset", "preset_name"),
        ("🧩 By request kind", "request_kind"),
        ("🤖 By model", "model"),
    ]
    if state.get("user_id") is None:
        breakdown_specs.append(("👤 By user", "user_id"))
    for title, key in breakdown_specs:
        rows = db.breakdown_llm_requests(key, filters, limit=5)
        lines.append("")
        lines.append(title + ":")
        if not rows:
            lines.append("- none")
            continue
        for row in rows:
            bucket = row.get("bucket")
            if key == "plan":
                bucket = {
                    "free": "free",
                    "silver": "silver",
                    "gold": "gold",
                }.get(str(bucket), str(bucket))
            lines.append(
                f"- {bucket}: {int(row.get('request_count') or 0):,} req • "
                f"{_llm_cost_currency_text(float(row.get('cost_usd') or 0), float(row.get('cost_toman') or 0))} • "
                f"{_llm_cost_percent(float(row.get('cost_usd') or 0), cost_usd)} spend • "
                f"{_llm_cost_percent(int(row.get('billed_failure_count') or 0), int(row.get('request_count') or 0))} billed fail"
            )

    if state.get("detail"):
        rows = db.recent_llm_requests(filters, limit=10)
        lines.extend(["", "🧾 Recent Requests"])
        if not rows:
            lines.append("- none")
        else:
            for row in rows:
                lines.append(
                    f"- {str(row['created_at'])[:19]} "
                    f"{_llm_cost_status_icon(row['outcome'])} {row['outcome']} | "
                    f"{row['request_kind']} | {row['model']} | "
                    f"user {row['user_id']} / {row['plan']} | "
                    f"{int(row['total_tokens'] or 0):,} tok | "
                    f"{_llm_cost_currency_text(float(row['cost_usd'] or 0), float(row['cost_toman'] or 0))} | "
                    f"{round(float(row['latency_ms']), 1) if row['latency_ms'] is not None else 0.0} ms"
                )

    return "\n".join(lines)


def _llm_pricing_text() -> str:
    profile = db.get_llm_cost_profile()
    return "\n".join(
        [
            "LLM pricing defaults",
            f"- Input: ${profile['input_cost_usd_per_million']:,.4f} / 1M tokens",
            f"- Output: ${profile['output_cost_usd_per_million']:,.4f} / 1M tokens",
            f"- USD→Toman: {profile['usd_to_toman_rate']:,.0f}",
            "",
            "These values are the active defaults used by new requests unless the admin updates them.",
        ]
    )


async def _show_llm_cost_dashboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    detail: bool | None = None,
):
    state = _llm_cost_state(context)
    if detail is not None:
        state = _llm_cost_set_state(context, detail=detail)
    text = _llm_cost_report_text(state)
    if update.callback_query:
        await _edit_or_send(
            update,
            context,
            text,
            reply_markup=llm_cost_dashboard_keyboard(bool(state.get("detail"))),
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=llm_cost_dashboard_keyboard(bool(state.get("detail"))),
        )


async def _handle_llm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split(":")
    if len(parts) < 2:
        await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
        return
    action = parts[1]
    if action == "pricing" and len(parts) >= 2:
        if len(parts) == 2 or (len(parts) == 3 and parts[2] == "back"):
            await _show_llm_cost_dashboard(update, context)
        elif len(parts) == 3 and parts[2] == "set_input":
            context.user_data["awaiting"] = "llm_price_input"
            await _edit_or_send(
                update,
                context,
                "Send input cost per 1M tokens in USD:",
                reply_markup=admin_awaiting_inline_keyboard(),
            )
        elif len(parts) == 3 and parts[2] == "set_output":
            context.user_data["awaiting"] = "llm_price_output"
            await _edit_or_send(
                update,
                context,
                "Send output cost per 1M tokens in USD:",
                reply_markup=admin_awaiting_inline_keyboard(),
            )
        elif len(parts) == 3 and parts[2] == "set_rate":
            context.user_data["awaiting"] = "llm_price_rate"
            await _edit_or_send(
                update,
                context,
                "Send the USD→Toman rate:",
                reply_markup=admin_awaiting_inline_keyboard(),
            )
        else:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
        return
    if action == "range" and len(parts) == 3:
        _llm_cost_set_state(context, range=parts[2], detail=False)
        await _show_llm_cost_dashboard(update, context)
    elif action == "set" and len(parts) == 3:
        field = parts[2]
        if field == "plan":
            await _edit_or_send(
                update,
                context,
                "Select a plan:",
                reply_markup=llm_cost_plan_keyboard(),
            )
        elif field == "user":
            context.user_data["awaiting"] = "llm_cost_user"
            await _edit_or_send(
                update,
                context,
                "Send a user_id or @username, or type all:",
                reply_markup=admin_awaiting_inline_keyboard(),
            )
        elif field == "kind":
            await _edit_or_send(
                update,
                context,
                "Select a request kind:",
                reply_markup=llm_cost_kind_keyboard(),
            )
        elif field == "model":
            context.user_data["awaiting"] = "llm_cost_model"
            await _edit_or_send(
                update,
                context,
                "نام مدل را بفرست، یا بنویس all:",
                reply_markup=admin_awaiting_inline_keyboard(),
            )
        elif field == "status":
            await _edit_or_send(
                update,
                context,
                "Select a status:",
                reply_markup=llm_cost_status_keyboard(),
            )
        else:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
    elif action == "plan" and len(parts) == 3:
        _llm_cost_set_state(context, plan=None if parts[2] == "all" else parts[2], detail=False)
        await _show_llm_cost_dashboard(update, context)
    elif action == "kind" and len(parts) == 3:
        _llm_cost_set_state(context, request_kind=None if parts[2] == "all" else parts[2], detail=False)
        await _show_llm_cost_dashboard(update, context)
    elif action == "status" and len(parts) == 3:
        _llm_cost_set_state(context, outcome=None if parts[2] == "all" else parts[2], detail=False)
        await _show_llm_cost_dashboard(update, context)
    elif action == "clear":
        context.user_data["llm_cost_state"] = _llm_cost_default_state()
        await _show_llm_cost_dashboard(update, context)
    elif action == "refresh":
        await _show_llm_cost_dashboard(update, context)
    elif action == "recent":
        _llm_cost_set_state(context, detail=not bool(_llm_cost_state(context).get("detail")))
        await _show_llm_cost_dashboard(update, context)
    else:
        await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)


async def _handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str, text: str):
    if awaiting == "llm_cost_user":
        if text.casefold() in {"all", "همه", "none", "null"}:
            _llm_cost_set_state(context, user_id=None)
        else:
            target = db.find_user(text)
            if not target:
                context.user_data["awaiting"] = "llm_cost_user"
                await update.message.reply_text(
                    "User not found. Send a valid user_id or @username, or type all.",
                    reply_markup=admin_awaiting_inline_keyboard(),
                )
                return
            _llm_cost_set_state(context, user_id=target["user_id"])
        await _show_llm_cost_dashboard(update, context)
        return

    if awaiting == "llm_cost_model":
        if text.casefold() in {"all", "همه", "none", "null"}:
            _llm_cost_set_state(context, model=None)
        else:
            _llm_cost_set_state(context, model=text.strip())
        await _show_llm_cost_dashboard(update, context)
        return

    if awaiting in {"llm_price_input", "llm_price_output", "llm_price_rate"}:
        try:
            value = float(text.replace(",", "").strip())
            if value < 0:
                raise ValueError
        except ValueError:
            context.user_data["awaiting"] = awaiting
            await update.message.reply_text(
                "عدد معتبر بفرست، مثلاً 0.12 یا 65000.",
                reply_markup=admin_awaiting_inline_keyboard(),
            )
            return
        profile = db.get_llm_cost_profile()
        if awaiting == "llm_price_input":
            db.set_llm_cost_profile(
                input_cost_usd_per_million=value,
                output_cost_usd_per_million=profile["output_cost_usd_per_million"],
                usd_to_toman_rate=profile["usd_to_toman_rate"],
            )
        elif awaiting == "llm_price_output":
            db.set_llm_cost_profile(
                input_cost_usd_per_million=profile["input_cost_usd_per_million"],
                output_cost_usd_per_million=value,
                usd_to_toman_rate=profile["usd_to_toman_rate"],
            )
        else:
            db.set_llm_cost_profile(
                input_cost_usd_per_million=profile["input_cost_usd_per_million"],
                output_cost_usd_per_million=profile["output_cost_usd_per_million"],
                usd_to_toman_rate=value,
            )
        await update.message.reply_text(_llm_pricing_text())
        return

    if awaiting == "admin_set_plan":
        parts = text.split()
        if len(parts) != 2 or parts[1].lower() not in PLANS:
            context.user_data["awaiting"] = "admin_set_plan"
            await update.message.reply_text(
                "فرمت نامعتبر است. نمونه: `123456789 silver` یا `@username gold`",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return
        target = db.find_user(parts[0])
        if not target:
            context.user_data["awaiting"] = "admin_set_plan"
            await update.message.reply_text("کاربر پیدا نشد؛ ابتدا باید کاربر /start را زده باشد.")
            return
        plan = parts[1].lower()
        previous_plan = target["plan"] or "free"
        db.set_plan(target["user_id"], plan)
        await update.message.reply_text(
            f"پلن کاربر {target['user_id']} از {PLANS.get(previous_plan, previous_plan)} "
            f"به {PLANS[plan]} تغییر کرد."
        )
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

    if awaiting.startswith("admin_group_batch_key:"):
        key_hash = awaiting.split(":", 1)[1]
        groups = _detect_key_groups()
        target = next((g for g in groups if g["key_hash"] == key_hash), None)
        if target:
            db.set_preset_api_key_batch(target["names"], text.strip())
        context.user_data.pop("awaiting", None)
        await update.message.reply_text("✅ کلید API برای همه اعضای گروه به‌روز شد.")
        await _show_grouped_presets(update, context)
        return

    if awaiting.startswith("admin_group_set_label:"):
        key_hash = awaiting.split(":", 1)[1]
        groups = _detect_key_groups()
        target = next((g for g in groups if g["key_hash"] == key_hash), None)
        if target:
            db.set_preset_group_label_batch(target["names"], text.strip())
        context.user_data.pop("awaiting", None)
        await update.message.reply_text("✅ برچسب گروه برای همه اعضا تنظیم شد.")
        await _show_grouped_presets(update, context)
        return

    if awaiting.startswith("admin_group_manager_rename:"):
        old_label = unquote(awaiting.split(":", 1)[1])
        new_label = text.strip()
        if new_label:
            db.rename_group_label(old_label, new_label)
            context.user_data.pop("awaiting", None)
            await update.message.reply_text(f"✅ برچسب «{old_label}» به «{new_label}» تغییر نام یافت.")
        else:
            context.user_data.pop("awaiting", None)
            await update.message.reply_text("انصراف از تغییر نام.")
        await _show_group_manager(update, context)
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

    if awaiting.startswith("ai_fallback_rank:"):
        preset_name = awaiting.split(":", 1)[1]
        try:
            target_rank = int(text.strip())
        except ValueError:
            context.user_data["awaiting"] = awaiting
            await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید.")
            return
        preset = db.get_preset(preset_name)
        if not preset:
            await update.message.reply_text("پیش‌تنظیم یافت نشد")
            return
        group_is_emergency = bool(preset.get("is_emergency", 0))
        chain = db.get_fallback_chain_presets()
        count = len(chain)
        try:
            db.reindex_preset_priority(preset_name, target_rank, group_is_emergency)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"✅ رتبه {preset_name} به {target_rank} تغییر یافت.")
        await _show_fallback_chain(update, context)
        return

    if awaiting.startswith("ai_preset_full_edit:"):
        # format: ai_preset_full_edit:preset_name:field_idx
        parts = awaiting.split(":", 2)
        if len(parts) == 3:
            sub_parts = parts[2].rsplit(":", 1)
            if len(sub_parts) == 2:
                preset_name, field_idx = sub_parts
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

async def _show_ai_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main AI settings panel."""
    active_preset = db.get_active_preset()
    fallback_status = db.get_fallback_status()

    text = (
        "🤖 <b>تنظیمات هوش مصنوعی</b>\n\n"
        f"<b>پیش‌تنظیم فعال:</b> {active_preset.get('name', 'gapgpt')}\n"
        f"<b>مدل:</b> {active_preset.get('model', '—')}\n"
        f"<b>Base URL:</b> {active_preset.get('base_url', '—')}\n"
        f"<b>Batch Size:</b> {active_preset.get('daily_batch_size', 6)}\n"
        f"<b>Concurrency:</b> {active_preset.get('max_concurrency', 2)}\n"
        f"<b>RPM Limit:</b> {active_preset.get('max_rpm', 30)}\n\n"
    )

    if fallback_status.get("fallback_active"):
        text += (
            f"⚠️ <b>Fallback ACTIVE</b> since {fallback_status.get('fallback_since', '?')}\n"
            f"Primary: {fallback_status.get('primary_preset')} → "
            f"Fallback: {fallback_status.get('fallback_preset')}\n\n"
        )

    # Last successful preset per request kind (Rule #2)
    try:
        with db.get_conn() as conn:
            last_rows = conn.execute(
                "SELECT preset_name, request_kind FROM llm_requests "
                "WHERE request_kind IN ('daily_batch', 'grammar_tip', 'custom_word') "
                "AND outcome = 'success' "
                "AND created_at >= datetime('now', '-7 days') "
                "GROUP BY request_kind HAVING created_at = MAX(created_at)"
            ).fetchall()
        tracking = {row["request_kind"]: row["preset_name"] or "—" for row in last_rows}
        text += "📇 <b>آخرین درخواست‌ها:</b>\n"
        text += f"  Daily: {tracking.get('daily_batch', '—')}\n"
        text += f"  Grammar: {tracking.get('grammar_tip', '—')}\n"
        text += f"  Word: {tracking.get('custom_word', '—')}\n"
    except Exception:
        pass

    keyboard = ai_settings_keyboard()
    if update.callback_query:
        await _edit_or_send(update, context, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _show_ai_presets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all presets with pagination and view-mode toggle."""
    view_mode = context.user_data.get("preset_view_mode", "linear")
    if view_mode == "grouped":
        await _show_grouped_presets(update, context)
    else:
        await _show_linear_presets(update, context)


def _key_hash(api_key: str) -> str:
    """Short hash of an API key for callback_data."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


def _detect_key_groups() -> list[dict]:
    """Group all presets by resolved API key. Returns list sorted by count desc."""
    from services.ai.ai_presets import resolve_api_key
    presets = db.get_presets()
    groups_map: dict[str, dict] = {}
    for p in presets:
        resolved = resolve_api_key(p)
        if not resolved:
            resolved = "__no_key__"
        if resolved not in groups_map:
            masked = (resolved[:6] + "…" + resolved[-4:]) if len(resolved) > 12 else resolved
            groups_map[resolved] = {
                "resolved_key": resolved,
                "masked_key": masked,
                "key_hash": _key_hash(resolved),
                "label": p.get("group_label", "") or "",
                "count": 0,
                "names": [],
            }
        groups_map[resolved]["count"] += 1
        groups_map[resolved]["names"].append(p["name"])
        if p.get("group_label") and not groups_map[resolved]["label"]:
            groups_map[resolved]["label"] = p["group_label"]

    groups = sorted(groups_map.values(), key=lambda g: -g["count"])
    return groups


async def _show_linear_presets(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Show paginated linear preset list."""
    all_presets = db.get_presets()
    active_name = db.get_active_preset_name()
    per_page = 5
    total_pages = max(1, (len(all_presets) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    page_presets = all_presets[start:end]

    lines = ["📋 <b>لیست پیش‌تنظیم‌ها</b>\n"]
    for p in page_presets:
        marker = " ✅" if p["name"] == active_name else ""
        custom = " (custom)" if p.get("is_custom") else ""
        lines.append(
            f"{marker} <b>{p['name']}</b>{custom}\n"
            f"   Model: {p.get('model', '—')}\n"
            f"   URL: {p.get('base_url', '—')}\n"
            f"   Batch: {p.get('daily_batch_size', 6)} | Concurrency: {p.get('max_concurrency', 2)} | RPM: {p.get('max_rpm', 30)}"
        )

    if total_pages > 1:
        lines.append(f"\n📄 صفحه {page + 1} از {total_pages}")

    text = "\n\n".join(lines)

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_presets_list_keyboard(
            all_presets, active_name,
            page=page, total_pages=total_pages,
            view_mode="linear",
        )
    )


async def _show_grouped_presets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show presets grouped by API key."""
    groups = _detect_key_groups()
    active_name = db.get_active_preset_name()

    lines = ["📁 <b>پیش‌تنظیم‌ها بر اساس کلید API</b>\n"]
    for g in groups:
        label = g.get("label") or g.get("masked_key", "—")
        lines.append(
            f"📁 <b>{label}</b> ({g['count']} preset)\n"
            f"   🔑 {g['masked_key']}"
        )

    text = "\n\n".join(lines) if groups else "هیچ گروهی یافت نشد."

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_presets_list_keyboard(
            [], active_name,
            view_mode="grouped",
            groups=groups,
        )
    )


async def _show_ai_preset_view(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """View/edit a single preset."""
    preset = db.get_preset(preset_name)
    if not preset:
        await update.callback_query.answer("پیش‌تنظیم یافت نشد", show_alert=True)
        return

    active_name = db.get_active_preset_name()
    is_active = preset_name == active_name
    is_custom = preset.get("is_custom", 0)

    raw_key = preset.get("api_key", "")
    masked_key = (raw_key[:6] + "…" + raw_key[-4:]) if len(raw_key) > 12 else ("—" if not raw_key else "***")

    from services.db import get_preset_cost as _get_preset_cost
    cost = _get_preset_cost(preset_name)
    input_cost_str = f"{cost['input_cost_per_million']}" if cost['input_cost_per_million'] is not None else "— (global)"
    output_cost_str = f"{cost['output_cost_per_million']}" if cost['output_cost_per_million'] is not None else "— (global)"

    text = (
        f"📋 <b>پیش‌تنظیم: {preset_name}</b>\n\n"
        f"Model: {preset.get('model', '—')}\n"
        f"Base URL: {preset.get('base_url', '—')}\n"
        f"API Key: {masked_key}\n"
        f"Daily Batch Size: {preset.get('daily_batch_size', 6)}\n"
        f"Max Concurrency: {preset.get('max_concurrency', 2)}\n"
        f"Max RPM: {preset.get('max_rpm', 30)}\n"
        f"Timeout: {preset.get('timeout_seconds', 30)}s\n"
        f"Temperature: {preset.get('temperature', 0.6)}\n"
        f"Max Output Tokens: {preset.get('max_output_tokens', 4096)}\n"
        f"Input Cost: {input_cost_str} $/1M\n"
        f"Output Cost: {output_cost_str} $/1M\n"
    )

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_preset_view_keyboard(preset, active_name)
    )


async def _activate_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Activate a preset as primary."""
    success = db.activate_preset(preset_name)
    if success:
        await update.callback_query.answer(f"پیش‌تنظیم {preset_name} فعال شد")
    else:
        await update.callback_query.answer("خطا در فعال‌سازی", show_alert=True)
    await _show_ai_preset_view(update, context, preset_name)


async def _edit_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Show field edit options for a preset."""
    preset = db.get_preset(preset_name)
    if not preset or not preset.get("is_custom"):
        await update.callback_query.answer("فقط پیش‌تنظیم‌های custom قابل ویرایش‌اند", show_alert=True)
        return

    text = f"✏️ <b>ویرایش پیش‌تنظیم: {preset_name}</b>\nانتخاب فیلد برای تغییر:"

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_preset_edit_keyboard(preset_name, preset)
    )


async def _edit_ai_preset_field(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_name: str):
    """Prompt for new value of a field."""
    preset = db.get_preset(preset_name)
    if not preset:
        await update.callback_query.answer("پیش‌تنظیم یافت نشد", show_alert=True)
        return

    current = preset.get(field_name, "")
    if current is None:
        current = ""
    context.user_data["awaiting"] = f"ai_preset_edit:{preset_name}:{field_name}"

    field_labels = {
        "base_url": "Base URL",
        "model": "Model Name",
        "api_key": "API Key (env: $VAR_NAME or literal)",
        "daily_batch_size": "Batch Size (integer)",
        "max_concurrency": "Concurrency (integer)",
        "max_rpm": "RPM Limit (integer)",
        "max_tpm": "Max TPM (integer, 0 = unlimited)",
        "max_daily_req": "Max Daily Requests (integer, 0 = unlimited)",
        "timeout_seconds": "Timeout in seconds (float)",
        "temperature": "Temperature (0.0-2.0)",
        "max_output_tokens": "Max Output Tokens (integer)",
        "is_emergency": "Is Emergency (0 or 1)",
        "name": "Preset Name (a-z, 0-9, _)",
        "input_cost_per_million": "Input Cost $/1M tokens (empty = global)",
        "output_cost_per_million": "Output Cost $/1M tokens (empty = global)",
        "in_fallback_chain": "In Fallback Chain (0 or 1)",
        "group_label": "Group Label (any text)",
    }

    help_text = _FIELD_HELP.get(field_name, "")
    message = (
        f"✏️ <b>{field_labels.get(field_name, field_name)}</b>\n"
        f"مقدار فعلی: <code>{current}</code>\n\n"
        f"مقدار جدید را ارسال کنید:"
    )
    if help_text:
        message += f"\n\n💡 {help_text}"

    await _edit_or_send(
        update, context, message,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_awaiting_inline_keyboard()
    )


async def _handle_ai_preset_field_input(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_name: str, text: str):
    """Process field input for preset edit."""
    preset = db.get_preset(preset_name)
    if not preset:
        await update.message.reply_text("پیش‌تنظیم یافت نشد")
        return

    raw = text.strip()

    # Parse and validate based on field type
    try:
        if field_name in ("daily_batch_size", "max_concurrency", "max_rpm", "max_tpm", "max_daily_req", "max_output_tokens"):
            value = int(raw)
            if value < 0:
                raise ValueError
        elif field_name in ("timeout_seconds", "temperature"):
            value = float(raw)
        elif field_name == "is_emergency":
            value = int(raw)
            if value not in (0, 1):
                raise ValueError
        elif field_name == "name":
            value = raw.lower().replace(" ", "_")
            if not value or not all(c.isalnum() or c == "_" for c in value):
                raise ValueError
            # Check uniqueness (skip if same as current)
            if value != preset_name and db.get_preset(value):
                context.user_data["awaiting"] = f"ai_preset_edit:{preset_name}:{field_name}"
                await update.message.reply_text("این نام از قبل وجود دارد. نام دیگری انتخاب کنید.", reply_markup=awaiting_inline_keyboard())
                return
        elif field_name in ("input_cost_per_million", "output_cost_per_million"):
            if raw == "":
                value = None
            else:
                value = float(raw)
                if value < 0:
                    raise ValueError
        elif field_name == "in_fallback_chain":
            value = int(raw)
            if value not in (0, 1):
                raise ValueError
        elif field_name == "group_label":
            value = raw
        else:
            value = raw
    except ValueError:
        context.user_data["awaiting"] = f"ai_preset_edit:{preset_name}:{field_name}"
        await update.message.reply_text("فرمت نامعتبر. لطفاً مقدار معتبر بفرستید.", reply_markup=awaiting_inline_keyboard())
        return

    # Store in-memory (per preset)
    edits = context.user_data.setdefault("preset_edits", {})
    edits.setdefault(preset_name, {})[field_name] = value

    # Auto-delete user message containing plaintext API key
    if field_name == "api_key":
        try:
            await update.message.delete()
        except Exception:
            pass

    context.user_data.pop("awaiting", None)

    await update.message.reply_text(
        f"✅ <b>{field_name}</b> برای پیش‌تنظیم <b>{preset_name}</b> ثبت شد.",
        parse_mode=ParseMode.HTML
    )
    await _edit_ai_preset(update, context, preset_name)


WIZARD_FIELDS = [
    "name", "api_key", "base_url", "model",
    "max_concurrency", "max_rpm", "max_tpm", "daily_batch_size",
    "max_daily_req", "timeout_seconds", "temperature", "max_output_tokens",
    "priority", "is_emergency", "in_fallback_chain",
    "input_cost_per_million", "output_cost_per_million", "group_label",
]

WIZARD_GROUP_HEADERS = {
    0: "🆔 — گروه هویت (Identity):",
    4: "🔒 — گروه محدودیت‌ها (Limits):",
    12: "⛓️ — گروه فال‌بک (Fallback):",
    15: "💰 — گروه هزینه و برچسب (Cost & Label):",
}

WIZARD_FIELD_LABELS = {
    "name": "نام پریست",
    "api_key": "API Key",
    "base_url": "Base URL",
    "model": "Model",
    "max_concurrency": "Concurrency",
    "max_rpm": "RPM Limit",
    "max_tpm": "حد توکن در دقیقه (TPM)",
    "daily_batch_size": "Batch Size",
    "max_daily_req": "سقف درخواست روزانه",
    "timeout_seconds": "Timeout (s)",
    "temperature": "Temperature",
    "max_output_tokens": "Max Output Tokens",
    "priority": "اولویت (Priority)",
    "is_emergency": "پریست اضطراری",
    "in_fallback_chain": "حضور در زنجیره فال‌بک",
    "input_cost_per_million": "هزینه ورودی ($/1M)",
    "output_cost_per_million": "هزینه خروجی ($/1M)",
    "group_label": "برچسب گروه",
}

TOTAL_WIZARD_FIELDS = len(WIZARD_FIELDS)


async def _start_full_edit_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Start the full preset edit wizard."""
    preset = db.get_preset(preset_name)
    if not preset or not preset.get("is_custom"):
        await update.callback_query.answer("فقط پیش‌تنظیم‌های custom قابل ویرایش‌اند", show_alert=True)
        return

    context.user_data["full_edit"] = {"preset": preset_name, "field_idx": 0, "values": {}}
    context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:0"
    await _show_wizard_field(update, context, preset_name, 0, preset)


async def _show_wizard_field(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_idx: int, preset: dict):
    """Display a wizard field with prompt and navigation."""
    field_name = WIZARD_FIELDS[field_idx]
    current = preset.get(field_name, "")
    if current is None:
        current = ""

    group_header = WIZARD_GROUP_HEADERS.get(field_idx, "")
    label = WIZARD_FIELD_LABELS.get(field_name, field_name)
    help_text = _FIELD_HELP.get(field_name, "")

    message = f"✏️ <b>ویرایش کامل — گام {field_idx + 1} از {TOTAL_WIZARD_FIELDS}</b>\n"
    if group_header:
        message += f"\n{group_header}\n"
    message += f"\n<b>{label}</b>"
    if current:
        message += f"\nمقدار فعلی: <code>{current}</code>"
    if help_text:
        message += f"\n\n💡 {help_text}"
    message += "\n\nمقدار جدید را ارسال کنید (یا خالی = رد کردن):"

    buttons = []
    if field_idx < TOTAL_WIZARD_FIELDS - 1:
        buttons.append(InlineKeyboardButton(IBTN_FULL_EDIT_NEXT, callback_data=f"admin:ai_preset:full_edit_next:{preset_name}"))
    buttons.append(InlineKeyboardButton(IBTN_FULL_EDIT_SKIP, callback_data=f"admin:ai_preset:full_edit_skip:{preset_name}"))
    buttons.append(InlineKeyboardButton(IBTN_FULL_EDIT_CANCEL_WIZARD, callback_data=f"admin:ai_preset:full_edit_cancel:{preset_name}"))

    # Add group label picker buttons when editing group_label
    if field_name == "group_label":
        existing_groups = db.get_group_labels()
        if existing_groups:
            # Add group picker buttons in rows of 2
            group_rows = []
            for g in existing_groups:
                g_label = g["label"]
                g_count = g["count"]
                encoded = quote(g_label)
                group_rows.append(InlineKeyboardButton(
                    f"🏷️ {g_label} ({g_count})",
                    callback_data=f"admin:ai_preset:full_edit_pick_group:{preset_name}:{encoded}"
                ))
            # Split into rows of 2
            keyboard_rows = [[group_rows[i], group_rows[i + 1]] if i + 1 < len(group_rows) else [group_rows[i]]
                             for i in range(0, len(group_rows), 2)]
            keyboard_rows.append(buttons)
            keyboard = InlineKeyboardMarkup(keyboard_rows)
        else:
            keyboard = InlineKeyboardMarkup([buttons])
    else:
        keyboard = InlineKeyboardMarkup([buttons])

    context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{field_idx}"

    await _edit_or_send(update, context, message, parse_mode=ParseMode.HTML, reply_markup=keyboard)


def _validate_wizard_value(field_name: str, raw: str, preset_name: str) -> tuple | None:
    """Validate a wizard field value. Returns (value,) or None on invalid."""
    try:
        if field_name in ("daily_batch_size", "max_concurrency", "max_rpm", "max_tpm", "max_daily_req", "max_output_tokens"):
            v = int(raw)
            if v < 0:
                return None
            return (v,)
        elif field_name in ("timeout_seconds", "temperature"):
            return (float(raw),)
        elif field_name == "is_emergency":
            v = int(raw)
            if v not in (0, 1):
                return None
            return (v,)
        elif field_name == "name":
            v = raw.lower().replace(" ", "_")
            if not v or not all(c.isalnum() or c == "_" for c in v):
                return None
            if v != preset_name and db.get_preset(v):
                return None
            return (v,)
        elif field_name in ("input_cost_per_million", "output_cost_per_million"):
            if raw == "":
                return (None,)
            v = float(raw)
            if v < 0:
                return None
            return (v,)
        elif field_name == "in_fallback_chain":
            v = int(raw)
            if v not in (0, 1):
                return None
            return (v,)
        elif field_name == "priority":
            v = int(raw)
            if v < 0:
                return None
            return (v,)
        elif field_name == "group_label":
            return (raw,)
        else:
            return (raw,)
    except (ValueError, TypeError):
        return None


async def _handle_full_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_idx: int, text: str):
    """Handle text input during full edit wizard."""
    preset = db.get_preset(preset_name)
    if not preset:
        await update.message.reply_text("پیش‌تنظیم یافت نشد")
        return

    field_name = WIZARD_FIELDS[field_idx]
    raw = text.strip()

    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await update.message.reply_text("ویزارد منقضی شده. دوباره شروع کنید.")
        return

    if raw:
        result = _validate_wizard_value(field_name, raw, preset_name)
        if result is None:
            context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{field_idx}"
            await update.message.reply_text("فرمت نامعتبر. لطفاً مقدار معتبر بفرستید.", reply_markup=awaiting_inline_keyboard())
            return
        wizard["values"][field_name] = result[0]

    next_idx = field_idx + 1
    wizard["field_idx"] = next_idx

    if next_idx >= TOTAL_WIZARD_FIELDS:
        await _show_wizard_summary(update, context, preset_name)
    else:
        context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{next_idx}"
        await _show_wizard_field(update, context, preset_name, next_idx, preset)


async def _handle_full_edit_next(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Advance to next field without saving current."""
    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await update.callback_query.answer("ویزارد منقضی شده")
        return

    current_idx = wizard.get("field_idx", 0)
    next_idx = current_idx + 1
    wizard["field_idx"] = next_idx

    preset = db.get_preset(preset_name)
    if next_idx >= TOTAL_WIZARD_FIELDS:
        await _show_wizard_summary(update, context, preset_name)
    else:
        context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{next_idx}"
        await _show_wizard_field(update, context, preset_name, next_idx, preset or {})


async def _handle_full_edit_pick_group(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, label: str):
    """Handle group label picker selection in wizard."""
    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await update.callback_query.answer("ویزارد منقضی شده")
        return

    wizard["values"]["group_label"] = label
    current_idx = wizard.get("field_idx", 0)
    next_idx = current_idx + 1
    wizard["field_idx"] = next_idx

    preset = db.get_preset(preset_name)
    if next_idx >= TOTAL_WIZARD_FIELDS:
        await _show_wizard_summary(update, context, preset_name)
    else:
        context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{next_idx}"
        await update.callback_query.answer(f"✅ {label}")
        await _show_wizard_field(update, context, preset_name, next_idx, preset or {})


async def _handle_full_edit_skip(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Skip current field and advance."""
    await _handle_full_edit_next(update, context, preset_name)


async def _handle_full_edit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Cancel the full edit wizard."""
    context.user_data.pop("full_edit", None)
    context.user_data.pop("awaiting", None)
    await update.callback_query.answer("ویرایش کامل لغو شد")
    await _edit_ai_preset(update, context, preset_name)


async def _show_wizard_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Show summary of wizard changes and ask for confirmation."""
    wizard = context.user_data.get("full_edit", {})
    values = wizard.get("values", {})
    preset = db.get_preset(preset_name) or {}

    lines = [f"📋 <b>خلاصه تغییرات برای {preset_name}</b>\n"]
    changed = 0
    for field_name in WIZARD_FIELDS:
        if field_name in values:
            new_val = values[field_name]
            old_val = preset.get(field_name, "—")
            label = WIZARD_FIELD_LABELS.get(field_name, field_name)
            lines.append(f"• <b>{label}</b>: {old_val} → {new_val}")
            changed += 1

    if not changed:
        lines.append("هیچ تغییری اعمال نشد.")

    lines.append(f"\nتعداد تغییرات: {changed}")
    text = "\n".join(lines)

    buttons = [
        InlineKeyboardButton(IBTN_FULL_EDIT_SAVE_ALL, callback_data=f"admin:ai_preset:full_edit_save:{preset_name}"),
        InlineKeyboardButton(IBTN_FULL_EDIT_CANCEL_WIZARD, callback_data=f"admin:ai_preset:full_edit_cancel:{preset_name}"),
    ]
    keyboard = InlineKeyboardMarkup([buttons])

    context.user_data.pop("awaiting", None)

    await _edit_or_send(update, context, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _handle_full_edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Save all wizard changes."""
    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await update.callback_query.answer("ویزارد منقضی شده")
        return

    values = wizard.get("values", {})
    preset = db.get_preset(preset_name)
    if not preset:
        await update.callback_query.answer("پیش‌تنظیم یافت نشد", show_alert=True)
        return

    new_name = values.get("name", preset_name)
    rename = new_name != preset_name

    db.set_preset(
        name=new_name,
        base_url=values.get("base_url", preset.get("base_url", "")),
        model=values.get("model", preset.get("model", "")),
        api_key=values.get("api_key", preset.get("api_key", "")),
        daily_batch_size=int(values.get("daily_batch_size", preset.get("daily_batch_size", 6))),
        max_concurrency=int(values.get("max_concurrency", preset.get("max_concurrency", 2))),
        max_rpm=int(values.get("max_rpm", preset.get("max_rpm", 30))),
        max_tpm=int(values.get("max_tpm", preset.get("max_tpm", 0))),
        max_daily_req=int(values.get("max_daily_req", preset.get("max_daily_req", 0))),
        timeout_seconds=float(values.get("timeout_seconds", preset.get("timeout_seconds", 30.0))),
        temperature=float(values.get("temperature", preset.get("temperature", 0.6))),
        max_output_tokens=int(values.get("max_output_tokens", preset.get("max_output_tokens", 4096))),
        is_custom=1,
        is_emergency=int(values.get("is_emergency", preset.get("is_emergency", 0))),
        input_cost_per_million=values.get("input_cost_per_million", preset.get("input_cost_per_million")),
        output_cost_per_million=values.get("output_cost_per_million", preset.get("output_cost_per_million")),
        in_fallback_chain=int(values.get("in_fallback_chain", preset.get("in_fallback_chain", 1))),
        group_label=values.get("group_label", preset.get("group_label", "")),
    )

    if rename:
        db.delete_preset(preset_name)

    context.user_data.pop("full_edit", None)
    context.user_data.pop("awaiting", None)

    await update.callback_query.answer(f"پیش‌تنظیم {new_name} ذخیره شد")
    await _show_ai_preset_view(update, context, new_name)


async def _toggle_preset_view_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle between linear and grouped preset view."""
    current = context.user_data.get("preset_view_mode", "linear")
    new_mode = "grouped" if current == "linear" else "linear"
    context.user_data["preset_view_mode"] = new_mode
    await update.callback_query.answer(f"حالت نمایش: {'گروهی' if new_mode == 'grouped' else 'خطی'}")
    await _show_ai_presets(update, context)


async def _handle_group_view(update: Update, context: ContextTypes.DEFAULT_TYPE, key_hash: str):
    """Show details for a specific group."""
    groups = _detect_key_groups()
    target = next((g for g in groups if g["key_hash"] == key_hash), None)
    if not target:
        await update.callback_query.answer("گروه یافت نشد", show_alert=True)
        return

    names = target["names"]
    presets = [db.get_preset(n) for n in names if db.get_preset(n)]
    active_name = db.get_active_preset_name()

    lines = [f"📁 <b>گروه: {target.get('label') or target['masked_key']}</b>\n"]
    lines.append(f"🔑 کلید: {target['masked_key']}")
    lines.append(f"تعداد: {target['count']} preset\n")
    for p in presets:
        marker = " ✅" if p["name"] == active_name else ""
        lines.append(f"{marker} <b>{p['name']}</b> — {p.get('model', '—')}")

    text = "\n".join(lines)

    buttons = [
        [
            InlineKeyboardButton(IBTN_GROUP_BATCH_KEY, callback_data=f"admin:ai_preset:group_batch_key:{key_hash}"),
            InlineKeyboardButton(IBTN_GROUP_SET_LABEL, callback_data=f"admin:ai_preset:group_set_label:{key_hash}"),
        ],
        [InlineKeyboardButton(BTN_BACK, callback_data="admin:ai_presets")],
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    await _edit_or_send(update, context, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _handle_group_batch_key(update: Update, context: ContextTypes.DEFAULT_TYPE, key_hash: str):
    """Start awaiting flow for batch API key update."""
    context.user_data["awaiting"] = f"admin_group_batch_key:{key_hash}"
    await _edit_or_send(
        update, context,
        "🔑 کلید API جدید را برای همه اعضای این گروه ارسال کنید:",
        reply_markup=admin_awaiting_inline_keyboard(),
    )


async def _handle_group_set_label(update: Update, context: ContextTypes.DEFAULT_TYPE, key_hash: str):
    """Start awaiting flow for group label update."""
    context.user_data["awaiting"] = f"admin_group_set_label:{key_hash}"
    await _edit_or_send(
        update, context,
        "🏷️ برچسب جدید گروه را ارسال کنید:",
        reply_markup=admin_awaiting_inline_keyboard(),
    )


async def _show_group_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show group manager — list all group_labels with preset counts."""
    groups = db.get_group_labels()
    lines = ["🏷️ <b>مدیریت گروه‌ها</b>\n\n"]
    if not groups:
        lines.append("هیچ گروهی تعریف نشده است.\nبرای گروه‌بندی، از فیلد group_label استفاده کنید.")
    else:
        for g in groups:
            lines.append(f"• <b>{g['label']}</b> — {g['count']} پریست")
    lines.append("")

    buttons = []
    for g in groups:
        encoded = quote(g["label"])
        buttons.append([
            InlineKeyboardButton(f"✏️ {g['label']}", callback_data=f"admin:ai_preset:group_manager_rename:{encoded}"),
            InlineKeyboardButton(f"🗑️ حذف برچسب", callback_data=f"admin:ai_preset:group_manager_clear:{encoded}"),
        ])
    buttons.append([InlineKeyboardButton(IBTN_BACK, callback_data="admin:ai_settings")])

    await _edit_or_send(update, context, "".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def _handle_group_manager_rename(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    """Start rename flow for a group label."""
    context.user_data["awaiting"] = f"admin_group_manager_rename:{quote(label)}"
    await _edit_or_send(
        update, context,
        f"✏️ نام جدید برای گروه <b>{label}</b> را ارسال کنید:\n"
        "(خالی = انصراف)",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_awaiting_inline_keyboard(),
    )


async def _handle_group_manager_clear(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    """Clear a group label from all presets."""
    db.clear_group_label(label)
    await update.callback_query.answer(f"✅ برچسب «{label}» از همه پریست‌ها حذف شد")
    await _show_group_manager(update, context)


async def _confirm_save_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Show confirmation dialog before saving."""
    edits = context.user_data.get("preset_edits", {}).get(preset_name, {})
    if not edits:
        await update.callback_query.answer("تغییری برای ذخیره وجود ندارد")
        return

    from config.keyboards import IBTN_SAVE_CONFIRM, IBTN_SAVE_CANCEL
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(IBTN_SAVE_CONFIRM, callback_data=f"admin:ai_preset:confirm_save_yes:{preset_name}"),
            InlineKeyboardButton(IBTN_SAVE_CANCEL, callback_data=f"admin:ai_preset:confirm_save_no:{preset_name}"),
        ]
    ])
    await _edit_or_send(
        update, context,
        f"⚠️ <b>آیا از ذخیره تغییرات برای «{preset_name}» مطمئنید؟</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _discard_all_preset_changes(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Discard all pending edits for a preset."""
    context.user_data.setdefault("preset_edits", {}).pop(preset_name, None)
    await update.callback_query.answer("همه تغییرات دور ریخته شد")
    await _show_ai_preset_view(update, context, preset_name)


async def _save_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Save all pending changes for a preset to the database."""
    preset = db.get_preset(preset_name)
    if not preset:
        await update.callback_query.answer("پیش‌تنظیم یافت نشد", show_alert=True)
        return

    # Read in-memory edits for this preset
    edits = context.user_data.get("preset_edits", {}).get(preset_name, {})
    if not edits:
        await update.callback_query.answer("تغییری برای ذخیره وجود ندارد")
        return

    # Handle rename: if name changed, use new name as key
    new_name = edits.get("name", preset_name)
    rename = new_name != preset_name

    # Apply to preset from in-memory edits + existing values as fallback
    db.set_preset(
        name=new_name,
        base_url=edits.get("base_url", preset.get("base_url", "")),
        model=edits.get("model", preset.get("model", "")),
        api_key=edits.get("api_key", preset.get("api_key", "")),
        daily_batch_size=int(edits.get("daily_batch_size", preset.get("daily_batch_size", 6))),
        max_concurrency=int(edits.get("max_concurrency", preset.get("max_concurrency", 2))),
        max_rpm=int(edits.get("max_rpm", preset.get("max_rpm", 30))),
        max_tpm=int(edits.get("max_tpm", preset.get("max_tpm", 0))),
        max_daily_req=int(edits.get("max_daily_req", preset.get("max_daily_req", 0))),
        timeout_seconds=float(edits.get("timeout_seconds", preset.get("timeout_seconds", 30.0))),
        temperature=float(edits.get("temperature", preset.get("temperature", 0.6))),
        max_output_tokens=int(edits.get("max_output_tokens", preset.get("max_output_tokens", 4096))),
        is_custom=1,
        is_emergency=int(edits.get("is_emergency", preset.get("is_emergency", 0))),
        input_cost_per_million=edits.get("input_cost_per_million", preset.get("input_cost_per_million")),
        output_cost_per_million=edits.get("output_cost_per_million", preset.get("output_cost_per_million")),
        in_fallback_chain=int(edits.get("in_fallback_chain", preset.get("in_fallback_chain", 1))),
        group_label=edits.get("group_label", preset.get("group_label", "")),
    )

    # If renamed, delete old preset row
    if rename:
        db.delete_preset(preset_name)
        # Move pending edits to new name key
        context.user_data.setdefault("preset_edits", {}).pop(preset_name, None)

    # Clear in-memory edits for this preset
    context.user_data.setdefault("preset_edits", {}).pop(new_name, None)

    await update.callback_query.answer(f"پیش‌تنظیم {new_name} ذخیره شد")
    await _show_ai_preset_view(update, context, new_name)


async def _delete_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Delete a preset (forbidden for the currently active one)."""
    preset = db.get_preset(preset_name)
    if not preset:
        await update.callback_query.answer("پیش‌تنظیم یافت نشد", show_alert=True)
        return

    active_name = db.get_active_preset_name()
    if preset_name == active_name:
        await update.callback_query.answer("نمی‌توان پیش‌تنظیم فعال را حذف کرد", show_alert=True)
        return

    db.delete_preset(preset_name)
    await update.callback_query.answer(f"پیش‌تنظیم {preset_name} حذف شد")
    await _show_ai_presets(update, context)


async def _add_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a new custom preset - start with name input."""
    context.user_data["awaiting"] = "admin_ai_preset_new_name"
    await _edit_or_send(
        update, context,
        "➕ <b>ایجاد پیش‌تنظیم جدید</b>\n\n"
        "نام پیش‌تنظیم را وارد کنید (مثال: my_openai):",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_awaiting_inline_keyboard()
    )


async def _handle_ai_preset_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle new preset name input."""
    name = text.strip().lower().replace(" ", "_")
    if not name or not name.isalnum() and "_" not in name:
        context.user_data["awaiting"] = "ai_preset_new_name"
        await update.message.reply_text("نام نامعتبر. فقط حروف، اعداد و زیرخط مجاز است.", reply_markup=awaiting_inline_keyboard())
        return

    existing = db.get_preset(name)
    if existing:
        context.user_data["awaiting"] = "ai_preset_new_name"
        await update.message.reply_text("این نام از قبل وجود دارد.", reply_markup=awaiting_inline_keyboard())
        return

    # Create empty custom preset
    db.set_preset(name=name, is_custom=1)
    context.user_data.pop("awaiting", None)
    await update.message.reply_text(f"پیش‌تنظیم <b>{name}</b> ایجاد شد. اکنون می‌توانید فیلدها را ویرایش کنید.", parse_mode=ParseMode.HTML)
    await _edit_ai_preset(update, context, name)


async def _test_ai_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test current AI connection."""
    await update.callback_query.answer("در حال تست اتصال...")
    active = db.get_active_preset()
    result = await asyncio.to_thread(
        ai.test_connection,
        base_url=active.get("base_url", ""),
        api_key=ai_presets.resolve_api_key(active),
        model=active.get("model", ""),
        timeout=active.get("timeout_seconds", 30.0),
    )

    if result["success"]:
        text = (
            f"✅ <b>اتصال موفق</b>\n"
            f"Latency: {result['latency_ms']} ms\n"
            f"Model: {result['model']}\n"
            f"Tokens: {result['usage']}"
        )
    else:
        text = (
            f"❌ <b>خطا در اتصال</b>\n"
            f"Error: {result['error_class']}: {result['error_message']}\n"
            f"Latency: {result['latency_ms']} ms"
        )

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 تست مجدد", callback_data="admin:ai_test_connection")],
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
        ])
    )


# ======== Custom Test Wizard ========

async def _start_custom_test_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the custom test wizard."""
    context.user_data["custom_test_state"] = {"step": "prompt"}
    context.user_data["awaiting"] = "ai_custom_test_prompt"

    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی کارت</b>\n\n"
        "مرحله ۱/۵: پرامپت سیستم (یا متن تست) را وارد کنید:\n"
        "<i>مثال: یک کارت واژگان برای سطح مبتدی بساز</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_awaiting_inline_keyboard()
    )


async def _custom_test_step_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("custom_test_state", {})
    state["step"] = "lang"
    context.user_data["custom_test_state"] = state
    context.user_data.pop("awaiting", None)

    buttons = [
        [InlineKeyboardButton(opt.name_fa, callback_data=f"admin:ai_custom_test:lang:{opt.code}")]
        for opt in LANGUAGES.values()
    ]
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - مرحله ۲/۵</b>\n\n"
        "زبان مقصد را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _custom_test_step_goal(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    state = context.user_data.get("custom_test_state", {})
    state["lang"] = lang
    state["step"] = "goal"
    context.user_data["custom_test_state"] = state

    buttons = [
        [InlineKeyboardButton(opt.name_fa, callback_data=f"admin:ai_custom_test:goal:{opt.code}")]
        for opt in GOALS.values()
    ]
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - مرحله ۳/۵</b>\n\n"
        "هدف یادگیری را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _custom_test_step_level(update: Update, context: ContextTypes.DEFAULT_TYPE, goal: str):
    state = context.user_data.get("custom_test_state", {})
    state["goal"] = goal
    state["step"] = "level"
    context.user_data["custom_test_state"] = state

    buttons = [
        [InlineKeyboardButton(f"{opt.name_fa} ({opt.cefr})", callback_data=f"admin:ai_custom_test:level:{opt.code}")]
        for opt in LEVELS.values()
    ]
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - مرحله ۴/۵</b>\n\n"
        "سطح زبان را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _custom_test_step_target(update: Update, context: ContextTypes.DEFAULT_TYPE, level: str):
    state = context.user_data.get("custom_test_state", {})
    state["level"] = level
    state["step"] = "target"
    context.user_data["custom_test_state"] = state

    active_preset = db.get_active_preset()
    buttons = [
        [InlineKeyboardButton("🔹 پیکربندی فعلی", callback_data="admin:ai_custom_test:target:current")],
        [InlineKeyboardButton("🔸 پیش‌تنظیم کاندیدا", callback_data="admin:ai_custom_test:target:candidate")],
        [InlineKeyboardButton("⚖️ مقایسه A/B", callback_data="admin:ai_custom_test:target:ab")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
    ]
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - مرحله ۵/۵</b>\n\n"
        "هدف تست را انتخاب کنید:\n"
        f"- فعلی: {active_preset.get('name', 'gapgpt')}\n"
        f"- کاندیدا: پیش‌تنظیم دیگری را انتخاب کنید",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _run_custom_test(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str):
    """Execute the custom test."""
    state = context.user_data.get("custom_test_state", {})
    prompt = state.get("prompt", "یک کارت واژگان بساز")
    lang = state.get("lang", "en")
    goal = state.get("goal", "general")
    level = state.get("level", "beginner")

    await update.callback_query.answer("در حال اجرای تست...")

    system_prompt = prompts.daily_batch_system_prompt(lang, goal, level, compact=False)

    results = []

    if target in ("current", "ab"):
        result = await asyncio.to_thread(
            ai.custom_test_card,
            system_prompt=system_prompt,
            user_prompt=prompt,
            lang=lang,
            goal=goal,
            level=level,
            preset=db.get_active_preset(),
        )
        results.append(("Current Config", result))

    if target in ("candidate", "ab"):
        candidate_name = state.get("candidate_preset", "gapgpt")
        candidate = db.get_preset(candidate_name) or db.get_preset("gapgpt") or {}
        result = await asyncio.to_thread(
            ai.custom_test_card,
            system_prompt=system_prompt,
            user_prompt=prompt,
            lang=lang,
            goal=goal,
            level=level,
            preset=candidate,
        )
        results.append((f"Candidate ({candidate_name})", result))

    # Format results
    lines = ["🧪 <b>نتیجه تست سفارشی</b>\n"]
    for label, card in results:
        lines.append(f"<b>{label}</b>")
        lines.append(f"Word: {card.get('word', '?')}")
        lines.append(f"Meaning: {card.get('fa_meaning', '?')}")
        lines.append(f"Examples: {card.get('examples', [])}")
        lines.append("")

    lines.append("🧪 این تست روی پیکربندی پیش‌تنظیم اجرا شد، نه مسیر تولید.")

    await _edit_or_send(
        update, context,
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 تست مجدد", callback_data="admin:ai_custom_test")],
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
        ])
    )
    context.user_data.pop("custom_test_state", None)


async def _handle_custom_test_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Route wizard callbacks."""
    if action == "ai_custom_test:lang":
        pass
    elif action.startswith("ai_custom_test:lang:"):
        await _custom_test_step_goal(update, context, action.split(":")[2])
    elif action.startswith("ai_custom_test:goal:"):
        await _custom_test_step_level(update, context, action.split(":")[2])
    elif action.startswith("ai_custom_test:level:"):
        await _custom_test_step_target(update, context, action.split(":")[2])
    elif action.startswith("ai_custom_test:target:"):
        target = action.split(":")[2]
        if target in ("candidate", "ab"):
            state = context.user_data.get("custom_test_state", {})
            state["target"] = target
            context.user_data["custom_test_state"] = state
            await _custom_test_step_preset(update, context)
        else:
            await _run_custom_test(update, context, target)
    elif action.startswith("ai_custom_test:preset:"):
        state = context.user_data.get("custom_test_state", {})
        state["candidate_preset"] = action.split(":")[2]
        context.user_data["custom_test_state"] = state
        await _run_custom_test(update, context, state.get("target", "candidate"))


async def _custom_test_step_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show preset picker for custom test."""
    presets = db.get_presets()
    buttons = [
        [InlineKeyboardButton(p["name"], callback_data=f"admin:ai_custom_test:preset:{p['name']}")]
        for p in presets
    ]
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_custom_test")])
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - انتخاب پیش‌تنظیم</b>\n\n"
        "پیش‌تنظیم کاندیدا را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def _show_ai_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show fallback configuration panel."""
    status = db.get_fallback_status()
    text = (
        "🔄 <b>مدیریت پیش‌تنظیم پشتیبان (Fallback)</b>\n\n"
        f"Status: {'🔴 Fallback ACTIVE' if status['fallback_active'] else '🟢 Primary Active'}\n"
        f"Primary: {status['primary_preset']}\n"
        f"Fallback: {status['fallback_preset']}\n"
        f"Consecutive Failures: {status['consecutive_failures']}\n"
    )
    if status["fallback_active"] and status["fallback_since"]:
        text += f"Fallback Since: {status['fallback_since'][:19]}\n"

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_fallback_keyboard(
            status["primary_preset"],
            status["fallback_preset"],
            status["fallback_preset"] if status["fallback_active"] else status["primary_preset"]
        )
    )


async def _handle_ai_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Handle fallback actions."""
    if action == "ai_fallback:set_primary":
        await _show_fallback_preset_picker(update, context, "primary")
    elif action == "ai_fallback:set_fallback":
        await _show_fallback_preset_picker(update, context, "fallback")
    elif action.startswith("ai_fallback:pick_primary:"):
        name = action.split(":")[2]
        db.set_setting("ai_primary_preset", name)
        await update.callback_query.answer(f"Primary preset: {name}")
        await _show_ai_fallback(update, context)
    elif action.startswith("ai_fallback:pick_fallback:"):
        name = action.split(":")[2]
        db.set_setting("ai_fallback_preset", name)
        await update.callback_query.answer(f"Fallback preset: {name}")
        await _show_ai_fallback(update, context)
    elif action == "ai_fallback:reset":
        db.set_fallback_active(False)
        db.set_setting("ai_consecutive_failures", "0")
        await update.callback_query.answer("بازگشت به Primary")
        await _show_ai_fallback(update, context)


async def _show_fallback_preset_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, which: str):
    """Show preset picker for primary/fallback."""
    presets = db.get_presets()
    buttons = [
        [InlineKeyboardButton(p["name"], callback_data=f"admin:ai_fallback:pick_{which}:{p['name']}")]
        for p in presets
    ]
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_fallback")])

    await _edit_or_send(
        update, context,
        f"پیش‌تنظیم {which.upper()} را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _show_help_presets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help overview for presets."""
    text = (
        "❓ <b>راهنمای پریست‌های AI</b>\n\n"
        "هر پریست یک تنظیمات کامل برای اتصال به یک سرویس‌دهنده AI است.\n\n"
        "<b>فیلدهای اصلی:</b>\n"
        "• name: نام یکتای پریست (فقط حروف انگلیسی، اعداد، زیرخط)\n"
        "• api_key: کلید API (مقدار ثابت یا متغیر محیطی $VAR)\n"
        "• base_url: آدرس سرور (سازگار با OpenAI)\n"
        "• model: نام دقیق مدل\n\n"
        "<b>محدودیت‌ها:</b>\n"
        "• max_concurrency: تعداد درخواست هم‌زمان\n"
        "• max_rpm: سقف درخواست در دقیقه (0 = بی‌محدودیت)\n"
        "• max_tpm: سقف توکن در دقیقه (0 = بی‌محدودیت)\n"
        "• max_daily_req: سقف درخواست روزانه (0 = بی‌محدودیت)\n\n"
        "<b>زنجیره فال‌بک:</b>\n"
        "پریست‌ها بر اساس priority (کم→زیاد) و is_emergency مرتب می‌شوند.\n"
        "پریست‌های عادی اول امتحان می‌شوند، سپس اضطراری.\n"
        "in_fallback_chain=0 یعنی پریست در زنجیره شرکت نمی‌کند.\n\n"
        "<b>گروه‌بندی:</b>\n"
        "پریست‌هایی که کلید API مشترک دارند در یک گروه قرار می‌گیرند.\n"
        "group_label برای نام‌گذاری گروه‌ها استفاده می‌شود."
    )
    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")]
        ])
    )


async def _show_help_fallback_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help for fallback chain."""
    text = (
        "❓ <b>راهنمای زنجیره فال‌بک</b>\n\n"
        "ترتیب زنجیره:\n"
        "۱. پریست‌های عادی (is_emergency=0) بر اساس priority (از کم به زیاد)\n"
        "۲. پریست‌های اضطراری (is_emergency=1) بر اساس priority\n\n"
        "پریست‌های با in_fallback_chain=0 در زنجیره نمایش داده نمی‌شوند.\n\n"
        "<b>دکمه‌ها:</b>\n"
        "• ⬆/⬇: جابه‌جایی دستی (تغییر priority)\n"
        "• 🟢/🔴: فعال/غیرفعال کردن پریست\n"
        "• 🚨: تبدیل به پریست اضطراری\n"
        "• 🎯: پرش به رتبه دلخواه در گروه\n\n"
        "پریست اضطراری همیشه بعد از همه پریست‌های عادی امتحان می‌شود."
    )
    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ بازگشت به زنجیره", callback_data="admin:fallback_chain")]
        ])
    )


async def _show_fallback_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show and manage the fallback chain order."""
    chain = db.get_fallback_chain_presets()
    text = (
        "⛓️ <b>زنجیره فال‌بک</b>\n\n"
        "ترتیب: پریست‌های عادی (is_emergency=0) بر اساس priority (از کم به زیاد)، "
        "سپس پریست‌های اضطراری (is_emergency=1).\n"
        "پریست‌های با in_fallback_chain=0 در این زنجیره نمایش داده نمی‌شوند.\n\n"
    )
    for i, preset in enumerate(chain):
        name = preset.get("name", "?")
        is_emergency = preset.get("is_emergency", 0)
        status = "🚨 اضطراری" if is_emergency else "✅ فعال"
        text += f"{i+1}. <b>{name}</b> — {status}\n"

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=fallback_chain_keyboard(chain)
    )


async def _show_fallback_usage_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show daily consumption for all presets."""
    presets = db.get_presets()
    lines = ["📊 <b>مصرف روزانه پریست‌ها</b>\n\n"]
    for p in presets:
        name = p["name"]
        req_count, token_count = db.get_hourly_usage(name, hours_back=24)
        max_daily = p.get("max_daily_req", 0)
        status = "🟢" if req_count < max_daily or max_daily == 0 else "🔴"
        daily_str = f"{req_count}/{max_daily}" if max_daily > 0 else f"{req_count}/∞"
        lines.append(f"{status} <b>{name}</b>: {daily_str} req, {token_count} توکن")

    text = "\n".join(lines) if len(lines) > 1 else "هیچ داده‌ای یافت نشد."

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ بازگشت به زنجیره", callback_data="admin:fallback_chain")]
        ])
    )


async def _handle_fallback_rank(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Start awaiting flow for rank jump input."""
    preset = db.get_preset(preset_name)
    if not preset:
        await update.callback_query.answer("پیش‌تنظیم یافت نشد", show_alert=True)
        return

    group_is_emergency = bool(preset.get("is_emergency", 0))
    group_label = "اضطراری" if group_is_emergency else "عادی"
    chain = db.get_fallback_chain_presets()
    group_chain = [p for p in chain if bool(p.get("is_emergency", 0)) == group_is_emergency]
    max_rank = len(group_chain)

    context.user_data["awaiting"] = f"ai_fallback_rank:{preset_name}"
    await _edit_or_send(
        update, context,
        f"🎯 رتبه جدید در گروه «{group_label}» را وارد کنید (۱ تا {max_rank}):",
        reply_markup=admin_awaiting_inline_keyboard(),
    )


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
