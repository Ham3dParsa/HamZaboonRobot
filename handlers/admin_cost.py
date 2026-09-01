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
    llm_legend_back_keyboard,
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
        "view": "overview",
        "detail": False,
        "plan": None,
        "user_id": None,
        "request_kind": None,
        "model": None,
        "outcome": None,
        "breakdown": "preset",
        "breakdown_page": 0,
        "recent_page": 0,
        "show_projection": False,
    }


def _llm_cost_state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    raw = context.user_data.get("llm_cost_state")
    if not isinstance(raw, dict):
        state = _llm_cost_default_state()
    else:
        merged = _llm_cost_default_state()
        merged.update({key: raw.get(key, value) for key, value in merged.items()})
        state = merged
        # migrate legacy detail=True (pre-hub) where view was missing → recent
        if bool(state.get("detail")) and state.get("view") == "overview" and "view" not in raw:
            state["view"] = "recent"
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
        return "-"
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


def _llm_cost_filter_pill(state: dict[str, object], currency_mode: str = "both") -> str:
    """Compact human pill - only non-all filters, e.g. 'MTD - Both' or 'MTD - Gold - vocab'."""
    parts: list[str] = []
    rng = str(state.get("range") or "mtd").upper()
    parts.append(rng)
    # currency as pill part
    cur = currency_mode if currency_mode in {"usd", "toman", "both"} else "both"
    cur_label = {"usd": "USD", "toman": "Toman", "both": "Both"}[cur]
    parts.append(cur_label)
    for key, label in (
        ("plan", None),
        ("user_id", None),
        ("request_kind", None),
        ("model", None),
        ("outcome", None),
    ):
        val = state.get(key)
        if val not in {None, "", "all"}:
            # shorten
            parts.append(str(val))
    return " · ".join(parts)


def _llm_cost_header_badge(billed_failures: int, billed_cost_usd: float, billed_cost_toman: float) -> str:
    if billed_failures > 0:
        return f"🟡 {billed_failures} billed fail ({_llm_cost_currency_text(billed_cost_usd, billed_cost_toman)})"
    return "🟢 Healthy - no billable failures"


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


# ---------- Hub helpers ----------

def _llm_cost_single_cost(c_usd: float, c_toman: float, mode: str) -> str:
    if mode == "usd":
        return f"${c_usd:,.4f}"
    if mode == "toman":
        return f"{round(c_toman):,} T"
    return f"${c_usd:,.4f} ({round(c_toman):,} T)"


def _build_overview_message(
    state: dict[str, object],
    currency_mode: str,
    summary: dict[str, object],
    filters: dict[str, object],
) -> Message:
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
    billed_failure_cost_usd = float(summary.get("billed_failure_cost_usd") or 0)
    billed_failure_cost_toman = float(summary.get("billed_failure_cost_toman") or 0)
    success_rate = _llm_cost_percent(success_count, request_count)
    billed_failure_rate = _llm_cost_percent(billed_failures, request_count)
    badge = _llm_cost_header_badge(billed_failures, billed_failure_cost_usd, billed_failure_cost_toman)

    msg = Message()
    msg.add_line(heading(2, plain(f"LLM Cost - {badge}")))
    msg.add_line(quote(plain(f"Filters: {_llm_cost_filter_pill(state, currency_mode)}")))

    # Dedicated Requests table (4-col LTR English, unslopped, no mdash)
    total_cost = _llm_cost_single_cost(cost_usd, cost_toman, currency_mode)
    avg_cost = _fmt_avg_triple(input_cost_usd, output_cost_usd, cost_usd, input_cost_toman, output_cost_toman, cost_toman, request_count, currency_mode) if request_count else "-"
    requests_header = (plain("Metric"), plain("Count"), plain("Cost"), plain("Avg"))
    requests_row = (plain("Requests"), plain(f"{request_count:,}"), plain(total_cost), plain(avg_cost))
    msg.add_line(table(requests_header, requests_row))

    # General metrics table (2-col LTR English, unslopped)
    overview_header = (plain("Metric"), plain("Value"))
    tokens_triple = _fmt_tokens_triple(prompt_tokens, completion_tokens, total_tokens)
    latency_str = f"{round(float(avg_latency), 1) if avg_latency is not None else 0.0} ms"
    overview_rows = [
        (plain("Tokens"), plain(tokens_triple)),
        (plain("Avg latency"), plain(latency_str)),
        (plain("Success rate"), plain(f"{success_rate} ({success_count:,})")),
        (plain("Billed failure rate"), plain(f"{billed_failure_rate} ({billed_failures:,}) - {_llm_cost_single_cost(billed_failure_cost_usd, billed_failure_cost_toman, currency_mode)}")),
    ]
    msg.add_line(table(overview_header, *overview_rows))

    # Projection - only when toggled, no collapsed inline quote
    if state.get("range") == "mtd" and bool(state.get("show_projection")):
        projection = _llm_cost_projection(filters)
        if projection:
            linear, rolling, ratio = projection
            msg.add_line(heading(3, plain("Month-end Projection")))
            proj_header = (plain("Projection"), plain("Value"), plain("Cost"), plain("Note"))
            proj_rows = [
                (plain("Linear"), plain("MTD run rate"), plain(linear), plain("-")),
                (plain("Rolling 7d"), plain("recent daily avg"), plain(rolling), plain(f"{ratio:.1f}x" if ratio >= 2 else "-")),
            ]
            msg.add_line(table(proj_header, *proj_rows))
            if ratio >= 2:
                msg.add_line(quote(plain(f"Rolling projection is {ratio:.1f}x the linear projection")))
    return msg


