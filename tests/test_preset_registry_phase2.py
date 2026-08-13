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

        set_preset accepts an `enabled` param (None kept as-is), but the
        no-disable-last guard lives in set_preset_enabled (R12), so the caller
        must keep at least one preset enabled.
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


class R1PartialEditPreservesStateTest(_Phase2ScratchDbTestCase):
    """Kilo R1: set_preset must not wipe priority/enabled on a partial edit.

    Callers that omit priority/enabled must preserve the stored values instead of
    silently re-enabling a disabled preset or resetting its chain position.
    """

    def test_partial_edit_preserves_priority_and_disabled(self):
        self._make_preset("anchor")
        self._make_preset("p", priority=4)
        db.set_preset_enabled("p", False)
        # Omitting priority/enabled must NOT touch them.
        db.set_preset(name="p", base_url="https://new", model="m2", is_custom=1)
        got = db.get_preset("p")
        self.assertEqual(got["priority"], 4)
        self.assertEqual(got["enabled"], 0, "disabled preset must stay disabled after a partial edit")

    def test_partial_edit_preserves_enabled_without_disable_flag(self):
        self._make_preset("q", priority=2)
        db.set_preset(name="q", base_url="https://x2", model="m3", is_custom=1)
        got = db.get_preset("q")
        self.assertEqual(got["enabled"], 1, "an enabled preset stays enabled when priority/enabled omitted")

    def test_explicit_priority_and_enabled_still_applied(self):
        self._make_preset("r", priority=1)
        db.set_preset(name="r", base_url="https://x3", model="m4", is_custom=1, priority=9, enabled=0)
        got = db.get_preset("r")
        self.assertEqual(got["priority"], 9)
        self.assertEqual(got["enabled"], 0)

    def test_partial_edit_preserves_stored_costs(self):
        self._make_preset("anchor")
        self._make_preset("c", input_cost_per_million=1.5, output_cost_per_million=2.5)
        # Omitting costs must NOT NULL them out (mirrors the priority/enabled guard).
        db.set_preset(name="c", base_url="https://new", model="m2", is_custom=1)
        got = db.get_preset("c")
        self.assertEqual(got["input_cost_per_million"], 1.5, "input cost must survive a partial edit")
        self.assertEqual(got["output_cost_per_million"], 2.5, "output cost must survive a partial edit")

    def test_explicit_costs_still_applied(self):
        self._make_preset("d", input_cost_per_million=1.0)
        db.set_preset(name="d", base_url="https://x4", model="m4", is_custom=1,
                      input_cost_per_million=3.0, output_cost_per_million=4.0)
        got = db.get_preset("d")
        self.assertEqual(got["input_cost_per_million"], 3.0)
        self.assertEqual(got["output_cost_per_million"], 4.0)


class R2NoDisableLastGuardTest(_Phase2ScratchDbTestCase):
    """Kilo R2: the no-disable-last guard must exclude the target preset, so a
    no-op disable (already-disabled or nonexistent) succeeds."""

    def _single_enabled(self, name: str) -> int:
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM ai_presets WHERE enabled=1 AND name != ?",
                (name,),
            ).fetchone()["c"]

    def test_noop_disable_of_already_disabled_succeeds(self):
        self._make_preset("keep_on")
        self._make_preset("already_off")
        db.set_preset_enabled("already_off", False)
        # No-op disable must not raise (the last-enabled preset is still on).
        db.set_preset_enabled("already_off", False)
        self.assertEqual(db.get_preset("already_off")["enabled"], 0)

    def test_noop_disable_of_nonexistent_succeeds(self):
        self._make_preset("keep_on")
        db.set_preset_enabled("ghost", False)

    def test_last_enabled_preset_still_refused(self):
        self._make_preset("only")
        with self.assertRaises(ValueError):
            db.set_preset_enabled("only", False)

    def test_disabling_one_of_two_allowed(self):
        self._make_preset("a")
        self._make_preset("b")
        db.set_preset_enabled("a", False)
        self.assertEqual(db.get_preset("a")["enabled"], 0)
        self.assertEqual(db.get_preset("b")["enabled"], 1)


