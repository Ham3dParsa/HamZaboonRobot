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
    "_validate_plan_wizard_value",
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

    def test_reexports_plan_keyboards_verbatim(self):
        for name, kbd in _KEYBOARDS.items():
            with self.subTest(name=name):
                self.assertIs(getattr(admin_plans, name), kbd)

    def test_plan_wizard_constants_present(self):
        self.assertEqual(
            admin_plans.TOTAL_PLAN_WIZARD_FIELDS, len(admin_plans.PLAN_WIZARD_FIELDS)
        )
        self.assertIn("display_name", admin_plans.PLAN_WIZARD_FIELD_LABELS)
        self.assertIn(0, admin_plans.PLAN_WIZARD_GROUP_HEADERS)
        self.assertIn("query_quota", admin_plans.PLAN_WIZARD_FIELD_HINTS)

    def test_all_is_explicit(self):
        expected = sorted(
            list(_PLAN_FUNCTIONS)
            + list(_KEYBOARDS.keys())
            + [
                "PLAN_WIZARD_FIELD_HINTS",
                "PLAN_WIZARD_FIELD_LABELS",
                "PLAN_WIZARD_FIELDS",
                "PLAN_WIZARD_GROUP_HEADERS",
                "TOTAL_PLAN_WIZARD_FIELDS",
            ],
            key=lambda s: s.lower(),
        )
        self.assertEqual(sorted(admin_plans.__all__, key=lambda s: s.lower()), expected)


if __name__ == "__main__":
    unittest.main()
