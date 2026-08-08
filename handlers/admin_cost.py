"""Admin cost/LLM domain module (Finding #7 seam).

Expand step: this module re-exports the standalone cost/LLM symbols currently
living in the admin monolith so that task 7.5 (Batch A) and 7.6 (Batch B) can
move the ``admin:cost_dashboard``/``admin:llm_costs``/``admin:llm_pricing`` and
``llm:`` handler logic here without changing call sites. Behavior is unchanged;
nothing routes to this module yet. The cost keyboards are re-exported from
``config.keyboards`` and the cost handler functions from ``handlers.admin``
(verbatim).
"""

from handlers.admin import (
    _handle_llm_callback,
    _llm_cost_currency_text,
    _llm_cost_default_state,
    _llm_cost_filter_label,
    _llm_cost_percent,
    _llm_cost_projection,
    _llm_cost_query_filters,
    _llm_cost_range_bounds,
    _llm_cost_report_text,
    _llm_cost_set_state,
    _llm_cost_state,
    _llm_cost_state_label,
    _llm_cost_status_icon,
    _llm_pricing_text,
    _show_llm_cost_dashboard,
)
from config.keyboards import (
    admin_cost_keyboard,
    llm_cost_dashboard_keyboard,
    llm_cost_kind_keyboard,
    llm_cost_plan_keyboard,
    llm_cost_pricing_keyboard,
    llm_cost_status_keyboard,
)

__all__ = [
    "_handle_llm_callback",
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
    "admin_cost_keyboard",
    "llm_cost_dashboard_keyboard",
    "llm_cost_kind_keyboard",
    "llm_cost_plan_keyboard",
    "llm_cost_pricing_keyboard",
    "llm_cost_status_keyboard",
]
