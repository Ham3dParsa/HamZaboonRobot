"""Focused tests for the admin_plans module (Finding #7, task 7.5 migration).

The plan-manager handler logic now lives in handlers.admin_plans; the admin
monolith imports the plan functions from this module. Behavior is unchanged.
"""

import unittest

from config.keyboards import (
    awaiting_inline_keyboard,
    plan_manager_keyboard,
    plan_view_keyboard,
    plan_wizard_keyboard,
    plan_wizard_summary_keyboard,
)
from handlers import admin
from handlers import admin_plans

_PLAN_FUNCTIONS = (
    "_show_plan_list",
    "_show_plan_view",
    "_start_plan_wizard",
    "_show_plan_wizard_field",
    "_handle_plan_wizard_input",
    "_handle_plan_wizard_next",
    "_handle_plan_wizard_back",
    "_handle_plan_wizard_cancel",
    "_show_plan_wizard_summary",
    "_handle_plan_wizard_save",
    "_handle_plan_set_active",
    "_handle_plans_text_input",
    "handle_plan_callback",
)

_KEYBOARDS = {
    "plan_manager_keyboard": plan_manager_keyboard,
    "plan_view_keyboard": plan_view_keyboard,
    "plan_wizard_keyboard": plan_wizard_keyboard,
    "plan_wizard_summary_keyboard": plan_wizard_summary_keyboard,
    "awaiting_inline_keyboard": awaiting_inline_keyboard,
}


class TestAdminPlansModule(unittest.TestCase):
    def test_defines_plan_functions_used_by_monolith(self):
        for name in _PLAN_FUNCTIONS:
            with self.subTest(name=name):
                self.assertIs(getattr(admin, name), getattr(admin_plans, name))

    def test_uses_plan_keyboards_from_config(self):
        """Keyboards are owned by config.keyboards; the handler imports them for
        use but does not re-export them as its own public API (single source of
        truth, RT-R5)."""
        for name, kbd in _KEYBOARDS.items():
            with self.subTest(name=name):
                self.assertIs(getattr(admin_plans, name), kbd)

    def test_plan_wizard_is_data_driven_by_registry(self):
        from services import plan_fields

        self.assertEqual(
            admin_plans.TOTAL_PLAN_WIZARD_FIELDS, len(plan_fields.field_order())
        )
        self.assertEqual(plan_fields.field_order()[0], "display_name")
        self.assertIn("query_quota", plan_fields.field_order())

    def test_all_is_explicit(self):
        expected = sorted(
            list(_PLAN_FUNCTIONS) + ["TOTAL_PLAN_WIZARD_FIELDS"],
            key=lambda s: s.lower(),
        )
        self.assertEqual(sorted(admin_plans.__all__, key=lambda s: s.lower()), expected)


if __name__ == "__main__":
    unittest.main()
