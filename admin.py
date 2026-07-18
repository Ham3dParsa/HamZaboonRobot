import calendar
import datetime
import logging
from collections import defaultdict
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import APP_TIMEZONE, OWNER_ID, PLANS, is_owner
import db
from helpers import _edit_or_send, _send_with_retry
from keyboards import (
    admin_panel_keyboard,
    awaiting_inline_keyboard,
    llm_cost_dashboard_keyboard,
    llm_cost_kind_keyboard,
    llm_cost_plan_keyboard,
    llm_cost_pricing_keyboard,
    llm_cost_status_keyboard,
    phonetic_settings_keyboard,
)

logger = logging.getLogger(__name__)
_app_timezone = ZoneInfo(APP_TIMEZONE)


async def open_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text("پنل مدیریت ربات:", reply_markup=admin_panel_keyboard())


def _phonetic_settings_text() -> str:
    settings = db.get_phonetic_display_settings()
    return (
        "تنظیم نمایش تلفظ‌ها:\n"
        f"IPA: {'روشن' if settings['ipa'] else 'خاموش'}\n"
        f"Persian: {'روشن' if settings['persian'] else 'خاموش'}"
    )


async def _handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    if not is_owner(update.effective_user.id):
        await update.callback_query.answer("فقط مالک ربات دسترسی داره.", show_alert=True)
        return
    if action == "stats":
        await _edit_or_send(update, context, f"👥 تعداد کل کاربران: {db.count_users()}")
    elif action == "back":
        await _edit_or_send(update, context, "پنل مدیریت ربات:", reply_markup=admin_panel_keyboard())
        await update.callback_query.answer("بازگشت")
    elif action == "llm_costs":
        await _show_llm_cost_dashboard(update, context)
    elif action == "llm_pricing":
        await _edit_or_send(
            update,
            context,
            _llm_pricing_text(),
            reply_markup=llm_cost_pricing_keyboard(),
        )
    elif action == "set_plan":
        context.user_data["awaiting"] = "admin_set_plan"
        await _edit_or_send(
            update,
            context,
            "فرمت را ارسال کنید:\n`user_id_or_username plan`\n\n"
            "مثال: `123456789 silver` یا `@username gold`\n"
            "پلن‌ها: free، silver، gold",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=awaiting_inline_keyboard(),
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
            "persian": "phonetic_show_persian",
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
    elif action == "set_model":
        context.user_data["awaiting"] = "admin_set_model"
        await _edit_or_send(
            update,
            context,
            f"نام مدل فعلی: `{db.get_setting('ai_model')}`\nنام مدل جدید رو بفرست:",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=awaiting_inline_keyboard(),
        )
    elif action == "set_base_url":
        context.user_data["awaiting"] = "admin_set_base_url"
        await _edit_or_send(
            update,
            context,
            f"Base URL فعلی: `{db.get_setting('ai_base_url')}`\nBase URL جدید رو بفرست:",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=awaiting_inline_keyboard(),
        )
    elif action == "set_api_key":
        context.user_data["awaiting"] = "admin_set_api_key"
        await _edit_or_send(
            update,
            context,
            "API Key جدید رو بفرست (بعداً این پیام رو از چت پاک کن):",
            reply_markup=awaiting_inline_keyboard(),
        )
    elif action == "broadcast":
        context.user_data["awaiting"] = "admin_broadcast"
        await _edit_or_send(
            update,
            context,
            "متن پیام همگانی رو بفرست:",
            reply_markup=awaiting_inline_keyboard(),
        )
    elif action == "show_settings":
        key = db.get_setting("ai_api_key", "")
        masked = (key[:6] + "…" + key[-4:]) if len(key) > 12 else "—"
        await _edit_or_send(
            update,
            context,
            f"🤖 مدل: `{db.get_setting('ai_model')}`\n"
            f"🌐 Base URL: `{db.get_setting('ai_base_url')}`\n"
            f"🔑 API Key: `{masked}`\n"
            f"🗣 IPA: {'روشن' if db.get_bool_setting('phonetic_show_ipa', True) else 'خاموش'}\n"
            f"🗣 Persian: {'روشن' if db.get_bool_setting('phonetic_show_persian', True) else 'خاموش'}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


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
                reply_markup=awaiting_inline_keyboard(),
            )
        elif len(parts) == 3 and parts[2] == "set_output":
            context.user_data["awaiting"] = "llm_price_output"
            await _edit_or_send(
                update,
                context,
                "Send output cost per 1M tokens in USD:",
                reply_markup=awaiting_inline_keyboard(),
            )
        elif len(parts) == 3 and parts[2] == "set_rate":
            context.user_data["awaiting"] = "llm_price_rate"
            await _edit_or_send(
                update,
                context,
                "Send the USD→Toman rate:",
                reply_markup=awaiting_inline_keyboard(),
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
                reply_markup=awaiting_inline_keyboard(),
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
                reply_markup=awaiting_inline_keyboard(),
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
    if awaiting == "admin_set_model":
        db.set_setting("ai_model", text)
        await update.message.reply_text(f"مدل جدید ثبت شد: `{text}`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    if awaiting == "llm_cost_user":
        if text.casefold() in {"all", "همه", "none", "null"}:
            _llm_cost_set_state(context, user_id=None)
        else:
            target = db.find_user(text)
            if not target:
                context.user_data["awaiting"] = "llm_cost_user"
                await update.message.reply_text(
                    "User not found. Send a valid user_id or @username, or type all.",
                    reply_markup=awaiting_inline_keyboard(),
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
                reply_markup=awaiting_inline_keyboard(),
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

    if awaiting == "admin_set_base_url":
        db.set_setting("ai_base_url", text)
        await update.message.reply_text(f"Base URL جدید ثبت شد: `{text}`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    if awaiting == "admin_set_api_key":
        db.set_setting("ai_api_key", text)
        await update.message.reply_text("API Key جدید ثبت شد. ✅")
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
