"""Admin plans domain module (Finding #7 seam).

Expand step: this module re-exports the standalone plan symbols currently living
in the admin monolith so that task 7.5 (Batch A migration) can move the
``admin:plans`` handler logic here without changing call sites. Behavior is
unchanged; nothing routes to this module yet. The plan keyboards are re-exported
from ``config.keyboards`` and the plan handler functions from ``handlers.admin``
(verbatim).
"""

from handlers.admin import (
    _handle_plan_set_active,
    _handle_plan_wizard_back,
    _handle_plan_wizard_cancel,
    _handle_plan_wizard_input,
    _handle_plan_wizard_next,
    _handle_plan_wizard_save,
    _show_plan_list,
    _show_plan_view,
    _show_plan_wizard_field,
    _show_plan_wizard_summary,
    _start_plan_wizard,
    _validate_plan_wizard_value,
)
from config.keyboards import (
    plan_manager_keyboard,
    plan_view_keyboard,
    plan_wizard_keyboard,
    plan_wizard_summary_keyboard,
)

__all__ = [
    "_handle_plan_set_active",
    "_handle_plan_wizard_back",
    "_handle_plan_wizard_cancel",
    "_handle_plan_wizard_input",
    "_handle_plan_wizard_next",
    "_handle_plan_wizard_save",
    "_show_plan_list",
    "_show_plan_view",
    "_show_plan_wizard_field",
    "_show_plan_wizard_summary",
    "_start_plan_wizard",
    "_validate_plan_wizard_value",
    "plan_manager_keyboard",
    "plan_view_keyboard",
    "plan_wizard_keyboard",
    "plan_wizard_summary_keyboard",
]
