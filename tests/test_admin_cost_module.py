"""Focused tests for the admin_cost module (Finding #7, task 7.5 migration).

The LLM cost/pricing handler logic now lives in handlers.admin_cost; the admin
monolith and bot.py import the cost functions from this module. Behavior is
unchanged.
"""

import os
import tempfile
import unittest

from config.keyboards import (
    admin_awaiting_inline_keyboard,
    admin_cost_keyboard,
    llm_cost_dashboard_keyboard,
    llm_cost_kind_keyboard,
    llm_cost_plan_keyboard,
    llm_cost_pricing_keyboard,
    llm_cost_status_keyboard,
)
from handlers import admin
from handlers import admin_cost
from services import db
from services.db import schema as db_schema

_COST_FUNCTIONS = (
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
)

_KEYBOARDS = {
    "admin_awaiting_inline_keyboard": admin_awaiting_inline_keyboard,
    "admin_cost_keyboard": admin_cost_keyboard,
    "llm_cost_dashboard_keyboard": llm_cost_dashboard_keyboard,
    "llm_cost_kind_keyboard": llm_cost_kind_keyboard,
    "llm_cost_plan_keyboard": llm_cost_plan_keyboard,
    "llm_cost_pricing_keyboard": llm_cost_pricing_keyboard,
    "llm_cost_status_keyboard": llm_cost_status_keyboard,
}


class TestAdminCostModule(unittest.TestCase):
    def test_defines_cost_functions(self):
        for name in _COST_FUNCTIONS:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(admin_cost, name)))

    def test_monolith_imports_cost_functions_from_module(self):
        for name in ("_show_llm_cost_dashboard", "_llm_pricing_text", "_llm_cost_set_state"):
            with self.subTest(name=name):
                self.assertIs(getattr(admin, name), getattr(admin_cost, name))

    def test_bot_llm_callback_reexported_through_monolith(self):
        self.assertIs(admin._handle_llm_callback, admin_cost._handle_llm_callback)

    def test_reexports_cost_keyboards_verbatim(self):
        for name, kbd in _KEYBOARDS.items():
            with self.subTest(name=name):
                self.assertIs(getattr(admin_cost, name), kbd)

    def test_all_is_explicit(self):
        expected = sorted(
            list(_COST_FUNCTIONS) + list(_KEYBOARDS.keys()),
            key=lambda s: s.lower(),
        )
        self.assertEqual(sorted(admin_cost.__all__, key=lambda s: s.lower()), expected)


class TestCostReportEmojiR8(unittest.TestCase):
    """R8 is global: the cost dashboard must follow the emoji dictionary.

    🟢/⚪ are ON/OFF toggles only and must never mark an outcome; success uses
    ✅, a billed failure is a hard error (❌), and a zero-cost failure is a
    warning (⚠️). 🔴/🟢/⚪ must not appear as outcome markers.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_status_icon_mapping(self):
        self.assertEqual(admin_cost._llm_cost_status_icon("success"), "✅")
        self.assertEqual(admin_cost._llm_cost_status_icon("failure_billed"), "❌")
        self.assertEqual(admin_cost._llm_cost_status_icon("failure_zero_cost"), "⚠️")
        # Unknown outcomes must not silently become a toggle emoji.
        self.assertEqual(admin_cost._llm_cost_status_icon("weird"), "❌")

    def test_report_text_uses_r8_emoji_and_no_toggle_markers(self):
        text = admin_cost._llm_cost_report_text(admin_cost._llm_cost_default_state())
        self.assertIn("✅ Success rate", text)
        self.assertIn("❌ Billed failure rate", text)
        # Outcome markers must not reuse the ON/OFF toggle emoji.
        self.assertNotIn("🟢", text)
        self.assertNotIn("⚪", text)
        self.assertNotIn("🔴", text)
        # Legend reflects the R8 mapping.
        self.assertIn("راهنما: ✅ = موفق | ❌ = خطای هزینه‌دار | ⚠️ = خطای بدون هزینه", text)


if __name__ == "__main__":
    unittest.main()
