"""Proof tests for full-fidelity 60-day load simulation (round 2, T4: F1-F4).

Harness-only: F1 full-fidelity day replay through the real routers (fast
pure-draws mode stays the CI default; fidelity gated behind its own entry
point), F2 patient word-query mock (p50 ~1.5s / p95 ~8s at scale 1.0, FAST
factor for practical runtimes, production-shaped cards, save taps), F3
night-owl 24h spread with a small midnight mass, F4 budget (full 60-day
fidelity is measurement-only and skipped in CI by default; CI keeps a tiny
miniature proving the path). No production code touched; zero real AI tokens.
"""

import os
import random
import statistics
import unittest
from unittest.mock import MagicMock, patch

from tests.test_integration import helpers


class NightOwlScheduleTests(unittest.TestCase):
    def test_midnight_mass_small_but_present(self):
        from tools.load_sim.plan_mix import sample_day_start_hours

        rng = random.Random(42)
        hours = []
        for _ in range(400):
            hours.extend(sample_day_start_hours("average", 3, rng))
        self.assertEqual(len(hours), 1200)
        night = sum(1 for h in hours if 0 <= h <= 5)
        # Documented small midnight mass (~4% for average): bound it loosely.
        self.assertGreater(night, 0)
        self.assertLess(night / len(hours), 0.10)

    def test_persona_weighted_gamer_up_later_than_lazy(self):
        from tools.load_sim.plan_mix import night_owl_prob

        self.assertGreater(night_owl_prob("gamer"), night_owl_prob("lazy"))
        self.assertGreater(night_owl_prob("eager"), night_owl_prob("lazy"))
        # Mix-weighted mean stays a small mass.
        self.assertAlmostEqual(night_owl_prob("unknown"), 0.05)

    def test_day_band_covers_24h_never_hour_6(self):
        from tools.load_sim.plan_mix import sample_day_start_hours

        rng = random.Random(7)
        seen: set[int] = set()
        for _ in range(300):
            seen.update(sample_day_start_hours("gamer", 4, rng))
        self.assertTrue(any(h <= 5 for h in seen))
        self.assertTrue(any(h >= 7 for h in seen))
        self.assertNotIn(6, seen)

    def test_start_hours_sorted_and_deterministic(self):
        from tools.load_sim.plan_mix import sample_day_start_hours

        first = sample_day_start_hours("eager", 3, random.Random(9))
        second = sample_day_start_hours("eager", 3, random.Random(9))
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))
        self.assertEqual(len(first), 3)

    def test_replay_order_sorted_by_hour_then_user(self):
        from tools.load_sim.plan_mix import build_day_replay_order

        order = build_day_replay_order([(3, 18), (1, 2), (2, 18)])
        self.assertEqual(order, [(1, 2), (2, 18), (3, 18)])


class PatientMockTests(unittest.TestCase):
    def test_delay_shape_p50_p95_at_scale_one(self):
        from tools.load_sim.driver import patient_delay_seconds

        rng = random.Random(1234)
        draws = sorted(patient_delay_seconds(rng) for _ in range(2000))
        p50 = statistics.median(draws)
        p95 = draws[int(0.95 * len(draws))]
        self.assertGreater(p50, 1.0)
        self.assertLess(p50, 2.1)
        self.assertGreater(p95, 5.0)
        self.assertLess(p95, 11.0)

    def test_fast_scale_documented_tiny(self):
        from tools.load_sim.driver import PATIENT_FAST_SCALE

        self.assertGreater(PATIENT_FAST_SCALE, 0.0)
        self.assertLessEqual(PATIENT_FAST_SCALE, 0.05)

    def test_patient_card_shape_and_word_override(self):
        from tools.load_sim.driver import PATIENT_CARDS, patient_card_for

        for card in PATIENT_CARDS:
            for key in (
                "word",
                "phonetic",
                "fa_meaning",
                "examples",
                "example_translations",
                "synonyms",
                "grammar_tip",
            ):
                self.assertIn(key, card)
            self.assertGreaterEqual(len(card["examples"]), 1)
            self.assertEqual(
                len(card["examples"]), len(card["example_translations"])
            )
        card = patient_card_for("fidelitytest", random.Random(1))
        self.assertEqual(card["word"], "fidelitytest")
        again = patient_card_for("fidelitytest", random.Random(999))
        self.assertEqual(
            {k: v for k, v in card.items() if k != "word"},
            {k: v for k, v in again.items() if k != "word"},
        )

    def test_patient_fake_answers_word_and_counts_timeouts(self):
        import threading

        from tools.load_sim.driver import make_patient_replay_ai_fakes

        counters = {"ai_timeouts": 0}
        step, prep = make_patient_replay_ai_fakes(
            seed=5, counters=counters, lock=threading.Lock(), fast_scale=0.0001
        )
        card = step(object(), user_prompt="fidelityword", user_id=900001)
        self.assertEqual(card["word"], "fidelityword")
        self.assertEqual(prep(card)["word"], "fidelityword")
        timeouts = 0
        for i in range(300):
            try:
                step(object(), user_prompt=f"w{i}", user_id=900002)
            except Exception as exc:
                if isinstance(exc, TimeoutError) or type(exc).__name__ == (
                    "TimeoutError"
                ):
                    timeouts += 1
        # Small timeout rate (~3%): some fire, few dominate.
        self.assertGreater(timeouts, 0)
        self.assertLess(timeouts, 60)
        with self.assertRaises(ValueError):
            make_patient_replay_ai_fakes(
                seed=5, counters=counters, lock=threading.Lock(), fast_scale=0
            )


