"""Admin cost/LLM domain module (Finding #7, task 7.5).

Migrate step: the LLM cost/pricing handler logic now lives here instead of the
admin monolith. The admin monolith (and bot.py) import the cost functions from
this module. All behavior and callback strings are unchanged.
"""

import calendar
import datetime
from collections import defaultdict

from telegram import Update
from telegram.ext import ContextTypes

from config import APP_TZ
from services import db
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers import _edit_or_send
from config.keyboards import (
    admin_awaiting_inline_keyboard,
    admin_cost_keyboard,
    llm_cost_dashboard_keyboard,
    llm_cost_kind_keyboard,
    llm_cost_plan_keyboard,
    llm_cost_pricing_keyboard,
    llm_cost_status_keyboard,
)

_app_timezone = APP_TZ


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
        await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
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
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
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
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
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
        await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)


async def _handle_cost_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    awaiting: str,
    text: str,
) -> None:
    """Route LLM-cost / pricing text-input awaiting states to their handlers.

    Mirrors the inline blocks that previously lived in the admin monolith's
    ``_handle_admin_text_input``. Behavior and awaiting strings are unchanged.
    """
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


async def handle_cost_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
) -> None:
    """Route cost/LLM-cost admin callback sub-actions to their handlers.

    Mirrors the inline ``admin:cost_dashboard`` / ``admin:llm_costs`` /
    ``admin:llm_pricing`` branches that previously lived in the admin monolith's
    ``_handle_admin_callback``. The owner check is performed by the caller.
    Behavior and action strings are unchanged.
    """
    if action == "llm_costs":
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
        await notify_callback(update.callback_query)


__all__ = [
    "_handle_cost_text_input",
    "_handle_llm_callback",
    "handle_cost_callback",
    "_llm_cost_currency_text",
    "_llm_cost_default_state",
    "_llm_cost_filter_label",
    "_llm_cost_percent",
    "_llm_cost_projection",
    "_llm_cost_query_filters",
    "_llm_cost_range_bounds",
    "_llm_cost_report_text",
    "_llm_cost_set_state",
    "_llm_cost_state",
    "_llm_cost_state_label",
    "_llm_cost_status_icon",
    "_llm_pricing_text",
    "_show_llm_cost_dashboard",
    "admin_awaiting_inline_keyboard",
    "admin_cost_keyboard",
    "llm_cost_dashboard_keyboard",
    "llm_cost_kind_keyboard",
    "llm_cost_plan_keyboard",
    "llm_cost_pricing_keyboard",
    "llm_cost_status_keyboard",
]