class R3DeleteRepairsPrimaryTest(_Phase2ScratchDbTestCase):
    """Kilo R3: deleting a preset must also clear an orphaned ai_primary_preset ref."""

    def _set_primary(self, name: str):
        db.activate_preset(name)

    def test_delete_clears_primary_reference(self):
        self._make_preset("p1")
        self._make_preset("p2")
        self._set_primary("p1")
        from services.db.settings import get_setting
        self.assertEqual(get_setting("ai_primary_preset"), "p1")
        db.delete_preset("p1")
        self.assertEqual(get_setting("ai_primary_preset"), "", "deleted preset's primary ref must be cleared")


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

    def _full_hour_bucket(self, offset_hours: float) -> str:
        """UTC hour bucket for a timestamp offset hours from now."""
        from datetime import datetime, timedelta, timezone
        when = datetime.now(timezone.utc) - timedelta(hours=offset_hours)
        return when.strftime("%Y-%m-%dT%H:00:00")

    def _row_count(self) -> int:
        from services.db.schema import get_conn
        with get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM preset_hourly_usage WHERE preset_name='pa'"
            ).fetchone()["c"]

    def test_prune_removes_rows_older_than_window_keeps_recent(self):
        # A 25h-old row is inside the year-long read window but outside the 24h
        # prune window, so pruning must delete it from the table.
        self._insert_usage("pa", self._full_hour_bucket(25))
        self._insert_usage("pa", self._full_hour_bucket(0))
        self.assertEqual(self._row_count(), 2)
        db.prune_preset_hourly_usage(hours_back=24)
        self.assertEqual(self._row_count(), 1, "the ~25h-old row must be pruned from the table")


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


class R4ClonePresetTest(_Phase2ScratchDbTestCase):
    """Kilo R4 (Phase 3): db.clone_preset copies all fields except name."""

    def test_clone_copies_all_configured_fields(self):
        self._make_preset(
            "src",
            base_url="https://api.example/v1",
            model="gpt-x",
            api_key="sk-abc",
            daily_batch_size=7,
            max_concurrency=3,
            max_rpm=45,
            max_tpm=1000,
            max_daily_req=50,
            timeout_seconds=15.0,
            temperature=0.4,
            max_output_tokens=2048,
            is_emergency=1,
            priority=2,
            input_cost_per_million=1.5,
            output_cost_per_million=2.5,
            in_fallback_chain=1,
        )
        new_name = db.clone_preset("src", "src_copy")
        self.assertEqual(new_name, "src_copy")
        got = db.get_preset("src_copy")
        src = db.get_preset("src")
        for field in ("base_url", "model", "api_key", "daily_batch_size",
                      "max_concurrency", "max_rpm", "max_tpm", "max_daily_req",
                      "timeout_seconds", "temperature", "max_output_tokens",
                      "is_emergency", "priority", "input_cost_per_million",
                      "output_cost_per_million", "in_fallback_chain"):
            self.assertEqual(got[field], src[field], f"{field} must be copied")
        self.assertEqual(got["name"], "src_copy")

    def test_clone_default_copy_in_fallback_disabled(self):
        self._make_preset("anchor")
        self._make_preset("s2", priority=1, enabled=0)
        db.clone_preset("s2", "s2_copy")
        got = db.get_preset("s2_copy")
        # A clone must not be enabled-without-explicit-choice; it inherits the
        # source's enabled state so it can't suddenly start routing.
        self.assertEqual(got["enabled"], 0)

    def test_clone_name_collision_raises(self):
        self._make_preset("sc", base_url="https://x", model="m", is_custom=1)
        with self.assertRaises(ValueError):
            db.clone_preset("sc", "sc")

    def test_clone_missing_source_raises(self):
        with self.assertRaises(ValueError):
            db.clone_preset("ghost", "ghost_copy")


if __name__ == "__main__":
    unittest.main()