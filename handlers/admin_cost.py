"""Admin cost/LLM domain module (Finding #7, task 7.5).

R3/R4/R5: RichMessage tables, max 4 cols, English + Persian legend, ✅ markers.
R1: pricing page keeps only USD→Toman rate (no input/output price UI).
R6: selected buttons show ✅ (keyboard side; state reflected here).
"""

import calendar
import datetime
from collections import defaultdict

from telegram import Update
from telegram.ext import ContextTypes

from handlers.flows import mark_awaiting_consumed

from config import APP_TZ
from services import db
from services.ai import ai_read_cache
from services.send_pretty import (
    Backend,
    Message,
    RawFormat,
    bold,
    heading,
    plain,
    quote,
    say,
    table,
)
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

# breakdown tab values – single active breakdown at a time (R4/R5)
_BREAKDOWN_TABS = ("preset", "plan", "kind", "model", "user", "preset_kind")
_BREAKDOWN_LABELS = {
    "preset": "🔧 By preset",
    "plan": "📦 By plan",
    "kind": "🧩 By request kind",
    "model": "🤖 By model",
    "user": "👤 By user",
    "preset_kind": "🧩 By Preset×Kind",
}
_BREAKDOWN_GROUP = {
    "preset": "preset_name",
    "plan": "plan",
    "kind": "request_kind",
    "model": "model",
    "user": "user_id",
    "preset_kind": "preset_kind",  # composite – handled separately
}


