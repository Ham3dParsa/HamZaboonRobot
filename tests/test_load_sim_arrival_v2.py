"""Proof tests for arrival-v2 T1 (harness-only, locked plan scale/plan-load-sim-arrival-v2).

Covers R1 (DB-driven session sizes in, sessions span days), R2 (personas
independent of plans; abandon-resume flow with the fluctuating 21-day wave),
and R3 (three named edge scenarios plus a small driver replay through the
existing counters). Pure sampling tests stay small; the driver smoke replays
only n=10 per scenario (no full 2800 runs in CI).
"""

import random
import unittest
from unittest.mock import MagicMock, patch

from tests.test_integration import helpers

# DB-shaped limits mirror the plans-table seed (services/db/plans.py):
# free 2x3, bronze 3x3, silver 3x5, gold 4x7, emerald 5x9.
DB_SHAPED_LIMITS = {
    "free": {"sessions": 2, "cards": 3},
    "bronze": {"sessions": 3, "cards": 3},
    "silver": {"sessions": 3, "cards": 5},
    "gold": {"sessions": 4, "cards": 7},
    "emerald": {"sessions": 5, "cards": 9},
}

_COUNTER_KEYS = (
    "telegram_429",
    "telegram_retries",
    "db_busy_retries",
    "ai_timeouts",
    "ai_error",
    "word_query_ok",
    "quota_double_spend",
    "report_loss",
    "plan_fallbacks",
    "real_grades",
    "card_lookup_miss",
    "grade_check_failed",
)


class ArrivalDistributionTests(unittest.TestCase):
    def test_db_limits_drive_session_sizes(self):
        from tools.load_sim.plan_mix import sample_workload

        users = sample_workload(n=300, seed=21, plan_limits=DB_SHAPED_LIMITS)
        self.assertEqual(len(users), 300)
        for user in users:
            spec = DB_SHAPED_LIMITS[user["plan"]]
            self.assertEqual(user["sessions"], spec["sessions"])
            self.assertEqual(user["cards_per_session"], spec["cards"])
            self.assertEqual(user["session_cards"], [spec["cards"]] * spec["sessions"])
            self.assertEqual(len(user["start_hours"]), spec["sessions"])
        total_sessions = sum(u["sessions"] for u in users)
        self.assertGreater(total_sessions, 300)
        self.assertGreater(len({u["day"] for u in users}), 1)

    def test_personas_independent_of_plans(self):
        from tools.load_sim.plan_mix import sample_workload

        users = sample_workload(n=2000, seed=11)
        personas = {u["persona"] for u in users}
        self.assertEqual(personas, {"lazy", "average", "eager", "fluctuating", "gamer"})
        mix = {p: sum(1 for u in users if u["persona"] == p) / 2000 for p in personas}
        for persona, want in (
            ("lazy", 0.25),
            ("average", 0.40),
            ("eager", 0.20),
            ("fluctuating", 0.10),
            ("gamer", 0.05),
        ):
            self.assertAlmostEqual(mix[persona], want, delta=0.05)
        plans = ("free", "bronze", "silver", "gold", "emerald")
        global_share = {c: sum(1 for u in users if u["plan"] == c) / 2000 for c in plans}
        worst = 0.0
        for persona in personas:
            cohort = [u for u in users if u["persona"] == persona]
            for code in plans:
                share = sum(1 for u in cohort if u["plan"] == code) / len(cohort)
                worst = max(worst, abs(share - global_share[code]))
        self.assertLess(worst, 0.12, f"persona/plan drift too large: {worst:.3f}")

    def test_persona_params_mirror_sources(self):
        from tools.load_sim.plan_mix import _PERSONA_PARAMS

        # tools/Fsrs_simulation_v5/v5.4_FSRS_full.py PERSONAS.
        self.assertEqual(_PERSONA_PARAMS["eager"]["attend"], 0.92)
        self.assertEqual((_PERSONA_PARAMS["eager"]["q_lo"], _PERSONA_PARAMS["eager"]["q_hi"]), (2, 6))
        self.assertEqual(_PERSONA_PARAMS["average"]["attend"], 0.70)
        self.assertEqual((_PERSONA_PARAMS["average"]["q_lo"], _PERSONA_PARAMS["average"]["q_hi"]), (0, 3))
        self.assertEqual(_PERSONA_PARAMS["lazy"]["attend"], 0.35)
        self.assertEqual((_PERSONA_PARAMS["lazy"]["q_lo"], _PERSONA_PARAMS["lazy"]["q_hi"]), (0, 1))
        fluct = _PERSONA_PARAMS["fluctuating"]
        self.assertEqual(
            (fluct["attend_base"], fluct["attend_amplitude"], fluct["attend_period_days"]),
            (0.55, 0.30, 21),
        )
        self.assertEqual((fluct["q_lo"], fluct["q_hi"]), (0, 3))
        # tools/fsrs-replay/sim_runner.py gamer augmentation.
        self.assertEqual(_PERSONA_PARAMS["gamer"]["attend"], 0.98)
        self.assertEqual((_PERSONA_PARAMS["gamer"]["q_lo"], _PERSONA_PARAMS["gamer"]["q_hi"]), (3, 8))

    def test_legacy_plan_journey_gates_unchanged(self):
        from tools.load_sim.plan_mix import sample_workload

        users = sample_workload(n=100, seed=7)
        self.assertEqual(len(users), 100)
        plans = [u["plan"] for u in users]
        for code in ("free", "bronze", "silver", "gold", "emerald"):
            self.assertIn(code, plans)
        free_share = plans.count("free") / 100
        self.assertGreaterEqual(free_share, 0.60)
        self.assertLessEqual(free_share, 0.80)
        journeys = [u["journey"] for u in users]
        self.assertIn("partial", journeys)
        self.assertIn("word_query", journeys)
        self.assertEqual(users, sample_workload(n=100, seed=7))


