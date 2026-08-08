"""Focused tests for the admin_ai module (Finding #7, task 7.5 AI migration).

After the migrate step, ``handlers.admin_ai`` DEFINES the standalone AI/preset/
fallback/custom-test handler functions that previously lived in the ``admin``
monolith. ``handlers.admin`` imports them back and ``bot.py`` continues to import
``_edit_ai_preset`` via ``handlers.admin``. These tests verify the migrated
ownership and the re-export direction, with no behavior change.
"""

import unittest

from config.keyboards import (
    ai_fallback_keyboard,
    ai_preset_edit_keyboard,
    ai_preset_view_keyboard,
    ai_presets_list_keyboard,
    ai_settings_keyboard,
    fallback_chain_keyboard,
)
from handlers import admin
from handlers import admin_ai

_FUNCTIONS = (
    "_activate_ai_preset",
    "_add_ai_preset",
    "_confirm_save_preset",
    "_custom_test_step_goal",
    "_custom_test_step_lang",
    "_custom_test_step_level",
    "_custom_test_step_preset",
    "_custom_test_step_target",
    "_delete_ai_preset",
    "_detect_key_groups",
    "_discard_all_preset_changes",
    "_edit_ai_preset",
    "_edit_ai_preset_field",
    "_handle_ai_fallback",
    "_handle_ai_preset_field_input",
    "_handle_ai_preset_new_name",
    "_handle_ai_text_input",
    "handle_ai_callback",
    "_handle_custom_test_wizard",
    "_handle_fallback_rank",
    "_handle_full_edit_cancel",
    "_handle_full_edit_input",
    "_handle_full_edit_next",
    "_handle_full_edit_pick_group",
    "_handle_full_edit_save",
    "_handle_full_edit_skip",
    "_handle_group_batch_key",
    "_handle_group_manager_clear",
    "_handle_group_manager_rename",
    "_handle_group_set_label",
    "_handle_group_view",
    "_key_hash",
    "_run_custom_test",
    "_save_ai_preset",
    "_show_ai_fallback",
    "_show_ai_preset_view",
    "_show_ai_presets",
    "_show_ai_settings",
    "_show_fallback_chain",
    "_show_fallback_preset_picker",
    "_show_fallback_usage_details",
    "_show_group_manager",
    "_show_grouped_presets",
    "_show_help_fallback_chain",
    "_show_help_presets",
    "_show_linear_presets",
    "_show_wizard_field",
    "_show_wizard_summary",
    "_start_custom_test_wizard",
    "_start_full_edit_wizard",
    "_test_ai_connection",
    "_toggle_preset_view_mode",
    "_validate_wizard_value",
)

# The subset of AI functions admin.py still dispatches on (and _edit_ai_preset,
# which bot.py imports through handlers.admin).
_ADMIN_REEXPORTS = (
    "_show_ai_settings",
    "_show_ai_presets",
    "_show_ai_preset_view",
    "_edit_ai_preset",
    "_edit_ai_preset_field",
    "_start_full_edit_wizard",
    "_confirm_save_preset",
    "_save_ai_preset",
    "_discard_all_preset_changes",
    "_delete_ai_preset",
    "_add_ai_preset",
    "_toggle_preset_view_mode",
    "_handle_group_view",
    "_handle_group_batch_key",
    "_handle_group_set_label",
    "_show_group_manager",
    "_handle_group_manager_rename",
    "_handle_group_manager_clear",
    "_test_ai_connection",
    "_start_custom_test_wizard",
    "_handle_custom_test_wizard",
    "_show_ai_fallback",
    "_handle_ai_fallback",
    "_handle_fallback_rank",
    "_show_grouped_presets",
    "_handle_ai_preset_new_name",
    "_handle_ai_preset_field_input",
    "_handle_ai_text_input",
    "handle_ai_callback",
)


class TestAdminAiModule(unittest.TestCase):
    def test_defines_ai_functions(self):
        for name in _FUNCTIONS:
            with self.subTest(name=name):
                self.assertTrue(hasattr(admin_ai, name), f"admin_ai.{name} missing")

    def test_admin_reexports_ai_functions_verbatim(self):
        for name in _ADMIN_REEXPORTS:
            with self.subTest(name=name):
                self.assertIs(getattr(admin, name), getattr(admin_ai, name))

    def test_edit_ai_preset_resolves_through_admin(self):
        self.assertIs(admin._edit_ai_preset, admin_ai._edit_ai_preset)


if __name__ == "__main__":
    unittest.main()
