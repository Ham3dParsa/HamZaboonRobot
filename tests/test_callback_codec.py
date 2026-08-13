"""Tests for the callback-data encoding scheme (R3: 64-byte limit fix).

Verifies that every admin AI-preset callback stays under Telegram's 64-byte
callback_data limit, and that the codec round-trips preset names / field names /
group labels with backward-compatible fallback.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from config.keyboards import (
    ai_preset_edit_keyboard,
    ai_preset_view_keyboard,
    ai_presets_list_keyboard,
    fallback_chain_keyboard,
)
from services import db
from services.db import schema as db_schema
from services.utils import callback_codec


def _collect_callback_data(markup) -> list[str]:
    collected: list[str] = []
    for row in markup.inline_keyboard:
        for btn in row:
            if getattr(btn, "callback_data", None):
                collected.append(btn.callback_data)
    return collected


class AiPresetCallbackByteLimitTest(unittest.TestCase):
    """Every emitted AI-preset callback must be <= 64 bytes."""

    # A long custom preset name (within the 60-char cap) that previously overflowed.
    LONG_NAME = "my_very_long_custom_preset_name_for_testing_overflow"

    def _preset(self, name: str) -> dict:
        return {"name": name, "model": "m", "base_url": "u"}

    def test_edit_field_callbacks_under_64(self):
        preset = self._preset(self.LONG_NAME)
        markup = ai_preset_edit_keyboard(self.LONG_NAME, preset)
        for cb in _collect_callback_data(markup):
            self.assertLessEqual(
                len(cb.encode("utf-8")),
                64,
                f"callback_data exceeds 64 bytes: {cb}",
            )

    def test_list_callbacks_under_64(self):
        presets = [self._preset(self.LONG_NAME)]
        markup = ai_presets_list_keyboard(presets, self.LONG_NAME)
        for cb in _collect_callback_data(markup):
            self.assertLessEqual(len(cb.encode("utf-8")), 64, cb)

    def test_view_callbacks_under_64(self):
        markup = ai_preset_view_keyboard(self._preset(self.LONG_NAME), "other")
        for cb in _collect_callback_data(markup):
            self.assertLessEqual(len(cb.encode("utf-8")), 64, cb)

    def test_fallback_chain_callbacks_under_64(self):
        chain = [self._preset(self.LONG_NAME), self._preset("short")]
        markup = fallback_chain_keyboard(chain)
        for cb in _collect_callback_data(markup):
            self.assertLessEqual(len(cb.encode("utf-8")), 64, cb)


class _ScratchDbTestCase(unittest.TestCase):
    """Seed a scratch DB so hash-resolution scans find the presets/labels."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db = db.DB_PATH
        self.old_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db.init_db()
        for p in db.get_presets():
            db.delete_preset(p["name"])
        db.set_preset(name="my_preset", base_url="https://x", model="m")
        db.set_preset(name="g", base_url="https://x", model="m", group_label="پشتیبان رایگان")

    def tearDown(self):
        db.DB_PATH = self.old_db
        db_schema.DB_PATH = self.old_schema
        self.tempdir.cleanup()


class CallbackCodecRoundTripTest(_ScratchDbTestCase):
    """The codec must round-trip identifiers and fall back for legacy values."""

    def test_preset_token_round_trip(self):
        token = callback_codec.preset_token("my_preset")
        self.assertEqual(len(token), 12)
        self.assertEqual(callback_codec.resolve_preset_token(token), "my_preset")

    def test_preset_token_returns_none_for_unknown(self):
        self.assertIsNone(callback_codec.resolve_preset_token("000000000000"))

    def test_label_token_round_trip(self):
        token = callback_codec.label_token("پشتیبان رایگان")
        self.assertEqual(len(token), 12)
        self.assertEqual(callback_codec.resolve_label_token(token), "پشتیبان رایگان")

    def test_field_alias_round_trip(self):
        self.assertEqual(callback_codec.resolve_field_alias("oc"), "output_cost_per_million")
        self.assertEqual(callback_codec.resolve_field_alias("ic"), "input_cost_per_million")
        self.assertEqual(callback_codec.resolve_field_alias("mo"), "max_output_tokens")

    def test_field_alias_unknown_returns_raw(self):
        self.assertEqual(callback_codec.resolve_field_alias("base_url"), "base_url")

    def test_all_field_aliases_are_unique(self):
        aliases = list(callback_codec._FIELD_ALIAS.values())
        self.assertEqual(len(aliases), len(set(aliases)), "field aliases must be unique")


if __name__ == "__main__":
    unittest.main()