"""Admin stats domain module (Finding #7, task 7.5).

Migrate step: ``handle_admin_stats`` owns the ``admin:stats`` handling that used
to be inline in the admin monolith's ``_handle_admin_callback``. The stats
keyboards are imported from ``config.keyboards``. Behavior is unchanged; the
admin monolith delegates to this module.
"""

from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from services import db
from services.utils.helpers import _edit_or_send
from config.keyboards import stats_back_keyboard, stats_menu_keyboard

__all__ = ["handle_admin_stats", "stats_back_keyboard", "stats_menu_keyboard"]


async def handle_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Handle the ``admin:stats`` menu and its sub-actions."""
    if action == "stats":
        await _edit_or_send(
            update, context,
            "📊 آمار کاربران\n\nیکی از بخش‌ها را انتخاب کن:",
            reply_markup=stats_menu_keyboard(),
        )
        return
    if action.startswith("stats:"):
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
