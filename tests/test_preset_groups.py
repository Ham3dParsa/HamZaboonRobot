"""Tests for Phase 01 of the DB-driven preset keys feature (spec #278).

Covers the additive `preset_groups` table, the group-aware `resolve_preset_key`
seam (own key > group key > empty), and the group CRUD / label-consistency
guarantees. Backward compatibility is a hard gate: any preset that already has
its own key must resolve identically whether or not a group key exists.
"""

import os
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema
from services.db import preset_registry
from services.ai import ai_presets


class _ScratchDbTestCase(unittest.TestCase):
    """Isolate each test against its own scratch SQLite DB."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db_module.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db_module.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path

    def tearDown(self):
        db_module.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()


class PresetGroupsTableTest(_ScratchDbTestCase):
    def test_table_exists_and_is_empty_after_init(self):
        db_module.init_db()
        with db_module.get_conn() as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM preset_groups").fetchone()["c"]
        self.assertEqual(n, 0)


class ResolvePresetKeyTest(_ScratchDbTestCase):
    def setUp(self):
        super().setUp()
        db_module.init_db()
        os.environ["HZ_OWN_KEY"] = "own-secret"
        os.environ["HZ_GROUP_KEY"] = "group-secret"
        self.addCleanup(os.environ.pop, "HZ_OWN_KEY", None)
        self.addCleanup(os.environ.pop, "HZ_GROUP_KEY", None)

    def _seed(self, presets, group_keys=None):
        for name, api_key, group_label in presets:
            preset_registry.set_preset(
                name=name, api_key=api_key, group_label=group_label
            )
        for label, key in (group_keys or {}).items():
            preset_registry.set_group_key(label, key)

    def test_own_key_precedes_group_key(self):
        self._seed([("p1", "$HZ_OWN_KEY", "g")], {"g": "$HZ_GROUP_KEY"})
        preset = preset_registry.get_preset("p1")
        self.assertEqual(preset_registry.resolve_preset_key(preset), "own-secret")

    def test_group_key_used_when_own_empty(self):
        self._seed([("p1", "", "g")], {"g": "$HZ_GROUP_KEY"})
        preset = preset_registry.get_preset("p1")
        self.assertEqual(preset_registry.resolve_preset_key(preset), "group-secret")

    def test_group_key_literal_resolves(self):
        self._seed([("p1", "", "g")], {"g": "sk-group-literal"})
        preset = preset_registry.get_preset("p1")
        self.assertEqual(preset_registry.resolve_preset_key(preset), "sk-group-literal")

    def test_no_group_key_returns_empty(self):
        self._seed([("p1", "", "g")], {})
        preset = preset_registry.get_preset("p1")
        self.assertEqual(preset_registry.resolve_preset_key(preset), "")

    def test_own_literal_key_resolves(self):
        literal = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
        self._seed([("p1", literal, "")])
        preset = preset_registry.get_preset("p1")
        self.assertEqual(preset_registry.resolve_preset_key(preset), literal)


class GroupCrdTest(_ScratchDbTestCase):
    def setUp(self):
        super().setUp()
        db_module.init_db()

    def test_set_get_delete_group_key(self):
        self.assertIsNone(preset_registry.get_group_key("g"))
        preset_registry.set_group_key("g", "$HZ_KEY")
        self.assertEqual(preset_registry.get_group_key("g"), "$HZ_KEY")
        preset_registry.delete_group_key("g")
        self.assertIsNone(preset_registry.get_group_key("g"))

    def test_rename_group_label_updates_preset_groups(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="old")
        preset_registry.set_group_key("old", "$HZ_KEY")
        preset_registry.rename_group_label("old", "new")
        self.assertIsNone(preset_registry.get_group_key("old"))
        self.assertEqual(preset_registry.get_group_key("new"), "$HZ_KEY")

    def test_self_rename_preserves_group_key(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="g")
        preset_registry.set_group_key("g", "$HZ_KEY")
        preset_registry.rename_group_label("g", "g")
        self.assertEqual(preset_registry.get_group_key("g"), "$HZ_KEY")

    def test_rename_into_existing_group_keeps_target_key(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="old")
        preset_registry.set_preset(name="p2", api_key="", group_label="new")
        preset_registry.set_group_key("old", "$HZ_OLD_KEY")
        preset_registry.set_group_key("new", "$HZ_NEW_KEY")
        preset_registry.rename_group_label("old", "new")
        self.assertIsNone(preset_registry.get_group_key("old"))
        self.assertEqual(preset_registry.get_group_key("new"), "$HZ_NEW_KEY")

    def test_rename_into_keyless_group_carries_source_key(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="old")
        preset_registry.set_group_key("old", "$HZ_OLD_KEY")
        preset_registry.rename_group_label("old", "new")
        self.assertIsNone(preset_registry.get_group_key("old"))
        self.assertEqual(preset_registry.get_group_key("new"), "$HZ_OLD_KEY")

    def test_clear_group_label_removes_group_row(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="g")
        preset_registry.set_group_key("g", "$HZ_KEY")
        preset_registry.clear_group_label("g")
        self.assertIsNone(preset_registry.get_group_key("g"))


class BackwardCompatTest(_ScratchDbTestCase):
    def test_own_key_behavior_unchanged_when_groups_empty(self):
        """With preset_groups empty and a preset owning its key, resolution is
        identical to the pre-existing pure resolve_api_key behavior."""
        db_module.init_db()
        os.environ["HZ_OWN_KEY"] = "own-secret"
        self.addCleanup(os.environ.pop, "HZ_OWN_KEY", None)
        preset_registry.set_preset(name="p1", api_key="$HZ_OWN_KEY", group_label="")
        preset = preset_registry.get_preset("p1")
        self.assertEqual(
            preset_registry.resolve_preset_key(preset),
            ai_presets.resolve_api_key(preset),
        )


if __name__ == "__main__":
    unittest.main()
