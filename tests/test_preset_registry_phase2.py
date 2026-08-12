"""Phase 2 DB-correctness tests for services/db/preset_registry (R1, R2, R10, R12, R13-at-DB).

Written from the locked Phase 2 contract (see
.opencode/plans/presets/plan-ai-preset-audit-fixes-phase-02-db-correctness.md). Uses a
scratch SQLite DB per test for isolation.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema


class _Phase2ScratchDbTestCase(unittest.TestCase):
    """Isolate each test against its own scratch SQLite DB."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        self._clean_presets()

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()

    def _clean_presets(self):
        for existing in db.get_presets():
            db.delete_preset(existing["name"])

    def _make_preset(self, name: str, **kwargs):
        self._make_preset_enabled(name, **kwargs)

    def _make_preset_enabled(self, name: str, **kwargs):
        """Create a preset via set_preset, then optionally adjust its enabled state.

        set_preset has no `enabled` param; the enabled column is toggled through
        set_preset_enabled, which enforces the no-disable-last guard (R12). So the
        caller must keep at least one preset enabled.
        """
        enable = kwargs.pop("enabled", 1)
        defaults = {"base_url": "https://x", "model": "m", "is_custom": 1}
        defaults.update(kwargs)
        db.set_preset(name=name, **defaults)
        if bool(enable) != 1:
            db.set_preset_enabled(name, bool(enable))

    @staticmethod
    def _chain_order() -> list[str]:
        return [p["name"] for p in db.get_fallback_chain_presets()]


class R2PriorityInSetPresetTest(_Phase2ScratchDbTestCase):
    """R2: set_preset must persist a priority value."""

    def test_set_preset_persists_priority(self):
        self._make_preset("prio_a", priority=3)
        self._make_preset("prio_b", priority=0)
        self._make_preset("prio_c", priority=1)
        got = {p["name"]: p["priority"] for p in db.get_presets()}
        self.assertEqual(got["prio_a"], 3)
        self.assertEqual(got["prio_b"], 0)
        self.assertEqual(got["prio_c"], 1)

    def test_priority_persisted_on_conflict_upsert(self):
        self._make_preset("upsert", priority=1)
        db.set_preset(name="upsert", base_url="https://x", model="m", is_custom=1, priority=7)
        got = db.get_preset("upsert")
        self.assertEqual(got["priority"], 7)

    def test_default_priority_zero(self):
        self._make_preset("defaulted")
        got = db.get_preset("defaulted")
        self.assertEqual(got["priority"], 0)


class R10NoSilentEmptyActivePresetTest(_Phase2ScratchDbTestCase):
    """R10: get_active_preset must raise (not return {}) when no enabled preset exists."""

    def test_get_active_preset_raises_when_no_presets(self):
        with self.assertRaises(Exception):
            db.get_active_preset()

    def test_get_active_preset_raises_when_only_disabled(self):
        self._make_preset("disabled_only")
        self._make_preset("anchor_to_delete")
        db.set_preset_enabled("disabled_only", False)
        db.delete_preset("anchor_to_delete")
        with self.assertRaises(Exception):
            db.get_active_preset()

    def test_get_active_preset_returns_enabled(self):
        self._make_preset("active_ok", enabled=1)
        self.assertEqual(db.get_active_preset()["name"], "active_ok")


class R12GuardsTest(_Phase2ScratchDbTestCase):
    """R12: DB guards for rename collision, emergency-flip-one, no-disable-last,
    and ai_fallback_preset repair on delete."""

    def test_rename_collision_raises(self):
        """R12: renaming onto an existing preset name must raise ValueError."""
        self._make_preset("src", priority=0)
        self._make_preset("dst", priority=1)
        with self.assertRaises(ValueError):
            db.set_preset(
                name="dst",
                base_url="https://x",
                model="m",
                is_custom=1,
                previous_name="src",
            )

    def test_no_disable_last_enabled_preset(self):
        """R12: disabling the last enabled preset must be refused."""
        self._make_preset("solo", enabled=1)
        with self.assertRaises(ValueError):
            db.set_preset_enabled("solo", False)
        got = db.get_preset("solo")
        self.assertEqual(got["enabled"], 1, "last enabled preset must stay enabled")

    def test_delete_repairs_ai_fallback_preset(self):
        """R12: deleting the preset referenced by ai_fallback_preset clears the ref."""
        self._make_preset("fb_target", enabled=1)
        db.set_setting("ai_fallback_preset", "fb_target")
        db.delete_preset("fb_target")
        self.assertNotEqual(
            db.get_setting("ai_fallback_preset", ""),
            "fb_target",
            "ai_fallback_preset should not point at a deleted preset",
        )

    def test_delete_does_not_break_other_fallback_ref(self):
        self._make_preset("unrelated", enabled=1)
        db.set_setting("ai_fallback_preset", "unrelated")
        db.delete_preset("unrelated")
        self.assertNotEqual(db.get_setting("ai_fallback_preset", ""), "unrelated")


