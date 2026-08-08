"""Focused tests for the admin_ai expand module (Finding #7, task 7.4).

Task 7.4 establishes the AI domain seam by re-exporting the standalone AI
symbols verbatim, with no behavior change and no routing changes yet.
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

_KEYBOARDS = {
    "ai_settings_keyboard": ai_settings_keyboard,
    "ai_presets_list_keyboard": ai_presets_list_keyboard,
    "ai_preset_view_keyboard": ai_preset_view_keyboard,
    "ai_preset_edit_keyboard": ai_preset_edit_keyboard,
    "ai_fallback_keyboard": ai_fallback_keyboard,
    "fallback_chain_keyboard": fallback_chain_keyboard,
}


class TestAdminAiModule(unittest.TestCase):
    def test_reexports_ai_functions_verbatim(self):
        for name in _FUNCTIONS:
            with self.subTest(name=name):
                self.assertIs(getattr(admin_ai, name), getattr(admin, name))

    def test_reexports_ai_keyboards_verbatim(self):
        for name, kbd in _KEYBOARDS.items():
            with self.subTest(name=name):
                self.assertIs(getattr(admin_ai, name), kbd)

    def test_all_is_explicit(self):
        expected = sorted(
            list(_FUNCTIONS) + list(_KEYBOARDS.keys()),
            key=lambda s: s.lower(),
        )
        self.assertEqual(sorted(admin_ai.__all__, key=lambda s: s.lower()), expected)


if __name__ == "__main__":
    unittest.main()
