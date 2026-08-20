"""F1/R1 — alignment test for the AI preset quick-edit keyboard.

The audit's headline defect: ``priority`` lived in the canonical field registry
(``services/ai/preset_fields.py``), the full-edit wizard (``handlers/admin_ai.py``
``WIZARD_FIELDS``) and the callback codec (``services/utils/callback_codec.py``
``_FIELD_ALIAS``), but was missing from ``ai_preset_edit_keyboard`` — so a single
preset's fallback order could not be edited without the full wizard.

This test locks that every field exposed on the quick-edit keyboard is a
canonical preset field with a callback alias, and that ``priority`` is among them
so the gap cannot silently recur.
"""

import unittest

from config.keyboards import ai_preset_edit_keyboard
from services.ai.preset_fields import PRESET_FIELDS
from services.utils.callback_codec import _FIELD_ALIAS, _FIELD_ALIAS_REV, alias_field


class AiPresetEditKeyboardAlignmentTests(unittest.TestCase):
    def _edit_field_keys(self) -> list[str]:
        kb = ai_preset_edit_keyboard("testpreset")
        keys: list[str] = []
        for row in kb.inline_keyboard:
            for btn in row:
                parts = btn.callback_data.split(":")
                # Only the per-field quick-edit buttons carry the edit_field
                # prefix; the keyboard also has full_edit/save/view buttons.
                if parts[:3] != ["admin", "ai_preset", "edit_field"]:
                    continue
                alias = parts[-1]
                self.assertIn(alias, _FIELD_ALIAS_REV, f"alias {alias!r} has no field")
                keys.append(_FIELD_ALIAS_REV[alias])
        return keys

    def test_priority_is_editable_from_keyboard(self):
        self.assertIn("priority", self._edit_field_keys())

    def test_every_keyboard_field_is_canonical_and_codec_aligned(self):
        keys = self._edit_field_keys()
        self.assertTrue(keys, "keyboard exposes no editable fields")
        for key in keys:
            self.assertIn(key, PRESET_FIELDS, f"{key} is not a canonical preset field")
            self.assertEqual(alias_field(key), _FIELD_ALIAS[key])
