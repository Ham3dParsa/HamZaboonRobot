"""Tests for the canonical settings-key registry (J0.2 / SEAMS 'settings keys').

Mirrors test_catalog.py: every stable key in SETTINGS_KEYS resolves through
settings_key(), pattern keys resolve only for the canonical card types, unknown
keys (including pattern-shaped ones) fail fast, the folded validate_catalog()
chain passes, and the consumer in settings.py uses the registry key.
"""

import unittest

from config.catalog import (
    DISPLAY_TOGGLE_DEFAULTS,
    SETTINGS_KEYS,
    settings_key,
    validate_catalog,
    validate_settings_keys,
)
from services.db import settings as settings_module


class SettingsKeyRegistryTest(unittest.TestCase):
    def test_every_stable_key_resolves(self):
        for key in SETTINGS_KEYS:
            if SETTINGS_KEYS[key].get("pattern"):
                continue
            with self.subTest(key=key):
                meta = settings_key(key)
                self.assertEqual(meta["key"], key)
                self.assertIn(meta["type"], {"str", "bool", "int", "float", "json"})

    def test_display_toggle_defaults_entry(self):
        meta = settings_key("display_toggle_defaults")
        self.assertEqual(meta["key"], "display_toggle_defaults")
        self.assertEqual(meta["type"], "json")
        self.assertIs(meta["default"], DISPLAY_TOGGLE_DEFAULTS)

    def test_pattern_keys_resolve_for_known_card_types(self):
        for card_type in ("first_exposure", "review"):
            for suffix in ("mode", "mode_gate"):
                key = f"{card_type}_{suffix}"
                with self.subTest(key=key):
                    meta = settings_key(key)
                    self.assertEqual(meta["card_type"], card_type)
                    self.assertEqual(meta["key"], key)
                    expected = "staged" if suffix == "mode" else "premium"
                    self.assertEqual(meta["default"], expected)

    def test_unknown_key_raises_keyerror(self):
        # Non-pattern unknown key.
        with self.assertRaises(KeyError):
            settings_key("this_is_not_a_real_key")
        # Pattern-shaped unknown (not a canonical card type) must also fail fast.
        with self.assertRaises(KeyError):
            settings_key("foo_mode")
        with self.assertRaises(KeyError):
            settings_key("x_mode_gate")

    def test_validate_settings_keys_passes(self):
        # Structural validation must not raise.
        validate_settings_keys()

    def test_validate_catalog_chain_passes(self):
        # settings_key validation is folded into the catalog validation chain.
        validate_catalog()

    def test_consumer_key_matches_registry(self):
        # The settings.py accessor sources its key from the registry, so the
        # literal string stays canonical and single-sourced.
        self.assertEqual(
            settings_module.DISPLAY_TOGGLE_DEFAULTS_KEY,
            settings_key("display_toggle_defaults")["key"],
        )
        self.assertEqual(settings_module.DISPLAY_TOGGLE_DEFAULTS_KEY, "display_toggle_defaults")


if __name__ == "__main__":
    unittest.main()
