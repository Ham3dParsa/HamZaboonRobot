"""Proof tests for the 60-day load simulation (locked plan scale/plan-load-sim-60day, T1).

Harness-only: covers R1 (explicit app-day per iteration, tz-correct bounds),
R2 (stable cohort, day-evolving activity, population projection), R3 (real
nightly purges + backup stand-in + growth curve), and R4 (expiry / streak /
quota edges across 3 consecutive days, plus one full 60-day smoke asserting
growth-curve length 60 and zero violations). No production code is touched;
no real AI tokens (this harness makes no AI calls at all).
"""

import datetime
import unittest

from tests.test_integration import helpers

from tools.load_sim.multiday import (
    DEFAULT_COHORT_N,
    build_cohort,
    project_cost,
    run_60day,
    run_multiday,
    sim_day_iso,
    simulate_day,
)


class DayLoopPureTests(unittest.TestCase):
    def test_sim_day_iso_anchors_final_day(self):
        anchor = "2026-09-06"
        self.assertEqual(sim_day_iso(59, 60, anchor), anchor)
        want_first = (
            datetime.date.fromisoformat(anchor) - datetime.timedelta(days=59)
        ).isoformat()
        self.assertEqual(sim_day_iso(0, 60, anchor), want_first)
        isos = [sim_day_iso(d, 60, anchor) for d in range(60)]
        self.assertEqual(len(set(isos)), 60)
        self.assertEqual(isos, sorted(isos))

    def test_attend_prob_mirrors_persona_params(self):
        from tools.load_sim.plan_mix import _PERSONA_PARAMS, attend_prob

        for persona in ("eager", "average", "lazy", "gamer"):
            self.assertEqual(
                attend_prob(persona, 3), _PERSONA_PARAMS[persona]["attend"]
            )
        # Fluctuating 21-day wave: peak (~day 5) > base > trough (~day 16).
        base = _PERSONA_PARAMS["fluctuating"]["attend_base"]
        self.assertGreater(attend_prob("fluctuating", 5), base)
        self.assertLess(attend_prob("fluctuating", 16), base)
        for day in range(21):
            self.assertGreaterEqual(attend_prob("fluctuating", day), 0.05)
            self.assertLessEqual(attend_prob("fluctuating", day), 0.98)

    def test_cohort_stable_across_builds(self):
        first = build_cohort(n=50, seed=4)
        second = build_cohort(n=50, seed=4)
        self.assertEqual(first, second)
        ids = [u["user_id"] for u in first]
        self.assertEqual(len(set(ids)), 50)
        self.assertEqual(len({u["persona"] for u in first}), 5)

    def test_simulate_day_deterministic_and_evolves(self):
        cohort = [
            {
                "user_id": 900000 + i,
                "plan": "free",
                "persona": "fluctuating",
                "sessions": 2,
                "queries": 1,
            }
            for i in range(500)
        ]
        peak = simulate_day(cohort, 5, seed=11)
        trough = simulate_day(cohort, 16, seed=11)
        self.assertEqual(peak, simulate_day(cohort, 5, seed=11))
        # Peak-wave attendance far exceeds trough attendance.
        self.assertGreater(peak["active"] - trough["active"], 150)

    def test_project_cost_arithmetic(self):
        self.assertAlmostEqual(project_cost(100.0, 200, 5000), 2500.0)
        self.assertAlmostEqual(project_cost(0.0, 200, 5000), 0.0)
        with self.assertRaises(ValueError):
            project_cost(10.0, 0, 5000)