class FidelityActionsPureTests(unittest.TestCase):
    def test_actions_match_pure_totals_and_hour_order(self):
        from tools.load_sim.multiday import (
            build_cohort,
            fidelity_actions_for_day,
            simulate_day,
        )

        cohort = build_cohort(n=30, seed=11)
        actions, totals = fidelity_actions_for_day(cohort, 3, seed=11)
        pure = simulate_day(cohort, 3, seed=11)
        self.assertEqual(totals["active"], pure["active"])
        self.assertEqual(totals["sessions"], pure["sessions"])
        self.assertEqual(totals["queries"], pure["queries"])
        self.assertEqual(totals["abandons"], pure["abandons"])
        self.assertEqual(len(actions), pure["active"])
        self.assertEqual(
            [a["user_id"] for a in actions], sorted(
                [a["user_id"] for a in actions],
                key=lambda uid: (
                    next(
                        a["first_hour"]
                        for a in actions
                        if a["user_id"] == uid
                    ),
                    uid,
                ),
            )
        )
        self.assertEqual(
            totals["first_hours"], sorted(totals["first_hours"])
        )

    def test_fidelity_words_unique_and_alpha(self):
        from tools.load_sim.multiday import fidelity_grade_word, fidelity_word

        words = {
            fidelity_word(d, u, q)
            for d in range(3)
            for u in range(6)
            for q in range(3)
        }
        self.assertEqual(len(words), 3 * 6 * 3)
        for word in words:
            self.assertTrue(word.isalpha(), word)
        grades = {fidelity_grade_word(d, u) for d in range(3) for u in range(6)}
        self.assertEqual(len(grades), 18)
        self.assertTrue(words.isdisjoint(grades))


class FidelityMiniatureTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_tiny_fidelity_miniature_proves_path(self):
        from tools.load_sim.multiday import run_multiday_fidelity

        result = await run_multiday_fidelity(
            n=4,
            seed=11,
            db_path=self.db_path,
            days=3,
            patient=True,
            fast_scale=0.0001,
            query_cap=1,
        )
        self.assertEqual(result["mode"], "fidelity")
        self.assertEqual(result["days"], 3)
        self.assertEqual(len(result["fidelity_days"]), 3)
        self.assertEqual(len(result["day_totals"]), 3)
        self.assertEqual(len(result["growth_curve_bytes"]), 3)
        self.assertEqual(len(result["backup_runs"]), 2)
        self.assertEqual(result["violations"], [])
        for fday in result["fidelity_days"]:
            self.assertEqual(fday["mode"], "fidelity")
            self.assertTrue(fday["patient"])
            self.assertEqual(fday["errors"], 0)
            self.assertEqual(
                fday["first_hours"], sorted(fday["first_hours"])
            )
        replayed = sum(
            f["sessions_replayed"] + f["queries_replayed"]
            for f in result["fidelity_days"]
        )
        self.assertGreater(replayed, 0)
        self.assertGreater(
            sum(f["real_grades"] for f in result["fidelity_days"]), 0
        )


@unittest.skipUnless(
    os.environ.get("LOAD_SIM_FULL") == "1",
    "full 60-day fidelity run is measurement-only (F4); "
    "set LOAD_SIM_FULL=1 to run it",
)
class FullSixtyDayFidelitySlowTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_full_60day_fidelity_measurement_only(self):
        from tools.load_sim.multiday import run_multiday_fidelity

        result = await run_multiday_fidelity(
            n=200, seed=7, db_path=self.db_path, days=60
        )
        self.assertEqual(result["days"], 60)
        self.assertEqual(len(result["fidelity_days"]), 60)
        self.assertEqual(result["violations"], [])


if __name__ == "__main__":
    unittest.main()
