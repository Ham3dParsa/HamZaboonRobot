"""Tests for the DB-driven preset keys feature (spec #278) + Phase 5.

Covers the additive `preset_groups` table, the group-aware `resolve_preset_key`
seam (own key > group key > empty), and the group CRUD / label-consistency
guarantees. Since Phase 5, keys are stored as Fernet ciphertext: every write
encrypts and every resolve decrypts, so all resolution tests observe the
original plaintext while raw `get_group_key`/`get_preset` reads observe the
encrypted token.
"""

import os
import tempfile
import unittest
from unittest import mock

import config

from services import db as db_module
from services.db import schema as db_schema
from services.db import key_crypto
from services.db import preset_registry
from services.ai import ai_presets


TEST_MASTER_KEY = "sd4H8UUr5ONYISGXcx468OQwFaUxaktNGGTPs9TBESg="


class _ScratchDbTestCase(unittest.TestCase):
    """Isolate each test against its own scratch SQLite DB + pinned master key."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db_module.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db_module.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        self._master = mock.patch.object(config, "AI_MASTER_KEY", TEST_MASTER_KEY)
        self._master.start()
        self.addCleanup(self._master.stop)

    def tearDown(self):
        db_module.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()

    def _dec(self, token):
        return key_crypto.decrypt_secret(token) if token else token


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

    def _seed(self, presets, group_keys=None):
        for name, api_key, group_label in presets:
            preset_registry.set_preset(
                name=name, api_key=api_key, group_label=group_label
            )
        for label, key in (group_keys or {}).items():
            preset_registry.set_group_key(label, key)

    def test_own_key_precedes_group_key(self):
        self._seed([("p1", "own-secret-123456", "g")], {"g": "group-secret-123456"})
        preset = preset_registry.get_preset("p1")
        self.assertEqual(preset_registry.resolve_preset_key(preset), "own-secret-123456")

    def test_group_key_used_when_own_empty(self):
        self._seed([("p1", "", "g")], {"g": "group-secret-123456"})
        preset = preset_registry.get_preset("p1")
        self.assertEqual(preset_registry.resolve_preset_key(preset), "group-secret-123456")

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
        preset_registry.set_group_key("g", "group-secret-123456")
        stored = preset_registry.get_group_key("g")
        self.assertTrue(stored.startswith("gAAAA"))
        self.assertEqual(key_crypto.decrypt_secret(stored), "group-secret-123456")
        preset_registry.delete_group_key("g")
        self.assertIsNone(preset_registry.get_group_key("g"))

    def test_rename_group_label_updates_preset_groups(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="old")
        preset_registry.set_group_key("old", "old-secret-123456")
        preset_registry.rename_group_label("old", "new")
        self.assertIsNone(preset_registry.get_group_key("old"))
        self.assertEqual(self._dec(preset_registry.get_group_key("new")), "old-secret-123456")

    def test_self_rename_preserves_group_key(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="g")
        preset_registry.set_group_key("g", "group-secret-123456")
        preset_registry.rename_group_label("g", "g")
        self.assertEqual(self._dec(preset_registry.get_group_key("g")), "group-secret-123456")

    def test_rename_into_existing_group_keeps_target_key(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="old")
        preset_registry.set_preset(name="p2", api_key="", group_label="new")
        preset_registry.set_group_key("old", "old-secret-123456")
        preset_registry.set_group_key("new", "new-secret-123456")
        preset_registry.rename_group_label("old", "new")
        self.assertIsNone(preset_registry.get_group_key("old"))
        self.assertEqual(self._dec(preset_registry.get_group_key("new")), "new-secret-123456")

    def test_rename_into_keyless_group_carries_source_key(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="old")
        preset_registry.set_group_key("old", "old-secret-123456")
        preset_registry.rename_group_label("old", "new")
        self.assertIsNone(preset_registry.get_group_key("old"))
        self.assertEqual(self._dec(preset_registry.get_group_key("new")), "old-secret-123456")

    def test_clear_group_label_removes_group_row(self):
        preset_registry.set_preset(name="p1", api_key="", group_label="g")
        preset_registry.set_group_key("g", "group-secret-123456")
        preset_registry.clear_group_label("g")
        self.assertIsNone(preset_registry.get_group_key("g"))


class BackwardCompatTest(_ScratchDbTestCase):
    def test_own_key_behavior_unchanged_when_groups_empty(self):
        """With preset_groups empty and a preset owning its key, resolution is
        identical to the pre-existing pure resolve_api_key behavior."""
        db_module.init_db()
        preset_registry.set_preset(name="p1", api_key="own-secret-123456", group_label="")
        preset = preset_registry.get_preset("p1")
        self.assertEqual(
            preset_registry.resolve_preset_key(preset),
            ai_presets.resolve_api_key(preset),
        )


if __name__ == "__main__":
    unittest.main()
