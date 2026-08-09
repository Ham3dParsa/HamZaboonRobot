"""Behavioral seam tests for services/db/preset_registry.

Covers `reindex_preset_priority` (pop/insert + reassign 0..n-1 priorities)
through the `services.db` facade, including error paths. Uses a scratch DB
per test for isolation.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema


class _ScratchDbTestCase(unittest.TestCase):
    """Isolate each test against its own scratch SQLite DB."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        self._seed_presets()

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()

    def _seed_presets(self):
        for existing in db.get_presets():
            db.delete_preset(existing["name"])
        for name in ("preset_a", "preset_b", "preset_c"):
            db.set_preset(name=name, base_url="https://x", model="m")
        for idx, name in enumerate(("preset_a", "preset_b", "preset_c")):
            db.set_preset_priority(name, idx)

    def _group_order(self) -> list[str]:
        """Names in the fallback chain ordered by current priority."""
        return [p["name"] for p in db.get_fallback_chain_presets()]

    def _priorities(self) -> dict[str, int]:
        return {p["name"]: p["priority"] for p in db.get_fallback_chain_presets()}


class ReindexPresetPriorityTest(_ScratchDbTestCase):
    def test_reindex_moves_middle_to_front(self):
        db.reindex_preset_priority("preset_b", target_rank=1, group_is_emergency=False)
        self.assertEqual(self._group_order(), ["preset_b", "preset_a", "preset_c"])
        self.assertEqual(
            self._priorities(),
            {"preset_b": 0, "preset_a": 1, "preset_c": 2},
        )

    def test_reindex_moves_first_to_last(self):
        db.reindex_preset_priority("preset_a", target_rank=3, group_is_emergency=False)
        self.assertEqual(self._group_order(), ["preset_b", "preset_c", "preset_a"])
        self.assertEqual(
            self._priorities(),
            {"preset_b": 0, "preset_c": 1, "preset_a": 2},
        )

    def test_reindex_noop_when_already_at_rank(self):
        db.reindex_preset_priority("preset_a", target_rank=1, group_is_emergency=False)
        self.assertEqual(self._group_order(), ["preset_a", "preset_b", "preset_c"])
        self.assertEqual(
            self._priorities(),
            {"preset_a": 0, "preset_b": 1, "preset_c": 2},
        )

    def test_reindex_raises_on_out_of_range_rank(self):
        with self.assertRaises(ValueError):
            db.reindex_preset_priority("preset_a", target_rank=99, group_is_emergency=False)
        self.assertEqual(
            self._group_order(),
            ["preset_a", "preset_b", "preset_c"],
            "out-of-range rank must not mutate priorities",
        )

    def test_reindex_raises_on_unknown_name(self):
        with self.assertRaises(ValueError):
            db.reindex_preset_priority("ghost", target_rank=1, group_is_emergency=False)
        self.assertEqual(
            self._group_order(),
            ["preset_a", "preset_b", "preset_c"],
            "unknown name must not mutate priorities",
        )

    def test_reindex_rollback_allows_subsequent_write(self):
        """A ValueError rollback must release the lock so the next write succeeds."""
        with self.assertRaises(ValueError):
            db.reindex_preset_priority("preset_a", target_rank=99, group_is_emergency=False)
        db.reindex_preset_priority("preset_a", target_rank=3, group_is_emergency=False)
        self.assertEqual(self._group_order(), ["preset_b", "preset_c", "preset_a"])

    def test_reindex_respects_emergency_group(self):
        db.set_preset_emergency("preset_b", 1)
        db.set_preset_emergency("preset_c", 1)
        db.reindex_preset_priority("preset_c", target_rank=1, group_is_emergency=True)
        emergency_order = [
            p["name"]
            for p in db.get_fallback_chain_presets()
            if p["is_emergency"]
        ]
        self.assertEqual(emergency_order, ["preset_c", "preset_b"])
        non_emergency = [
            p["name"] for p in db.get_fallback_chain_presets() if not p["is_emergency"]
        ]
        self.assertEqual(non_emergency, ["preset_a"])
        self.assertEqual(self._priorities()["preset_a"], 0)


if __name__ == "__main__":
    unittest.main()