def _llm_cost_default_state() -> dict[str, object]:
    return {
        "range": "mtd",
        "detail": False,
        "plan": None,
        "user_id": None,
        "request_kind": None,
        "model": None,
        "outcome": None,
        "breakdown": "preset",
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
    elif range_name == "mtd":
        start = today.replace(day=1)
        end = today
        label = "MTD"
    else:
        raise ValueError(f"Unknown llm range {range_name!r}")
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


# ---------- R3 helpers: currency mode + triple formatting ----------

def _llm_cost_currency_mode(context: ContextTypes.DEFAULT_TYPE | None = None, override: str | None = None) -> str:
    if override in {"usd", "toman", "both"}:
        return override
    if context is not None:
        try:
            mode = context.user_data.get("llm_cost_currency", "both")  # type: ignore[union-attr]
        except Exception:
            mode = "both"
        if mode in {"usd", "toman", "both"}:
            return mode
    return "both"


def _fmt_cost_triple(
    in_usd: float,
    out_usd: float,
    total_usd: float,
    in_toman: float,
    out_toman: float,
    total_toman: float,
    mode: str = "both",
) -> str:
    mode = mode if mode in {"usd", "toman", "both"} else "both"
    if mode == "usd":
        return f"${in_usd:.4f} / ${out_usd:.4f} / ${total_usd:.4f}"
    if mode == "toman":
        return f"{round(in_toman):,} / {round(out_toman):,} / {round(total_toman):,} T"
    # both – show USD triple + toman total in parens to stay compact (1 cell)
    # e.g. "$0.0100 / $0.0050 / $0.0150 (1,500 T)"
    usd_part = f"${in_usd:.4f} / ${out_usd:.4f} / ${total_usd:.4f}"
    toman_part = f"{round(total_toman):,} T"
    return f"{usd_part} ({toman_part})"


def _fmt_avg_triple(
    in_usd: float,
    out_usd: float,
    total_usd: float,
    in_toman: float,
    out_toman: float,
    total_toman: float,
    req: int,
    mode: str = "both",
) -> str:
    if not req:
        return "—"
    return _fmt_cost_triple(
        in_usd / req,
        out_usd / req,
        total_usd / req,
        in_toman / req,
        out_toman / req,
        total_toman / req,
        mode,
    )


def _fmt_tokens_triple(prompt: int, completion: int, total: int) -> str:
    return f"{prompt:,} / {completion:,} / {total:,}"


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
    daily_costs = db.daily_costs_grouped(projection_filters)
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
    # R8 emoji dictionary (global): ✅/❌/⚠️ = result / system warnings
    # (health). 🟢/⚫ are ON/OFF toggles only and must never mark an outcome.
    # Billed failure = hard error (financial loss) -> ❌; zero-cost failure =
    # warning (failed but no money lost) -> ⚠️.
    return {
        "success": "✅",
        "failure_billed": "❌",
        "failure_zero_cost": "⚠️",
    }.get(str(outcome), "❌")


# ---------- RichMessage builder (R3/R4/R5) ----------

def _build_llm_cost_message(
    state: dict[str, object],
    currency_mode: str = "both",
) -> Message:
    filters = _llm_cost_query_filters(state)
    summary = db.summarize_llm_requests(filters)
    request_count = int(summary.get("request_count") or 0)
    prompt_tokens = int(summary.get("prompt_tokens") or 0)
    completion_tokens = int(summary.get("completion_tokens") or 0)
    total_tokens = int(summary.get("total_tokens") or 0)
    cost_usd = float(summary.get("cost_usd") or 0)
    cost_toman = float(summary.get("cost_toman") or 0)
    input_cost_usd = float(summary.get("input_cost_usd") or 0)
    output_cost_usd = float(summary.get("output_cost_usd") or 0)
    input_cost_toman = float(summary.get("input_cost_toman") or 0)
    output_cost_toman = float(summary.get("output_cost_toman") or 0)
    avg_latency = summary.get("avg_latency_ms")
    success_count = int(summary.get("success_count") or 0)
    billed_failures = int(summary.get("billed_failure_count") or 0)
    zero_cost_failures = int(summary.get("zero_cost_failure_count") or 0)
    billed_failure_cost_usd = float(summary.get("billed_failure_cost_usd") or 0)
    billed_failure_cost_toman = float(summary.get("billed_failure_cost_toman") or 0)
    success_rate = _llm_cost_percent(success_count, request_count)
    billed_failure_rate = _llm_cost_percent(billed_failures, request_count)
    range_label = str(state.get("range") or "mtd").upper()
    currency_mode = currency_mode if currency_mode in {"usd", "toman", "both"} else "both"

    msg = Message()
    # heading – static literal pre-escaped (English)
    msg.add_line(heading(2, plain("📊 LLM Cost — Overview")))
    msg.add_line(quote(plain(f"Scope: {_llm_cost_state_label(state)} • Range: {range_label} • Currency: {currency_mode}")))

    # Overview KPI table – exactly 4 cols (R3 max 4)
    # Header: Metric | Value | Cost | Note
    overview_header = (plain("Metric"), plain("Value"), plain("Cost"), plain("Note"))
    cost_triple = _fmt_cost_triple(input_cost_usd, output_cost_usd, cost_usd, input_cost_toman, output_cost_toman, cost_toman, currency_mode)
    avg_triple = _fmt_avg_triple(input_cost_usd, output_cost_usd, cost_usd, input_cost_toman, output_cost_toman, cost_toman, request_count, currency_mode)
    tokens_triple = _fmt_tokens_triple(prompt_tokens, completion_tokens, total_tokens)
    latency_str = f"{round(float(avg_latency), 1) if avg_latency is not None else 0.0} ms"
    # Keep legacy substrings for compat: "✅ Success rate" and "❌ Billed failure rate" as Metric labels
    overview_rows = [
        (plain("📨 Requests"), plain(f"{request_count:,}"), plain(cost_triple), plain(f"✅ Success rate: {success_rate}")),
        (plain("🪙 Avg cost/req"), plain("—"), plain(avg_triple), plain(f"avg in/out/total")),
        (plain("🧮 Tokens"), plain(tokens_triple), plain("—"), plain("prompt / completion / total")),
        (plain("⏱ Avg latency"), plain(latency_str), plain("—"), plain("ms")),
        (plain("✅ Success rate"), plain(f"{success_rate} ({success_count:,})"), plain("—"), plain("success")),
        (plain("❌ Billed failure rate"), plain(f"{billed_failure_rate} ({billed_failures:,})"), plain(_fmt_cost_triple(0, 0, billed_failure_cost_usd, 0, 0, billed_failure_cost_toman, currency_mode)), plain("billed fail")),
    ]
    msg.add_line(table(overview_header, *overview_rows))

    # Health / attention block – keep legacy phrases for tests (moved to legend submenu, keep minimal inline)
    # Inline health removed per UX request; full legend is in sub-menu via ❓ button

    # Projection – 4-col table when MTD (kept compact, max 4 cols)
    if state.get("range") == "mtd":
        projection = _llm_cost_projection(filters)
        if projection:
            linear, rolling, ratio = projection
            msg.add_line(heading(3, plain("📈 Month-end Projection")))
            proj_header = (plain("Projection"), plain("Value"), plain("Cost"), plain("Note"))
            proj_rows = [
                (plain("Linear"), plain("MTD run rate"), plain(linear), plain("—")),
                (plain("Rolling 7d"), plain("recent daily avg"), plain(rolling), plain(f"{ratio:.1f}×" if ratio >= 2 else "—")),
            ]
            msg.add_line(table(proj_header, *proj_rows))
            if ratio >= 2:
                msg.add_line(quote(plain(f"⚠️ Rolling projection is {ratio:.1f}× the linear projection")))
            # also keep legacy line for test substring "📈 Month-end Projection"
            # already added as heading; table covers details

    # Breakdown – single active tab (R4 4 cols + R5 composite)
    breakdown = str(state.get("breakdown") or "preset")
    if breakdown not in _BREAKDOWN_TABS:
        breakdown = "preset"
    title = _BREAKDOWN_LABELS.get(breakdown, breakdown)
    msg.add_line(heading(3, plain(f"{title} — top 5 by spend")))

    # breakdown table header 4 cols: Name | Req | Avg Cost | Share (R4)
    bd_header = (plain("Name"), plain("Req"), plain("Avg Cost"), plain("Share"))

    if breakdown == "preset_kind":
        rows = db.breakdown_llm_requests_preset_kind(filters, limit=5)
        if not rows:
            msg.add_line(quote(plain("— none")))
        else:
            bd_rows = []
            for row in rows:
                bucket = str(row.get("bucket") or "—")
                req = int(row.get("request_count") or 0)
                in_usd = float(row.get("input_cost_usd") or 0)
                out_usd = float(row.get("output_cost_usd") or 0)
                c_usd = float(row.get("cost_usd") or 0)
                in_t = float(row.get("input_cost_toman") or 0)
                out_t = float(row.get("output_cost_toman") or 0)
                c_t = float(row.get("cost_toman") or 0)
                avg = _fmt_avg_triple(in_usd, out_usd, c_usd, in_t, out_t, c_t, req, currency_mode)
                share = _llm_cost_percent(c_usd, cost_usd)
                bd_rows.append((plain(bucket), plain(f"{req:,}"), plain(avg), plain(share)))
            msg.add_line(table(bd_header, *bd_rows))
    else:
        group_by = _BREAKDOWN_GROUP.get(breakdown, "preset_name")
        rows = db.breakdown_llm_requests(group_by, filters, limit=5)
        if not rows:
            msg.add_line(quote(plain("— none")))
        else:
            bd_rows = []
            for row in rows:
                bucket = row.get("bucket")
                if group_by == "plan":
                    bucket = {"free": "free", "silver": "silver", "gold": "gold"}.get(str(bucket), str(bucket))
                bucket = str(bucket or "—")
                req = int(row.get("request_count") or 0)
                in_usd = float(row.get("input_cost_usd") or 0)
                out_usd = float(row.get("output_cost_usd") or 0)
                c_usd = float(row.get("cost_usd") or 0)
                in_t = float(row.get("input_cost_toman") or 0)
                out_t = float(row.get("output_cost_toman") or 0)
                c_t = float(row.get("cost_toman") or 0)
                avg = _fmt_avg_triple(in_usd, out_usd, c_usd, in_t, out_t, c_t, req, currency_mode)
                share = _llm_cost_percent(c_usd, cost_usd)
                bd_rows.append((plain(bucket), plain(f"{req:,}"), plain(avg), plain(share)))
            msg.add_line(table(bd_header, *bd_rows))

    # Recent requests detail – 4-col table (R3 max 4) when detail=True
    if state.get("detail"):
        rows = db.recent_llm_requests(filters, limit=10)
        msg.add_line(heading(3, plain("🧾 Recent Requests")))
        if not rows:
            msg.add_line(quote(plain("— none")))
        else:
            recent_header = (plain("Time"), plain("Status"), plain("Kind · Model"), plain("Cost"))
            recent_rows = []
            for row in rows:
                t = str(row.get("created_at") or "")[:19]
                icon = _llm_cost_status_icon(row.get("outcome"))
                status = f"{icon} {row.get('outcome')}"
                kind_model = f"{row.get('request_kind')} · {row.get('model')}"
                c_usd = float(row.get("cost_usd") or 0)
                c_toman = float(row.get("cost_toman") or 0)
                # for single-request triple, in/out unknown → show total only as triple with 0 in/out
                cost_cell = _llm_cost_currency_text(c_usd, c_toman)
                recent_rows.append((plain(t), plain(status), plain(kind_model), plain(cost_cell)))
            msg.add_line(table(recent_header, *recent_rows))

    return msg


def _llm_cost_report_text(state: dict[str, object]) -> str:
    """Backward-compat string wrapper (tests expect str).

    New code should use :func:`_build_llm_cost_message` which returns a
    :class:`Message` for ``Backend.RICH`` rendering.
    """
    msg = _build_llm_cost_message(state, currency_mode="both")
    return msg.render(Backend.RICH)


def _llm_pricing_text() -> str:
    # R1: only USD→Toman rate remains; input/output price UI removed
    profile = db.get_llm_cost_profile()
    return "\n".join(
        [
            "LLM pricing — rate only (R1)",
            f"- USD→Toman: {profile['usd_to_toman_rate']:,.0f}",
            "",
            "Use the button below to update the conversion rate.",
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
    currency_mode = _llm_cost_currency_mode(context)
    msg = _build_llm_cost_message(state, currency_mode=currency_mode)
    kb = llm_cost_dashboard_keyboard(
        bool(state.get("detail")),
        active_range=str(state.get("range") or "mtd"),
        breakdown=str(state.get("breakdown") or "preset"),
        currency=_llm_cost_currency_mode(context),
    )
    # route through shared RICH path (retry/concurrency via send_pretty)
    if update.callback_query:
        # Use say with Backend.RICH which edits the callback message
        await say(update, context, msg, backend=Backend.RICH, keyboard=kb, mode="auto")
    else:
        await say(update, context, msg, backend=Backend.RICH, keyboard=kb, mode="auto")


async def _handle_llm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split(":")
    if len(parts) < 2:
        await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    action = parts[1]
    if action == "pricing" and len(parts) >= 2:
        # R1: only set_rate remains; input/output removed
        if len(parts) == 2 or (len(parts) == 3 and parts[2] == "back"):
            await _show_llm_cost_dashboard(update, context)
        elif len(parts) == 3 and parts[2] == "set_rate":
            context.user_data["awaiting"] = "llm_price_rate"
            await _edit_or_send(
                update,
                context,
                "Send the USD→Toman rate:",
                reply_markup=admin_awaiting_inline_keyboard(),
            )
        elif len(parts) == 3 and parts[2] in {"set_input", "set_output"}:
            # removed per R1 – inform admin
            await notify_callback(update.callback_query, "قیمت ورودی/خروجی حذف شد — فقط نرخ تبدیل فعال است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        else:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if action == "range" and len(parts) == 3:
        val = parts[2]
        if val not in {"today", "7d", "30d", "mtd", "all"}:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        _llm_cost_set_state(context, range=val, detail=False)
        await _show_llm_cost_dashboard(update, context)
    elif action == "breakdown" and len(parts) == 3:
        tab = parts[2]
        if tab not in _BREAKDOWN_TABS:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        _llm_cost_set_state(context, breakdown=tab)
        await _show_llm_cost_dashboard(update, context)
    elif action == "currency" and len(parts) == 3:
        mode = parts[2]
        if mode not in {"usd", "toman", "both"}:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        context.user_data["llm_cost_currency"] = mode
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
    """Route LLM-cost / pricing text-input awaiting states to their handlers."""
    if awaiting == "llm_cost_user":
        if text.casefold() in {"all", "همه", "none", "null"}:
            _llm_cost_set_state(context, user_id=None)
        else:
            target = db.find_user(text)
            if not target:
                context.user_data["awaiting"] = "llm_cost_user"
                await say(
                    update,
                    context,
                    "User not found. Send a valid user_id or @username, or type all.",
                    raw=RawFormat.PLAIN,
                    keyboard=admin_awaiting_inline_keyboard(),
                    mode="send",
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

    if awaiting == "llm_price_rate":
        try:
            value = float(text.replace(",", "").strip())
            if value < 0:
                raise ValueError
        except ValueError:
            context.user_data["awaiting"] = awaiting
            await say(
                update,
                context,
                "عدد معتبر بفرست، مثلاً 65000.",
                raw=RawFormat.PLAIN,
                keyboard=admin_awaiting_inline_keyboard(),
                mode="send",
            )
            return
        profile = db.get_llm_cost_profile()
        db.set_llm_cost_profile(
            input_cost_usd_per_million=profile["input_cost_usd_per_million"],
            output_cost_usd_per_million=profile["output_cost_usd_per_million"],
            usd_to_toman_rate=value,
        )
        mark_awaiting_consumed(context)
        ai_read_cache.invalidate_cost_profile()
        await say(update, context, _llm_pricing_text(), raw=RawFormat.PLAIN, mode="send")
        return


async def handle_cost_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
) -> None:
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
    "_build_llm_cost_message",
    "_fmt_cost_triple",
    "_fmt_avg_triple",
    "_llm_cost_currency_mode",
    "_llm_cost_set_state",
    "_llm_cost_state",
    "_llm_cost_state_label",
    "_llm_cost_status_icon",
    "_llm_pricing_text",
    "_show_llm_cost_dashboard",
]
