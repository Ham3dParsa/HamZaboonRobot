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
        # Exact dotted-key set — only staged fields carry dots now.
        self.assertEqual(self._dotted_keys(kb), {"model", "api_key"})

    def test_dirty_name_renders_single_prefix(self):
        """Dirty `name` gets exactly one ✏️ from the dirty branch (T7/U2)."""
        kb = ai_preset_edit_keyboard(
            "p",
            [FieldDiff(field="name", label="Preset Name", old="a", new="b")],
        )
        name_row = next(t for t in self._texts(kb) if "نام پریست" in t)
        self.assertEqual(name_row, "✏️ 🆔 نام پریست")
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
        # No dirty dots; the `name` row is now a plain label.
        self.assertEqual(self._dotted_keys(kb), set())

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
        self.assertEqual(self._dotted_keys(kb), set())
        self.assertIn("💾 ذخیره (۱)", self._texts(kb))

    def test_non_field_diff_items_raise_type_error(self):
        with self.assertRaises(TypeError):
            ai_preset_edit_keyboard("p", ["model"])  # type: ignore[list-item]
        with self.assertRaises(TypeError):
            ai_preset_edit_keyboard("p", {"model": "x"})  # type: ignore[arg-type]


class AiPresetEditKeyboardPairedLayoutTests(unittest.TestCase):
    """T7 (U1/U2) — paired 2-per-row layout + 🆔 name icon.

    TEXT/layout only: every ``callback_data`` byte-identical to the pre-T7
    shape (asserted as a set — row order follows the U1 pairs, not the old
    flat order). No new prefixes (``tests/test_wiring.py`` stays green).
    """

    # U1 pairs in order; api_key solo full-width.
    EXPECTED_PAIRS = [
        ("base_url", "model"),
        ("api_key",),
        ("daily_batch_size", "max_concurrency"),
        ("max_rpm", "timeout_seconds"),
        ("temperature", "max_output_tokens"),
        ("max_tpm", "max_daily_req"),
        ("input_cost_per_million", "output_cost_per_million"),
        ("priority", "in_fallback_chain"),
        ("is_emergency", "reasoning_effort"),
        ("name", "group_label"),
    ]

    # T7-shortened half-width labels (were 20–26 chars, overflowed a half-row).
    EXPECTED_SHORT_LABELS = {
        "🔢 TPM",
        "📊 سقف روزانه",
        "💵 ورودی ($/1M)",
        "💵 خروجی ($/1M)",
        "🔢 اولویت فال‌بک",
        "⛓️ عضو فال‌بک",
    }

    def _field_key_rows(self, kb) -> list[list[str]]:
        """Field keys per keyboard row (edit_field buttons only, in row order)."""
        from services.utils.callback_codec import _FIELD_ALIAS_REV

        key_rows = []
        for row in kb.inline_keyboard:
            keys = []
            for b in row:
                parts = b.callback_data.split(":")
                if parts[:3] == ["admin", "ai_preset", "edit_field"]:
                    keys.append(_FIELD_ALIAS_REV[parts[-1]])
            if keys:
                key_rows.append(keys)
        return key_rows

    def _row_of(self, kb, key: str):
        for row in kb.inline_keyboard:
            keys = []
            for b in row:
                parts = b.callback_data.split(":")
                if parts[:3] == ["admin", "ai_preset", "edit_field"]:
                    from services.utils.callback_codec import _FIELD_ALIAS_REV

                    keys.append(_FIELD_ALIAS_REV[parts[-1]])
            if key in keys:
                return keys
        self.fail(f"{key} not found on keyboard")

    def test_field_pairs_share_rows(self):
        kb = ai_preset_edit_keyboard("p")
        self.assertEqual(
            self._field_key_rows(kb),
            [list(pair) for pair in self.EXPECTED_PAIRS],
        )

    def test_api_key_solo_full_width(self):
        self.assertEqual(self._row_of(ai_preset_edit_keyboard("p"), "api_key"), ["api_key"])

    def test_all_pairs_share_rows_when_dirty(self):
        """Pairing is structural — dirty dots must not split rows."""
        kb = ai_preset_edit_keyboard(
            "p",
            [
                FieldDiff(field="model", label="Model", old="a", new="b"),
                FieldDiff(field="priority", label="Priority", old="0", new="1"),
            ],
        )
        self.assertEqual(
            self._field_key_rows(kb),
            [list(pair) for pair in self.EXPECTED_PAIRS],
        )

    def test_name_clean_carries_id_icon(self):
        kb = ai_preset_edit_keyboard("p")
        name_text = next(
            b.text
            for row in kb.inline_keyboard
            for b in row
            if b.callback_data.endswith(":n")
        )
        self.assertEqual(name_text, "🆔 نام پریست")

    def test_name_dirty_carries_id_icon_with_single_pencil(self):
        kb = ai_preset_edit_keyboard(
            "p",
            [FieldDiff(field="name", label="Preset Name", old="a", new="b")],
        )
        name_text = next(
            b.text
            for row in kb.inline_keyboard
            for b in row
            if b.callback_data.endswith(":n")
        )
        self.assertEqual(name_text, "✏️ 🆔 نام پریست")
        self.assertEqual(name_text.count("✏️"), 1)

    def test_short_labels_fit_half_width(self):
        """Renamed labels pinned; every clean field button ≤ 16 chars.

        Pre-T7 the six renamed labels were 20–26 chars — demonstrably too
        wide for a half-row next to a sibling button (longest surviving
        label is 16 chars: 🛡️ پریست اضطراری).
        """
        kb = ai_preset_edit_keyboard("p")
        texts = [b.text for row in kb.inline_keyboard for b in row]
        for label in self.EXPECTED_SHORT_LABELS:
            self.assertIn(label, texts)
        from services.utils.callback_codec import _FIELD_ALIAS_REV

        for row in kb.inline_keyboard:
            for b in row:
                parts = b.callback_data.split(":")
                if parts[:3] == ["admin", "ai_preset", "edit_field"]:
                    self.assertLessEqual(
                        len(b.text), 16, f"{_FIELD_ALIAS_REV[parts[-1]]}: {b.text!r}"
                    )

    def test_action_rows_paired(self):
        kb = ai_preset_edit_keyboard("p")
        text_rows = [[b.text for b in row] for row in kb.inline_keyboard]
        cb_rows = [[b.callback_data for b in row] for row in kb.inline_keyboard]
        # [save|discard] share a row, save first.
        save_row = next(r for r, cbs in zip(text_rows, cb_rows) if any("save:" in c for c in cbs))
        self.assertEqual(len(save_row), 2)
        self.assertTrue(save_row[0].startswith("💾"))
        self.assertTrue(save_row[1].startswith("🗑️"))
        # [cancel|close] share a row.
        close_row = next(r for r, cbs in zip(text_rows, cb_rows) if "admin:close" in cbs)
        self.assertEqual(len(close_row), 2)
        self.assertEqual(close_row[0], "↩️ انصراف")
        self.assertEqual(close_row[1], "❌ بستن")
        # Full-edit solo.
        full_row = next(r for r, cbs in zip(text_rows, cb_rows) if any("full_edit:" in c for c in cbs))
        self.assertEqual(full_row, ["✏️ ویرایش کامل"])

    def test_detach_row_solo_conditional(self):
        grouped = ai_preset_edit_keyboard("p", [], has_group=True)
        detach_rows = [
            row for row in grouped.inline_keyboard
            if any("detach_group" in b.callback_data for b in row)
        ]
        self.assertEqual(len(detach_rows), 1)
        self.assertEqual(len(detach_rows[0]), 1)

    def test_callback_data_set_unchanged(self):
        """Every callback_data byte-identical to the pre-T7 shape (as a set).

        Row order follows the U1 pairs (fields reordered vs the old flat
        list), but no callback string itself changed.
        """
        from services.utils.callback_codec import alias_field, preset_token

        ref = preset_token("p")
        field_keys = [k for pair in self.EXPECTED_PAIRS for k in pair]
        self.assertEqual(len(field_keys), 19)
        expected_fields = {
            f"admin:ai_preset:edit_field:{ref}:{alias_field(k)}" for k in field_keys
        }
        expected_actions = {
            f"admin:ai_preset:detach_group:{ref}",
            f"admin:ai_preset:full_edit:{ref}",
            f"admin:ai_preset:save:{ref}",
            f"admin:ai_preset:discard_all:{ref}",
            f"admin:ai_preset:view:{ref}",
            "admin:close",
        }
        kb = ai_preset_edit_keyboard("p", [], has_group=True)
        actual = {b.callback_data for row in kb.inline_keyboard for b in row}
        self.assertEqual(actual, expected_fields | expected_actions)
        # Without group: same set minus detach.
        kb_plain = ai_preset_edit_keyboard("p", [], has_group=False)
        actual_plain = {b.callback_data for row in kb_plain.inline_keyboard for b in row}
        self.assertEqual(actual_plain, expected_fields | (expected_actions - {f"admin:ai_preset:detach_group:{ref}"}))

    def test_no_new_callback_prefixes(self):
        """All callbacks keep the pre-T7 prefixes (wiring untouched)."""
        kb = ai_preset_edit_keyboard("p", [], has_group=True)
        for row in kb.inline_keyboard:
            for b in row:
                self.assertTrue(
                    b.callback_data == "admin:close"
                    or b.callback_data.startswith("admin:ai_preset:"),
                    f"new prefix: {b.callback_data!r}",
                )