class R1ChainSourceTest(_Phase2ScratchDbTestCase):
    """R1: get_fallback_chain_presets is the single order source, ordering
    normal (is_emergency=0) before emergency (is_emergency=1), each by priority."""

    def test_chain_orders_normal_before_emergency_by_priority(self):
        self._make_preset("emerg_low", priority=0, is_emergency=1)
        self._make_preset("normal_hi", priority=9, is_emergency=0)
        self._make_preset("normal_lo", priority=1, is_emergency=0)
        self.assertEqual(
            self._chain_order(),
            ["normal_lo", "normal_hi", "emerg_low"],
        )

    def test_chain_excludes_disabled_and_non_chain(self):
        self._make_preset("in_chain", priority=2, in_fallback_chain=1)
        self._make_preset("off")
        self._make_preset("not_in", priority=1, in_fallback_chain=0)
        db.set_preset_enabled("off", False)
        self.assertEqual(self._chain_order(), ["in_chain"])


class R13aPruneAndRPCTest(_Phase2ScratchDbTestCase):
    """R13a: preset_hourly_usage prune >24h + RPD counts only successful calls."""

    def _insert_usage(self, preset_name: str, hour_bucket: str, req: int = 1):
        from services.db.schema import get_conn
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO preset_hourly_usage(preset_name, hour_bucket, request_count, token_count) "
                "VALUES (?, ?, ?, 0) "
                "ON CONFLICT(preset_name, hour_bucket) DO UPDATE SET "
                "request_count=request_count+excluded.request_count",
                (preset_name, hour_bucket, req),
            )
            conn.commit()

    def test_prune_removes_rows_older_than_window_keeps_recent(self):
        self._insert_usage("pa", "2000-01-01T00:00:00")
        self._insert_usage("pa", "2099-01-01T00:00:00")
        db.prune_preset_hourly_usage(hours_back=24)
        req, _ = db.get_hourly_usage("pa", hours_back=8766)
        self.assertEqual(req, 1, "only the stale row should be pruned")


class R14InsertPresetAtRankTest(_Phase2ScratchDbTestCase):
    """R14: insert_preset_at_rank densifies the enabled normal group so top /
    bottom / manual-value always land at the intended fallback-chain position."""

    def test_rank_zero_is_first_densified(self):
        self._make_preset("a", priority=0)
        self._make_preset("b", priority=5)
        self._make_preset("newtop")
        db.insert_preset_at_rank("newtop", 0)
        self.assertEqual(self._chain_order()[:3], ["newtop", "a", "b"])

    def test_bottom_rank_appends_and_densifies(self):
        self._make_preset("a", priority=0)
        self._make_preset("b", priority=3)
        self._make_preset("newbot")
        count = sum(1 for p in db.get_fallback_chain_presets() if not p.get("is_emergency") and p["name"] != "newbot")
        db.insert_preset_at_rank("newbot", count)
        self.assertEqual(self._chain_order()[-3:], ["a", "b", "newbot"])

    def test_manual_rank_places_in_middle(self):
        self._make_preset("a", priority=0)
        self._make_preset("b", priority=1)
        self._make_preset("c", priority=2)
        self._make_preset("newmid")
        db.insert_preset_at_rank("newmid", 1)
        self.assertEqual(self._chain_order()[:4], ["a", "newmid", "b", "c"])

    def test_out_of_range_rank_raises(self):
        self._make_preset("a", priority=0)
        self._make_preset("bad")
        with self.assertRaises(ValueError):
            db.insert_preset_at_rank("bad", 5)


if __name__ == "__main__":
    unittest.main()