class AbandonResumeTests(unittest.TestCase):
    def test_abandon_resume_flow(self):
        from tools.load_sim.plan_mix import sample_workload

        users = sample_workload(n=500, seed=5)
        abandoned = [u for u in users if u["abandoned"]]
        self.assertGreater(len(abandoned), 0)
        for user in abandoned:
            delay = user["resume_hours_later"]
            self.assertIsNotNone(delay)
            self.assertGreaterEqual(delay, 0.5)
            self.assertLessEqual(delay, 9.0)
        for user in users:
            if not user["abandoned"]:
                self.assertIsNone(user["resume_hours_later"])

    def test_fluctuating_wave_modulates_abandon(self):
        from tools.load_sim.plan_mix import sample_session_outcome

        def rate(day: int) -> float:
            rng = random.Random(0)
            hits = sum(
                sample_session_outcome("fluctuating", day, rng)[0] for _ in range(3000)
            )
            return hits / 3000

        # Wave trough (~day 16) abandons far more often than peak (~day 5).
        self.assertGreater(rate(16) - rate(5), 0.3)


class EdgeScenarioTests(unittest.TestCase):
    def test_edge_shapes(self):
        from tools.load_sim.plan_mix import edge_scenarios

        herd = edge_scenarios("gamer_herd", n=20, seed=9, plan_limits=DB_SHAPED_LIMITS)
        self.assertTrue(all(u["persona"] == "gamer" for u in herd))
        self.assertTrue(all(u["start_hours"] == [18] * u["sessions"] for u in herd))
        self.assertTrue(all(j in ("full_session", "word_query") for j in (u["journey"] for u in herd)))

        resume = edge_scenarios("mass_resume", n=20, seed=9, plan_limits=DB_SHAPED_LIMITS)
        self.assertTrue(all(u["journey"] == "partial" for u in resume))
        self.assertTrue(all(u["abandoned"] for u in resume))
        self.assertTrue(all(u["resume_hours_later"] == 3.0 for u in resume))
        self.assertTrue(all(u["start_hours"] == [12] * u["sessions"] for u in resume))

        thunder = edge_scenarios("hour_boundary_thunder", n=20, seed=9, plan_limits=DB_SHAPED_LIMITS)
        self.assertTrue(all(u["start_hours"] == [9] * u["sessions"] for u in thunder))
        for user in thunder:
            spec = DB_SHAPED_LIMITS[user["plan"]]
            self.assertEqual(user["sessions"], spec["sessions"])

    def test_unknown_edge_scenario_raises(self):
        from tools.load_sim.plan_mix import edge_scenarios

        with self.assertRaises(ValueError):
            edge_scenarios("nope", n=5, seed=1)


class EdgeDriverSmokeTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_gamer_herd_replay_through_existing_counters(self):
        from tools.load_sim.driver import run_edge_scenario

        metrics = await run_edge_scenario("gamer_herd", n=10, seed=3, db_path=self.db_path)
        self.assertEqual(metrics["total"], 10)
        self.assertEqual(metrics["scenario"], "gamer_herd")
        for key in _COUNTER_KEYS:
            self.assertIn(key, metrics)
        self.assertEqual(metrics["errors"], 0)
        self.assertEqual(metrics["personas"], {"gamer": 10})

    async def test_mass_resume_replay(self):
        from tools.load_sim.driver import run_edge_scenario

        metrics = await run_edge_scenario("mass_resume", n=10, seed=4, db_path=self.db_path)
        self.assertEqual(metrics["total"], 10)
        self.assertEqual(metrics["scenario"], "mass_resume")
        self.assertEqual(metrics["journey_counts"], {"partial": 10})
        self.assertEqual(metrics["errors"], 0)
        self.assertEqual(metrics["report_loss"], 0)


class OverrideThreadingTests(unittest.IsolatedAsyncioTestCase):
    """Custom limits/override flow through the 5k + edge paths (no replay)."""

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

    def tearDown(self):
        from services import db
        from services.db import schema as db_schema

        self._offline.stop()
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._holder.cleanup()

    async def test_custom_limits_flow_through_without_replay(self):
        from unittest.mock import AsyncMock

        import tools.load_sim.driver as driver
        from tools.load_sim.driver import run_edge_scenario, run_load_5k

        tiny = {
            code: {"sessions": 1, "cards": 2}
            for code in ("free", "bronze", "silver", "gold", "emerald")
        }
        captured: dict = {}

        async def _fake_run(n, seed, bot, db, bot_mock, ai_mock, workload):
            captured["workload"] = workload
            return {"ok": True}

        with patch.object(driver, "_run", new=_fake_run):
            await run_edge_scenario(
                "gamer_herd", n=4, seed=1, db_path=self.db_path, plan_limits=tiny
            )
        workload = captured["workload"]
        self.assertEqual(len(workload), 4)
        for user in workload:
            self.assertEqual(user["sessions"], 1)
            self.assertEqual(user["session_cards"], [2])
            self.assertEqual(user["start_hours"], [18])

        sentinel = [{"plan": "free", "sessions": 1}]
        with patch.object(driver, "_run", new=_fake_run):
            await run_edge_scenario(
                "gamer_herd",
                n=4,
                seed=1,
                db_path=self.db_path,
                plan_limits=tiny,
                workload_override=sentinel,
            )
        self.assertIs(captured["workload"], sentinel)

        with patch.object(
            driver, "_run_5k", new=AsyncMock(return_value={"ok": True})
        ) as m5k:
            await run_load_5k(
                n=4, seed=1, db_path=self.db_path, plan_limits=tiny
            )
            self.assertEqual(m5k.call_args.args[8], tiny)
            self.assertIsNone(m5k.call_args.args[9])
        with patch.object(
            driver, "_run_5k", new=AsyncMock(return_value={"ok": True})
        ) as m5k_override:
            await run_load_5k(
                n=4, seed=1, db_path=self.db_path, workload_override=sentinel
            )
            self.assertIs(m5k_override.call_args.args[9], sentinel)


if __name__ == "__main__":
    unittest.main()
