"""Focused tests for the admin_plans expand module (Finding #7, task 7.2).

Task 7.2 establishes the plans domain seam by re-exporting the standalone plan
symbols verbatim, with no behavior change and no routing changes yet.
"""

import unittest

from config.keyboards import (
    plan_manager_keyboard,
    plan_view_keyboard,
    plan_wizard_keyboard,
    plan_wizard_summary_keyboard,
)
from handlers import admin
from handlers import admin_plans


class TestAdminPlansModule(unittest.TestCase):
    def test_reexports_plan_functions_verbatim(self):
        for name in (
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
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(admin_plans, name), getattr(admin, name))

    def test_reexports_plan_keyboards_verbatim(self):
        for name, kbd in (
            ("plan_manager_keyboard", plan_manager_keyboard),
            ("plan_view_keyboard", plan_view_keyboard),
            ("plan_wizard_keyboard", plan_wizard_keyboard),
            ("plan_wizard_summary_keyboard", plan_wizard_summary_keyboard),
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(admin_plans, name), kbd)

    def test_all_is_explicit(self):
        self.assertEqual(
            admin_plans.__all__,
            [
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
            ],
        )


if __name__ == "__main__":
    unittest.main()
