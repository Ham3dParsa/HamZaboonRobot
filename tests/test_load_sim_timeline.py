"""Proof tests for discrete-event arrival timeline (T11, hybrid H1-H3).

Harness-only: H1 timeline compiler (pure, no DB/router) plus sequential
replay through the existing driver journey machinery (real routers,
replay-wide mocks, virtual-clock day scoping). No production code touched;
zero real AI tokens.
"""

import unittest
from unittest.mock import MagicMock, patch

from tests.test_integration import helpers


class TimelineShapeTests(unittest.TestCase):
    def _cohort(self, n=80, seed=11):
        from tools.load_sim.multiday import build_cohort

        return build_cohort(n=n, seed=seed)

    def test_sorted_think_gaps_and_kinds(self):
        from tools.load_sim.timeline import (
            EVENT_KINDS,
            THINK_HI_S,
            THINK_LO_S,
            compile_timeline,
        )

        cohort = self._cohort()
        events = compile_timeline(
            cohort, days=21, seed=11, anchor_today_iso="2026-03-01"
        )
        self.assertGreater(len(events), 0)
        kinds = {e["kind"] for e in events}
        self.assertTrue(kinds.issubset(set(EVENT_KINDS)))
        for core in ("SESSION_START", "GRADE", "QUERY_SUBMIT"):
            self.assertIn(core, kinds)
        vtimes = [e["vtime"] for e in events]
        self.assertEqual(vtimes, sorted(vtimes))
        grades = [e for e in events if e["kind"] == "GRADE"]
        self.assertGreater(len(grades), 0)
        for event in grades:
            self.assertGreaterEqual(event["think_gap_s"], THINK_LO_S)
            self.assertLessEqual(event["think_gap_s"], THINK_HI_S)
            self.assertGreaterEqual(event["think_gap_s"], 10.0)
            self.assertLessEqual(event["think_gap_s"], 46.0)

    def test_split_sessions_abandon_then_resume(self):
        from tools.load_sim.timeline import compile_timeline

        cohort = self._cohort()
        events = compile_timeline(
            cohort, days=21, seed=11, anchor_today_iso="2026-03-01"
        )
        abandons = [e for e in events if e["kind"] == "ABANDON"]
        resumes = [e for e in events if e["kind"] == "RESUME"]
        self.assertGreater(len(abandons), 0)
        self.assertEqual(len(abandons), len(resumes))
        resume_by_key = {
            (r["user_id"], r["day"], r["session_idx"]): r for r in resumes
        }
        for abandon in abandons:
            key = (
                abandon["user_id"],
                abandon["day"],
                abandon["session_idx"],
            )
            self.assertIn(key, resume_by_key)
            self.assertGreater(
                resume_by_key[key]["vtime"], abandon["vtime"]
            )

    def test_midnight_crossings_exist_and_day_iso_per_event(self):
        from tools.load_sim.multiday import sim_day_iso
        from tools.load_sim.timeline import compile_timeline

        days = 21
        anchor = "2026-03-01"
        cohort = self._cohort()
        events = compile_timeline(
            cohort, days=days, seed=11, anchor_today_iso=anchor
        )
        crossed = [e for e in events if e["crossed_midnight"]]
        self.assertGreater(len(crossed), 0)
        for event in crossed:
            self.assertNotEqual(event["eff_day"], event["day"])
            self.assertEqual(
                event["day_iso"],
                sim_day_iso(event["eff_day"], days, anchor),
            )
        plain = [e for e in events if not e["crossed_midnight"]]
        self.assertGreater(len(plain), 0)
        for event in plain[:200]:
            self.assertEqual(
                event["day_iso"],
                sim_day_iso(event["day"], days, anchor),
            )

    def test_deterministic_per_seed_day_user(self):
        from tools.load_sim.timeline import compile_timeline

        cohort = self._cohort()
        first = compile_timeline(
            cohort, days=7, seed=11, anchor_today_iso="2026-03-01"
        )
        second = compile_timeline(
            cohort, days=7, seed=11, anchor_today_iso="2026-03-01"
        )
        self.assertEqual(first, second)
        other = compile_timeline(
            cohort, days=7, seed=12, anchor_today_iso="2026-03-01"
        )
        self.assertNotEqual(
            [e["vtime"] for e in first], [e["vtime"] for e in other]
        )

    def test_partial_completion_and_quota_underuse_emerge(self):
        from tools.load_sim.timeline import compile_timeline

        cohort = self._cohort(n=60, seed=11)
        events = compile_timeline(
            cohort, days=14, seed=11, anchor_today_iso="2026-03-01"
        )
        completes = [e for e in events if e["kind"] == "SESSION_COMPLETE"]
        abandons = [e for e in events if e["kind"] == "ABANDON"]
        self.assertGreater(len(completes), 0)
        self.assertGreater(len(abandons), 0)
        # Underuse: some cohort users sit out at least one day.
        seen_days: dict[int, set[int]] = {}
        for event in events:
            if event["kind"] == "SESSION_START":
                seen_days.setdefault(event["user_id"], set()).add(
                    event["day"]
                )
        self.assertTrue(
            any(len(days) < 14 for days in seen_days.values())
        )

    def test_overlap_prescan_output(self):
        from tools.load_sim.timeline import (
            compile_timeline,
            scan_top_windows,
        )

        cohort = self._cohort(n=30, seed=11)
        events = compile_timeline(
            cohort, days=7, seed=11, anchor_today_iso="2026-03-01"
        )
        windows = scan_top_windows(events)
        self.assertEqual(len(windows), 5)
        counts = [w["count"] for w in windows]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertGreaterEqual(counts[0], counts[-1])
        self.assertGreater(counts[0], 1)
        for window in windows:
            self.assertIn("window_start_vtime", window)
            self.assertIn("day_iso", window)
            self.assertIn("count", window)
        self.assertEqual(scan_top_windows([]), [])


class TimelineReplayMiniatureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import bot
        from services import db
        from services.db import schema as db_schema

        self._holder, self.db_path = helpers.fresh_db_from_snapshot()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        db.DB_PATH = self.db_path
        db_schema.DB_PATH = self.db_path
        db.init_db()
        self._offline = patch.object(bot, "_telegram_offline", False)
        self._offline.start()
        self._no_real_ai = patch(
            "services.ai.ai.ask_card",
            new=MagicMock(side_effect=AssertionError("real AI must not run")),
        )
        self._no_real_ai.start()

    def tearDown(self):
        from services import db
        from services.db import schema as db_schema

        self._no_real_ai.stop()
        self._offline.stop()
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._holder.cleanup()

    async def test_tiny_timeline_replay_zero_violations(self):
        from tools.load_sim.multiday import build_cohort
        from tools.load_sim.timeline import compile_timeline, run_timeline_replay

        cohort = build_cohort(n=4, seed=11)
        events = compile_timeline(
            cohort, days=3, seed=11, anchor_today_iso="2026-03-01"
        )
        self.assertGreater(len(events), 0)
        result = await run_timeline_replay(
            events,
            self.db_path,
            seed=11,
            patient=True,
            fast_scale=0.0001,
        )
        self.assertEqual(result["events_total"], len(events))
        self.assertEqual(result["events_replayed"], len(events))
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["violations"], [])
        self.assertGreater(len(result["days"]), 0)
        self.assertEqual(len(result["top_windows"]), 5)
        counts = [w["count"] for w in result["top_windows"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertGreater(result["real_grades"], 0)
        self.assertIn("GRADE", result["latencies_ms"])
        self.assertGreater(len(result["grade_latencies_ms"]), 0)


if __name__ == "__main__":
    unittest.main()