def _build_breakdown_message(
    state: dict[str, object],
    currency_mode: str,
    summary: dict[str, object],
    filters: dict[str, object],
    rows_all: list[dict] | None = None,
    total_count: int | None = None,
) -> Message:
    cost_usd = float(summary.get("cost_usd") or 0)
    breakdown = str(state.get("breakdown") or "preset")
    if breakdown not in _BREAKDOWN_TABS:
        breakdown = "preset"
    title = _BREAKDOWN_LABELS.get(breakdown, breakdown)
    page = int(state.get("breakdown_page") or 0)
    page = max(0, page)
    limit = 5

    msg = Message()
    badge = _llm_cost_header_badge(int(summary.get("billed_failure_count") or 0), float(summary.get("billed_failure_cost_usd") or 0), float(summary.get("billed_failure_cost_toman") or 0))
    msg.add_line(heading(2, plain(f"LLM Cost - {badge}")))
    msg.add_line(quote(plain(f"Filters: {_llm_cost_filter_pill(state, currency_mode)}")))
    msg.add_line(heading(3, plain(f"{title}")))

    bd_header = (plain("Name"), plain("Req"), plain("Avg Cost"), plain("Share"))
    # proper LIMIT/OFFSET pagination (no flat cap); rows_all kept for legacy tests that pass pre-fetched list
    if rows_all is not None:
        # legacy path: rows_all is full list (old _show pre-fetch with limit 100)
        group_by = "preset_kind" if breakdown == "preset_kind" else _BREAKDOWN_GROUP.get(breakdown, "preset_name")
        total = len(rows_all)
        total_pages = max(1, (total + limit - 1) // limit) if total else 1
        page = min(page, total_pages - 1)
        rows = rows_all[page * limit : (page + 1) * limit]
        if not rows_all:
            msg.add_line(quote(plain("- none - try Clear filters")))
            return msg
    else:
        if total_count is not None:
            total = total_count
            group_by = "preset_kind" if breakdown == "preset_kind" else _BREAKDOWN_GROUP.get(breakdown, "preset_name")
            total_pages = max(1, (total + limit - 1) // limit) if total else 1
            page = min(page, total_pages - 1)
            if breakdown == "preset_kind":
                rows = db.breakdown_llm_requests_preset_kind(filters, limit=limit, offset=page * limit)
            else:
                rows = db.breakdown_llm_requests(group_by, filters, limit=limit, offset=page * limit)
        else:
            if breakdown == "preset_kind":
                total = db.count_breakdown_preset_kind_groups(filters)
                total_pages = max(1, (total + limit - 1) // limit) if total else 1
                page = min(page, total_pages - 1)
                rows = db.breakdown_llm_requests_preset_kind(filters, limit=limit, offset=page * limit)
                group_by = "preset_kind"
            else:
                group_by = _BREAKDOWN_GROUP.get(breakdown, "preset_name")
                total = db.count_breakdown_groups(group_by, filters)
                total_pages = max(1, (total + limit - 1) // limit) if total else 1
                page = min(page, total_pages - 1)
                rows = db.breakdown_llm_requests(group_by, filters, limit=limit, offset=page * limit)
        if total == 0:
            msg.add_line(quote(plain("- none - try Clear filters")))
            return msg
    # common render for both legacy and offset paths (non-empty)
    bd_rows = []
    for row in rows:
        bucket = row.get("bucket")
        if group_by == "plan":
            bucket = {"free": "free", "silver": "silver", "gold": "gold"}.get(str(bucket), str(bucket))
        bucket = str(bucket or "-")
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
    msg.add_line(quote(plain(f"Page {page + 1}/{total_pages} - {total} buckets - Showing {page*limit+1}-{page*limit+len(bd_rows)}")))
    return msg


def _build_recent_message(
    state: dict[str, object],
    currency_mode: str,
    summary: dict[str, object],
    filters: dict[str, object],
    rows_all: list[dict] | None = None,
    total_count: int | None = None,
) -> Message:
    page = int(state.get("recent_page") or 0)
    page = max(0, page)
    limit = 8

    msg = Message()
    badge = _llm_cost_header_badge(int(summary.get("billed_failure_count") or 0), float(summary.get("billed_failure_cost_usd") or 0), float(summary.get("billed_failure_cost_toman") or 0))
    msg.add_line(heading(2, plain(f"LLM Cost - {badge}")))
    msg.add_line(quote(plain(f"Filters: {_llm_cost_filter_pill(state, currency_mode)}")))
    msg.add_line(heading(3, plain("Recent Requests")))

    # proper LIMIT/OFFSET pagination (no flat cap); rows_all kept for legacy pre-fetched list
    if rows_all is not None:
        total = len(rows_all)
        total_pages = max(1, (total + limit - 1) // limit) if total else 1
        page = min(page, total_pages - 1)
        rows = rows_all[page * limit : (page + 1) * limit]
        if not rows_all:
            msg.add_line(quote(plain("- none")))
            return msg
    else:
        total = total_count if total_count is not None else int(summary.get("request_count") or 0)
        total_pages = max(1, (total + limit - 1) // limit) if total else 1
        page = min(page, total_pages - 1)
        rows = db.recent_llm_requests(filters, limit=limit, offset=page * limit)
        if total == 0:
            msg.add_line(quote(plain("- none")))
            return msg
    # common: render table for non-empty (both branches)
    recent_header = (plain("Time"), plain("Status"), plain("Kind · Model"), plain("Cost"))
    recent_rows = []
    for row in rows:
        t = str(row.get("created_at") or "")[:19]
        icon = _llm_cost_status_icon(row.get("outcome"))
        status = f"{icon} {row.get('outcome')}"
        kind_model = f"{row.get('request_kind')} · {row.get('model')}"
        c_usd = float(row.get("cost_usd") or 0)
        c_toman = float(row.get("cost_toman") or 0)
        cost_cell = _llm_cost_single_cost(c_usd, c_toman, currency_mode)
        recent_rows.append((plain(t), plain(status), plain(kind_model), plain(cost_cell)))
    msg.add_line(table(recent_header, *recent_rows))
    msg.add_line(quote(plain(f"Page {page + 1}/{total_pages} - {total} requests - Showing {page*limit+1}-{page*limit+len(rows)}")))
    return msg


# ---------- RichMessage dispatcher (R3/R4/R5) ----------

def _build_llm_cost_message(
    state: dict[str, object],
    currency_mode: str = "both",
) -> Message:
    # honor legacy detail flag: detail=True maps to recent view for backward compat
    view = str(state.get("view") or ("recent" if state.get("detail") else "overview")).lower()
    if view not in {"overview", "breakdown", "recent"}:
        view = "overview"
    filters = _llm_cost_query_filters(state)
    summary = db.summarize_llm_requests(filters)
    currency_mode = currency_mode if currency_mode in {"usd", "toman", "both"} else "both"
    if view == "breakdown":
        return _build_breakdown_message(state, currency_mode, summary, filters)
    if view == "recent":
        return _build_recent_message(state, currency_mode, summary, filters)
    return _build_overview_message(state, currency_mode, summary, filters)


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
            "LLM pricing - rate only (R1)",
            f"- USD to Toman: {profile['usd_to_toman_rate']:,.0f}",
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
        # backward compat: detail=True → recent view
        view = "recent" if detail else "overview"
        state = _llm_cost_set_state(context, detail=detail, view=view)
    currency_mode = _llm_cost_currency_mode(context)
    filters = _llm_cost_query_filters(state)
    view = str(state.get("view") or "overview")
    # single fetch for summary; breakdown/recent paged via LIMIT/OFFSET + COUNT (no flat cap)
    summary = db.summarize_llm_requests(filters)
    breakdown_total_pages = 1
    recent_total_pages = 1
    breakdown_total = 0
    recent_total = 0
    if view == "breakdown":
        br = str(state.get("breakdown") or "preset")
        if br == "preset_kind":
            breakdown_total = db.count_breakdown_preset_kind_groups(filters)
        else:
            group_by = _BREAKDOWN_GROUP.get(br, "preset_name")
            breakdown_total = db.count_breakdown_groups(group_by, filters)
        breakdown_total_pages = max(1, (breakdown_total + 4) // 5) if breakdown_total else 1
    elif view == "recent":
        recent_total = int(summary.get("request_count") or 0)
        recent_total_pages = max(1, (recent_total + 7) // 8) if recent_total else 1
    # clamp pages for keyboard (avoid 1000/N when stored pg is crafted)
    breakdown_page_clamped = min(max(0, int(state.get("breakdown_page") or 0)), max(0, breakdown_total_pages - 1))
    recent_page_clamped = min(max(0, int(state.get("recent_page") or 0)), max(0, recent_total_pages - 1))
    # build message reusing totals (no second COUNT)
    if view == "breakdown":
        msg = _build_breakdown_message(state, currency_mode, summary, filters, total_count=breakdown_total)
    elif view == "recent":
        msg = _build_recent_message(state, currency_mode, summary, filters, total_count=recent_total)
    else:
        msg = _build_overview_message(state, currency_mode, summary, filters)
    kb = llm_cost_dashboard_keyboard(
        bool(state.get("detail")),
        active_range=str(state.get("range") or "mtd"),
        breakdown=str(state.get("breakdown") or "preset"),
        currency=_llm_cost_currency_mode(context),
        view=str(state.get("view") or "overview"),
        breakdown_page=breakdown_page_clamped,
        recent_page=recent_page_clamped,
        show_projection=bool(state.get("show_projection")),
        breakdown_total_pages=breakdown_total_pages,
        recent_total_pages=recent_total_pages,
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
    if action == "noop":
        await notify_callback(update.callback_query)
        return
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
            await notify_callback(update.callback_query, "قیمت ورودی/خروجی حذف شد - فقط نرخ تبدیل فعال است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        else:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if action == "range" and len(parts) == 3:
        val = parts[2]
        if val not in {"today", "7d", "30d", "mtd", "all"}:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        # preserve view (do not force-bounce); single atomic update keeps view/detail in sync
        cur_view = str(_llm_cost_state(context).get("view") or "overview")
        _llm_cost_set_state(context, range=val, detail=cur_view == "recent", breakdown_page=0, recent_page=0, show_projection=False)
        await _show_llm_cost_dashboard(update, context)
    elif action == "breakdown" and len(parts) == 3:
        tab = parts[2]
        if tab not in _BREAKDOWN_TABS:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        _llm_cost_set_state(context, breakdown=tab, view="breakdown", breakdown_page=0)
        await _show_llm_cost_dashboard(update, context)
    elif action == "view" and len(parts) == 3:
        view = parts[2]
        if view not in {"overview", "breakdown", "recent"}:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        detail_flag = view == "recent"
        _llm_cost_set_state(context, view=view, detail=detail_flag)
        await _show_llm_cost_dashboard(update, context)
    elif action == "page" and len(parts) == 4:
        target = parts[2]
        try:
            pg = int(parts[3])
        except ValueError:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        if target == "breakdown":
            # clamp only to >=0 here; _show/_build will clamp to total_pages-1 via COUNT (no flat cap, no duplicate COUNT)
            pg = max(0, pg)
            _llm_cost_set_state(context, breakdown_page=pg, view="breakdown", detail=False)
            await _show_llm_cost_dashboard(update, context)
        elif target == "recent":
            pg = max(0, pg)
            _llm_cost_set_state(context, recent_page=pg, view="recent", detail=True)
            await _show_llm_cost_dashboard(update, context)
        else:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
    elif action == "projection" and len(parts) == 2:
        cur = bool(_llm_cost_state(context).get("show_projection"))
        _llm_cost_set_state(context, show_projection=not cur, view="overview")
        await _show_llm_cost_dashboard(update, context)
    elif action == "currency" and len(parts) == 3:
        mode = parts[2]
        if mode == "cycle":
            cur = _llm_cost_currency_mode(context)
            nxt = {"both": "usd", "usd": "toman", "toman": "both"}[cur]
            context.user_data["llm_cost_currency"] = nxt
            await _show_llm_cost_dashboard(update, context)
            return
        if mode not in {"usd", "toman", "both"}:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        context.user_data["llm_cost_currency"] = mode
        await _show_llm_cost_dashboard(update, context)
    elif action == "legend" and len(parts) == 2:
        await _edit_or_send(
            update,
            context,
            "راهنما: ✅ موفق | ❌ هزینه‌دار | ⚠️ بدون هزینه\n\n"
            "System health: no billable failures when Billed failure rate is 0%",
            reply_markup=llm_legend_back_keyboard(),
        )
        return
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
        _llm_cost_set_state(context, plan=None if parts[2] == "all" else parts[2], detail=False, view="overview", breakdown_page=0, recent_page=0)
        await _show_llm_cost_dashboard(update, context)
    elif action == "kind" and len(parts) == 3:
        _llm_cost_set_state(context, request_kind=None if parts[2] == "all" else parts[2], detail=False, view="overview", breakdown_page=0, recent_page=0)
        await _show_llm_cost_dashboard(update, context)
    elif action == "status" and len(parts) == 3:
        _llm_cost_set_state(context, outcome=None if parts[2] == "all" else parts[2], detail=False, view="overview", breakdown_page=0, recent_page=0)
        await _show_llm_cost_dashboard(update, context)
    elif action == "clear":
        context.user_data["llm_cost_state"] = _llm_cost_default_state()
        await _show_llm_cost_dashboard(update, context)
    elif action == "refresh":
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
