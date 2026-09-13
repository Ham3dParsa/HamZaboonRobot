"""Focused seam tests for the services/db split (finding #3, REF2-T5).

These prove that the cost-tracking and preset-registry domains, now split into
their own modules, are still reachable byte-identically through the `services.db`
facade and via `from services.db import ...`, so `from services import db` call
sites (bot, handlers, scheduling, tools, tests) break nowhere.

REF2-T5 extends the same guarantee to the query_results, legacy_aux, and
backup leaves extracted from the facade body.
"""

import importlib
import unittest

from services import db
from services.db import cost_tracking, preset_registry, settings
from services.db import query_results, legacy_aux, backup


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
    "get_hourly_usage_many",
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
    "get_display_toggle_defaults",
    "get_llm_cost_profile",
    "get_setting",
    "set_bool_setting",
    "set_display_toggle_defaults",
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


QUERY_RESULTS_EXPORTS = [
    "create_query_result",
    "get_query_result",
    "find_unexpired_query",
    "find_unexpired_query_by_word",
    "mark_query_result_saved",
    "clear_query_result_saved",
    "update_query_result_fields",
    "cleanup_expired_query_results",
    "_query_result_expired",
    "_normalize_query_text",
    "_QUERY_RESULTS_CAP",
    "_enforce_query_results_cap",
]

LEGACY_AUX_EXPORTS = [
    "add_grammar_tip",
    "recent_grammar_tip_titles",
    "log_config_test",
    "_config_tests_prune_due",
    "prune_config_tests",
    "purge_grammar_tips",
]

BACKUP_EXPORTS = [
    "export_db_bytes",
    "import_db_bytes",
    "_RESTORE_CORE_TABLES",
    "_STORAGE_SQLITE_CODES",
    "_is_storage_error",
]


class QueryResultsSeamTest(unittest.TestCase):
    def test_facade_re_exports_all_query_results_names(self):
        for name in QUERY_RESULTS_EXPORTS:
            self.assertTrue(hasattr(db, name), f"db.{name} missing")
            self.assertIs(getattr(db, name), getattr(query_results, name))

    def test_direct_import_matches_facade(self):
        mod = importlib.import_module("services.db")
        for name in QUERY_RESULTS_EXPORTS:
            self.assertIs(getattr(mod, name), getattr(query_results, name))


class LegacyAuxSeamTest(unittest.TestCase):
    def test_facade_re_exports_all_legacy_aux_names(self):
        for name in LEGACY_AUX_EXPORTS:
            self.assertTrue(hasattr(db, name), f"db.{name} missing")
            self.assertIs(getattr(db, name), getattr(legacy_aux, name))

    def test_direct_import_matches_facade(self):
        mod = importlib.import_module("services.db")
        for name in LEGACY_AUX_EXPORTS:
            self.assertIs(getattr(mod, name), getattr(legacy_aux, name))


class BackupSeamTest(unittest.TestCase):
    def test_facade_re_exports_all_backup_names(self):
        for name in BACKUP_EXPORTS:
            self.assertTrue(hasattr(db, name), f"db.{name} missing")
            self.assertIs(getattr(db, name), getattr(backup, name))

    def test_direct_import_matches_facade(self):
        mod = importlib.import_module("services.db")
        for name in BACKUP_EXPORTS:
            self.assertIs(getattr(mod, name), getattr(backup, name))


if __name__ == "__main__":
    unittest.main()
