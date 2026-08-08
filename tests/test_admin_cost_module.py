"""Focused tests for the admin_cost expand module (Finding #7, task 7.3).

Task 7.3 establishes the cost/LLM domain seam by re-exporting the standalone
cost symbols verbatim, with no behavior change and no routing changes yet.
"""

import unittest

from config.keyboards import (
    admin_cost_keyboard,
    llm_cost_dashboard_keyboard,
    llm_cost_kind_keyboard,
    llm_cost_plan_keyboard,
    llm_cost_pricing_keyboard,
    llm_cost_status_keyboard,
)
from handlers import admin
from handlers import admin_cost

_FUNCTIONS = (
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
)

_KEYBOARDS = {
    "admin_cost_keyboard": admin_cost_keyboard,
    "llm_cost_dashboard_keyboard": llm_cost_dashboard_keyboard,
    "llm_cost_kind_keyboard": llm_cost_kind_keyboard,
    "llm_cost_plan_keyboard": llm_cost_plan_keyboard,
    "llm_cost_pricing_keyboard": llm_cost_pricing_keyboard,
    "llm_cost_status_keyboard": llm_cost_status_keyboard,
}


class TestAdminCostModule(unittest.TestCase):
    def test_reexports_cost_functions_verbatim(self):
        for name in _FUNCTIONS:
            with self.subTest(name=name):
                self.assertIs(getattr(admin_cost, name), getattr(admin, name))

    def test_reexports_cost_keyboards_verbatim(self):
        for name, kbd in _KEYBOARDS.items():
            with self.subTest(name=name):
                self.assertIs(getattr(admin_cost, name), kbd)

    def test_all_is_explicit(self):
        expected = sorted(
            list(_FUNCTIONS) + list(_KEYBOARDS.keys()),
            key=lambda s: s.lower(),
        )
        self.assertEqual(sorted(admin_cost.__all__, key=lambda s: s.lower()), expected)


if __name__ == "__main__":
    unittest.main()