class ThreeDayMiniatureTests(unittest.TestCase):
    def setUp(self):
        from services import db
        from services.db import schema as db_schema

        self._holder, self.db_path = helpers.fresh_db_from_snapshot()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        db.DB_PATH = self.db_path
        db_schema.DB_PATH = self.db_path
        db.init_db()

    def tearDown(self):
        from services import db
        from services.db import schema as db_schema

        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._holder.cleanup()

    def test_3day_run_shape(self):
        result = run_multiday(n=20, seed=11, db_path=self.db_path, days=3)

        self.assertEqual(result["days"], 3)
        self.assertEqual(len(result["day_totals"]), 3)
        self.assertEqual(len(result["growth_curve_bytes"]), 3)
        self.assertEqual(len(result["backup_runs"]), 2)
        self.assertEqual(result["violations"], [])
        self.assertEqual(len(set(result["cohort_user_ids"])), 20)
        for day_total in result["day_totals"]:
            for key in ("day", "day_iso", "active", "sessions", "queries"):
                self.assertIn(key, day_total)
        for entry in result["backup_runs"]:
            self.assertTrue(entry["ran"])
            self.assertFalse(entry["uploaded"])

    def test_r4_edges_expired_session_streak_quota(self):
        from config import APP_TZ
        from services import db
        from services import scheduling
        from services.db.sessions import load_study_session, save_study_session
        from services.db.users import get_quota_status, touch_streak_in_txn
        from tools.load_sim.multiday import run_nightly

        real_today = datetime.datetime.now(APP_TZ).date()
        d0 = (real_today - datetime.timedelta(days=2)).isoformat()
        d1 = (real_today - datetime.timedelta(days=1)).isoformat()
        d2 = real_today.isoformat()

        # Expired sessions do not resume; live ones survive the purge.
        save_study_session(951001, d0, "{}")
        save_study_session(951002, d2, "{}")
        run_nightly()
        self.assertIsNone(load_study_session(951001))
        self.assertIsNotNone(load_study_session(951002))

        # Streak increments on active days, resets after a gap (midnight rule).
        db.create_user_if_needed(951011, "edge")
        db.create_user_if_needed(951012, "edgegap")
        with db.transaction() as conn:
            self.assertEqual(
                touch_streak_in_txn(conn, 951011, today_iso=d0), 1
            )
            self.assertEqual(
                touch_streak_in_txn(conn, 951011, today_iso=d1), 2
            )
        with db.transaction() as conn:
            # Gap: touching d2 after last active d0 resets to 1.
            self.assertEqual(
                touch_streak_in_txn(conn, 951012, today_iso=d0), 1
            )
            self.assertEqual(
                touch_streak_in_txn(conn, 951012, today_iso=d2), 1
            )

        # Quotas reset to full each new day.
        db.create_user_if_needed(951021, "edgequota")
        with db.transaction() as conn:
            conn.execute(
                "UPDATE users SET words_asked_today=?, words_asked_date=? "
                "WHERE user_id=?",
                (5, d0, 951021),
            )
        status = get_quota_status(951021)
        self.assertIsNotNone(status)
        self.assertEqual(status["word_query"]["used"], 0)
        db.set_setting(f"sessions_used_951021_{d0}", "2")
        budget = scheduling.daily_session_budget(951021, "free")
        self.assertEqual(budget["used"], 0)
        self.assertEqual(budget["remaining"], budget["total"])


class SixtyDaySmokeTests(unittest.TestCase):
    def setUp(self):
        from services import db
        from services.db import schema as db_schema

        self._holder, self.db_path = helpers.fresh_db_from_snapshot()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        db.DB_PATH = self.db_path
        db_schema.DB_PATH = self.db_path
        db.init_db()

    def tearDown(self):
        from services import db
        from services.db import schema as db_schema

        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._holder.cleanup()

    def test_full_60day_smoke(self):
        result = run_60day(n=DEFAULT_COHORT_N, seed=7, db_path=self.db_path)

        self.assertEqual(result["total"], DEFAULT_COHORT_N)
        self.assertEqual(result["days"], 60)
        self.assertEqual(len(result["day_totals"]), 60)
        self.assertEqual(len(result["growth_curve_bytes"]), 60)
        self.assertEqual(len(result["backup_runs"]), 59)
        self.assertEqual(result["violations"], [])
        self.assertEqual(len(set(result["cohort_user_ids"])), 200)
        for day_total in result["day_totals"]:
            self.assertGreaterEqual(day_total["active"], 0)
            self.assertLessEqual(day_total["active"], 200)
        for size in result["growth_curve_bytes"]:
            self.assertGreaterEqual(size, 0)
        for entry in result["backup_runs"]:
            self.assertTrue(entry["ran"])
            self.assertFalse(entry["uploaded"])
        total_sessions = sum(d["sessions"] for d in result["day_totals"])
        self.assertGreater(total_sessions, 0)
        # Population projection helper on the measured cohort figure.
        projected = project_cost(total_sessions, 200, 5000)
        self.assertAlmostEqual(projected, total_sessions * 25.0)


if __name__ == "__main__":
    unittest.main()
