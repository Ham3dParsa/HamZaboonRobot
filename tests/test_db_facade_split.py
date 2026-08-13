"""Focused seam tests for the services/db split (finding #3).

These prove that the cost-tracking and preset-registry domains, now split into
their own modules, are still reachable byte-identically through the `services.db`
facade and via `from services.db import ...`, so `from services import db` call
sites (bot, handlers, scheduling, tools, tests) break nowhere.
"""

import importlib
import unittest

from services import db
from services.db import cost_tracking, preset_registry, settings


COST_TRACKING_EXPORTS = [
    "add_llm_request",
    "breakdown_llm_requests",
    "delete_llm_requests",
    "recent_llm_requests",
    "summarize_llm_requests",
]

PRESET_REGISTRY_EXPORTS = [
    "activate_preset",
    "clear_group_label",
    "clone_preset",
    "delete_preset",
    "get_active_preset",
    "get_active_preset_name",
    "get_enabled_presets_ordered",
    "get_fallback_chain_presets",
    "get_fallback_status",
    "get_group_labels",
    "get_hourly_usage",
    "get_preset",
    "get_preset_cost",
    "get_presets",
    "increment_consecutive_failures",
    "increment_hourly_usage",
    "reindex_preset_priority",
    "rename_group_label",
    "reset_consecutive_failures",
    "set_fallback_active",
    "set_preset",
    "set_preset_api_key_batch",
    "set_preset_emergency",
    "set_preset_enabled",
    "set_preset_group_label_batch",
    "set_preset_priority",
]

SETTINGS_EXPORTS = [
    "get_bool_setting",
    "get_llm_cost_profile",
    "get_phonetic_display_settings",
    "get_setting",
    "set_bool_setting",
    "set_llm_cost_profile",
    "set_setting",
]


class CostTrackingSeamTest(unittest.TestCase):
    def test_facade_re_exports_all_cost_tracking_names(self):
        for name in COST_TRACKING_EXPORTS:
            self.assertTrue(hasattr(db, name), f"db.{name} missing")
            self.assertIs(getattr(db, name), getattr(cost_tracking, name))

    def test_direct_import_matches_facade(self):
        mod = importlib.import_module("services.db")
        for name in COST_TRACKING_EXPORTS:
            self.assertIs(getattr(mod, name), getattr(cost_tracking, name))


class PresetRegistrySeamTest(unittest.TestCase):
    def test_facade_re_exports_all_preset_registry_names(self):
        for name in PRESET_REGISTRY_EXPORTS:
            self.assertTrue(hasattr(db, name), f"db.{name} missing")
            self.assertIs(getattr(db, name), getattr(preset_registry, name))

    def test_direct_import_matches_facade(self):
        mod = importlib.import_module("services.db")
        for name in PRESET_REGISTRY_EXPORTS:
            self.assertIs(getattr(mod, name), getattr(preset_registry, name))


class SettingsSeamTest(unittest.TestCase):
    def test_facade_re_exports_all_settings_names(self):
        for name in SETTINGS_EXPORTS:
            self.assertTrue(hasattr(db, name), f"db.{name} missing")
            self.assertIs(getattr(db, name), getattr(settings, name))

    def test_direct_import_matches_facade(self):
        mod = importlib.import_module("services.db")
        for name in SETTINGS_EXPORTS:
            self.assertIs(getattr(mod, name), getattr(settings, name))


if __name__ == "__main__":
    unittest.main()
