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
from services.utils.confirm_summary import FieldDiff


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


class AiPresetEditKeyboardDiffsTests(unittest.TestCase):
    """T6 (D3) — keyboard as thin adapter over diffs + has_group.

    Synthetic FieldDiffs only, no DB dicts. Callback_data strings pinned
    byte-identical to the pre-T6 shape.
    """

    def _texts(self, kb) -> list[str]:
        return [b.text for row in kb.inline_keyboard for b in row]

    def _field_rows(self, kb) -> list[tuple[str, str]]:
        """(field key, text) for the per-field quick-edit rows only."""
        from services.utils.callback_codec import _FIELD_ALIAS_REV

        rows = []
        for row in kb.inline_keyboard:
            for b in row:
                parts = b.callback_data.split(":")
                if parts[:3] == ["admin", "ai_preset", "edit_field"]:
                    rows.append((_FIELD_ALIAS_REV[parts[-1]], b.text))
        return rows

    def _dotted_keys(self, kb) -> set[str]:
        return {key for key, text in self._field_rows(kb) if text.startswith("✏️")}

    def _callbacks(self, kb) -> list[str]:
        return [b.callback_data for row in kb.inline_keyboard for b in row]

    def test_dirty_dot_follows_field_identity_not_labels(self):
        """Dots mark FieldDiff.field keys even though button labels (IBTN_*)
        differ from diff labels (FIELD_LABELS)."""
        kb = ai_preset_edit_keyboard(
            "p",
            [
                FieldDiff(field="model", label="Model", old="a", new="b"),
                FieldDiff(field="api_key", label="API Key", old="••••1", new="••••2"),
            ],
        )
        texts = self._texts(kb)
        model_row = next(t for t in texts if "🤖 Model" in t)
        key_row = next(t for t in texts if "API Key" in t)
        base_row = next(t for t in texts if "Base URL" in t)
        self.assertTrue(model_row.startswith("✏️"))
        self.assertTrue(key_row.startswith("✏️"))
        self.assertFalse(base_row.startswith("✏️"))
        # Exact dotted-key set (plus the static ✏️ نام پریست label quirk).
        self.assertEqual(self._dotted_keys(kb), {"model", "api_key", "name"})

    def test_dirty_name_renders_single_prefix(self):
        """Dirty `name` must not double the static ✏️ in IBTN_FIELD_NAME."""
        kb = ai_preset_edit_keyboard(
            "p",
            [FieldDiff(field="name", label="Preset Name", old="a", new="b")],
        )
        name_row = next(t for t in self._texts(kb) if "نام پریست" in t)
        self.assertEqual(name_row.count("✏️"), 1)

    def test_save_discard_counts_use_persian_digits(self):
        kb = ai_preset_edit_keyboard(
            "p",
            [
                FieldDiff(field="model", label="Model", old="a", new="b"),
                FieldDiff(field="temperature", label="Temperature", old="0.6", new="0.9"),
            ],
        )
        texts = self._texts(kb)
        self.assertIn("💾 ذخیره (۲)", texts)
        self.assertIn("🗑️ دور ریختن همه (۲)", texts)

    def test_empty_diffs_render_zero_counts_and_no_dots(self):
        kb = ai_preset_edit_keyboard("p")
        texts = self._texts(kb)
        self.assertIn("💾 ذخیره (۰)", texts)
        self.assertIn("🗑️ دور ریختن همه (۰)", texts)
        # No dirty dots; the `name` row keeps its static ✏️ نام پریست label.
        self.assertEqual(self._dotted_keys(kb), {"name"})

    def test_detach_row_follows_has_group_flag(self):
        grouped = ai_preset_edit_keyboard("p", [], has_group=True)
        ungrouped = ai_preset_edit_keyboard("p", [], has_group=False)
        grouped_callbacks = self._callbacks(grouped)
        ungrouped_callbacks = self._callbacks(ungrouped)
        self.assertTrue(any("detach_group" in c for c in grouped_callbacks))
        self.assertFalse(any("detach_group" in c for c in ungrouped_callbacks))

    def test_callback_data_shape_unchanged(self):
        from services.utils.callback_codec import preset_token

        ref = preset_token("p")
        kb = ai_preset_edit_keyboard("p", [FieldDiff(field="model", label="Model", old="a", new="b")], has_group=True)
        callbacks = self._callbacks(kb)
        self.assertIn(f"admin:ai_preset:save:{ref}", callbacks)
        self.assertIn(f"admin:ai_preset:discard_all:{ref}", callbacks)
        self.assertIn(f"admin:ai_preset:detach_group:{ref}", callbacks)
        self.assertIn(f"admin:ai_preset:full_edit:{ref}", callbacks)
        self.assertIn(f"admin:ai_preset:view:{ref}", callbacks)
        self.assertIn("admin:close", callbacks)

    def test_unknown_field_identity_marks_nothing(self):
        kb = ai_preset_edit_keyboard("p", [FieldDiff(label="?", old="a", new="b")])
        self.assertEqual(self._dotted_keys(kb), {"name"})
        self.assertIn("💾 ذخیره (۱)", self._texts(kb))

    def test_non_field_diff_items_raise_type_error(self):
        with self.assertRaises(TypeError):
            ai_preset_edit_keyboard("p", ["model"])  # type: ignore[list-item]
        with self.assertRaises(TypeError):
            ai_preset_edit_keyboard("p", {"model": "x"})  # type: ignore[arg-type]
