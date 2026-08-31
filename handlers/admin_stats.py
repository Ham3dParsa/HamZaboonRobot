"""Admin stats domain module (Finding #7, task 7.5).

Migrate step: ``handle_admin_stats`` owns the ``admin:stats`` handling that used
to be inline in the admin monolith's ``_handle_admin_callback``. The stats
keyboards are imported from ``config.keyboards``. Behavior is unchanged; the
admin monolith delegates to this module.
"""

import io
from datetime import timedelta

from services.db.schema import _today, _utc_now

from telegram import Update
from telegram.ext import ContextTypes

from services import db
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.formatting import to_persian_digits
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
                f"• کل کاربران: {to_persian_digits(data['total'])}\n"
                f"• ثبت‌نام کامل: {to_persian_digits(data['onboarded'])}\n"
                f"• بلاک کرده: {to_persian_digits(data['blocked'])}",
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
                    lines.append(f"  {val}: {to_persian_digits(r['cnt'])}")
                lines.append("")
            await _edit_or_send(
                update, context,
                "\n".join(lines).strip(),
                reply_markup=stats_back_keyboard(),
            )
        elif sub == "activity":
            today = _today()
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
                f"• فعال امروز: {to_persian_digits(active_today)}\n"
                f"• فعال این هفته: {to_persian_digits(active_week)}\n"
                f"• فعال این ماه: {to_persian_digits(active_month)}\n\n"
                f"• کل لغات ذخیره‌شده: {to_persian_digits(total_words)}\n"
                f"• درخواست‌های AI امروز: {to_persian_digits(today_llm)}",
                reply_markup=stats_back_keyboard(),
            )
        elif sub == "growth":
            # created_at is UTC (_utc_now), last_active_date is APP_TIMEZONE (_today)
            today_app = _today()
            today_utc = _utc_now().date()
            d7_app = (today_app - timedelta(days=7)).isoformat()
            d7_utc = (today_utc - timedelta(days=7)).isoformat()
            d30_utc = (today_utc - timedelta(days=30)).isoformat()
            new_7 = db.count_new_users_since(d7_utc)
            new_30 = db.count_new_users_since(d30_utc)
            created_before_7 = db.count_users_created_before(d7_utc)
            retained_7 = db.count_retained_users(d7_utc, d7_app)
            ret_pct = round(retained_7 / created_before_7 * 100) if created_before_7 else 0
            await _edit_or_send(
                update, context,
                f"📈 رشد و بازگشت\n\n"
                f"• کاربر جدید ۷ روز اخیر: {to_persian_digits(new_7)}\n"
                f"• کاربر جدید ۳۰ روز اخیر: {to_persian_digits(new_30)}\n"
                f"• نرخ بازگشت (ثبت‌نام‌کرده +۷ روز، فعال در ۷ روز اخیر): "
                f"{to_persian_digits(ret_pct)}٪",
                reply_markup=stats_back_keyboard(),
            )
        elif sub == "learning":
            reviews = db.count_review_events_total()
            sessions = db.count_study_sessions_total()
            total_sw = db.count_saved_words_total()
            total_users = db.count_users()
            avg = round(total_sw / total_users, 1) if total_users else 0
            fe = db.count_first_exposure_completion()
            fe_pct = round(fe["done"] / fe["total"] * 100) if fe["total"] else 0
            top = db.get_top_users_by_streak(20)
            # Filter zero-streak users — empty-state if no active streak
            top_active = [u for u in top if (u.get("streak") or 0) > 0]
            lines = [
                f"📚 درگیری یادگیری\n\n"
                f"• کل مرورهای SRS: {to_persian_digits(reviews)}\n"
                f"• کل جلسات مطالعه: {to_persian_digits(sessions)}\n"
                f"• میانگین لغت ذخیره‌شده به ازای هر کاربر: {to_persian_digits(avg)}\n"
                f"• تکمیل first-exposure: {to_persian_digits(fe_pct)}٪",
            ]
            if top_active:
                lines.append("\n🏆 برترین‌ها (استریک):")
                for idx, u in enumerate(top_active, 1):
                    full_name = (u.get("full_name") or "").strip().replace("\n", " ")[:50]
                    if full_name:
                        if u.get("username"):
                            name = f"{full_name} (@{u['username']})"
                        else:
                            name = full_name
                    else:
                        name = f"@{u['username']}" if u.get("username") else str(u["user_id"])
                    lines.append(f"{to_persian_digits(idx)}. {name} — {to_persian_digits(u['streak'] or 0)}")
            else:
                lines.append("\n(هنوز کاربری با استریک ثبت نشده)")
            await _edit_or_send(
                update, context,
                "\n".join(lines),
                reply_markup=stats_back_keyboard(),
            )
        elif sub == "export":
            await notify_callback(
                update.callback_query, "در حال آماده‌سازی فایل…", intent=CallbackNoticeIntent.INFO
            )
            csv_text = db.export_users_csv()
            data = csv_text.encode("utf-8-sig")
            await update.effective_message.reply_document(
                document=io.BytesIO(data),
                filename=f"hamzaban_users_{_today().isoformat()}.csv",
                caption="📤 خروجی کاربران (CSV)",
            )
        else:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
