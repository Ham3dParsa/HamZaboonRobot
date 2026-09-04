"""5k load-simulation small-scale proof (locked plan scale/plan-load-sim-5k, T1).

Drives ``tools.load_sim.driver.run_load_5k`` with n=200 seed=11 through the
REAL routers on an isolated SQLite file (snapshot-DB isolation via
``tests/test_integration/helpers.py``), with all Telegram sends and AI steps
mocked (AI budget: 0 real tokens).

Locked R3 gates, scaled for the proof slice:
- grade-path p95 under 1500ms,
- db busy-retry under 1% of txns,
- zero correctness violations (quota double-spend, report loss,
  card lookup miss, grade check failure),
- resources dict present with sane keys.

Full n=2800 runs in T2, not in CI: this proof stays under ~60s.
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from tests.test_integration import helpers


class LoadSim5kFlowTests(unittest.IsolatedAsyncioTestCase):
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
        # Zero-real-token guard: any reach of the real provider fails loudly.
        # ask_card patch alone never fires (the bypass raises earlier at
        # llm_services get_chain), so also guard _call_ai_limited directly.
        self._no_real_ai = patch(
            "services.ai.ai.ask_card",
            new=MagicMock(side_effect=AssertionError("real AI must not run")),
        )
        self._no_real_ai.start()
        self._no_real_limited = patch(
            "services.ai.llm_services._call_ai_limited",
            new=MagicMock(side_effect=AssertionError("real AI must not run")),
        )
        self._no_real_limited.start()

    def tearDown(self):
        from services import db
        from services.db import schema as db_schema

        self._no_real_limited.stop()
        self._no_real_ai.stop()
        self._offline.stop()
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._holder.cleanup()

    async def test_5k_driver_proof_slice_meets_scaled_r3_gates(self):
        from tools.load_sim.driver import run_load_5k

        t0 = time.perf_counter()
        # Proof-scale overlap: 10-way (driver default stays 50 for T2 full
        # runs). 50-way on one SQLite file saturates the single event loop
        # with synchronous handler/DB slices; 10-way keeps real contention
        # while fitting the scaled latency gate and the ~60s CI budget.
        metrics = await run_load_5k(
            n=200, seed=11, db_path=self.db_path, concurrency=10
        )
        wall_s = time.perf_counter() - t0
        print(f"\n[load-sim-5k-proof] n=200 wall={wall_s:.1f}s")
        print(
            "[load-sim-5k-proof] grade_p95={:.1f}ms txn_p95={:.1f}ms "
            "lag_p95={:.1f}ms busy={} errors={} err_rate={:.4f} "
            "real_grades={} ai_timeouts={} ai_error={} word_query_ok={} "
            "tg429={} counts={}".format(
                metrics["grade_p95_ms"],
                metrics["resources"]["txn_p95_ms"],
                metrics["resources"]["loop_lag_p95_ms"],
                metrics["db_busy_retries"],
                metrics["errors"],
                metrics["error_rate"],
                metrics["real_grades"],
                metrics["ai_timeouts"],
                metrics["ai_error"],
                metrics["word_query_ok"],
                metrics["telegram_429"],
                metrics["journey_counts"],
            )
        )

        self.assertEqual(metrics["total"], 200)
        for key in (
            "telegram_429",
            "telegram_retries",
            "db_busy_retries",
            "ai_timeouts",
            "ai_error",
            "word_query_ok",
            "quota_double_spend",
            "report_loss",
            "card_lookup_miss",
            "grade_check_failed",
            "real_grades",
            "grade_p95_ms",
            "error_rate",
            "resources",
        ):
            self.assertIn(key, metrics)

        self.assertLess(
            metrics["grade_p95_ms"],
            1500,
            f"grade-path p95 under 1500ms, got {metrics['grade_p95_ms']:.1f}ms",
        )
        self.assertLess(
            metrics["db_busy_retries"] / max(1, metrics["total"]),
            0.01,
            f"busy-retry under 1% of txns, got {metrics['db_busy_retries']}",
        )
        self.assertEqual(
            metrics["quota_double_spend"], 0, "zero quota double-spend"
        )
        self.assertEqual(metrics["report_loss"], 0, "zero report loss")
        self.assertEqual(
            metrics["card_lookup_miss"], 0, "zero card lookup miss"
        )
        self.assertEqual(
            metrics["grade_check_failed"], 0, "zero grade check failure"
        )
        self.assertGreater(
            metrics["real_grades"], 0, "at least one real grade reached production"
        )
        self.assertEqual(metrics["ai_error"], 0, "zero ai_error: no real-path failure")
        self.assertGreater(
            metrics["word_query_ok"],
            0,
            "at least one word_query journey delivered ok via the mock",
        )
        self.assertLess(
            metrics["error_rate"], 0.01, f"error rate under 1%, got {metrics['error_rate']:.4f}"
        )

        resources = metrics["resources"]
        for key in (
            "rss_before",
            "rss_after",
            "rss_delta",
            "loop_lag_p95_ms",
            "db_bytes",
            "wal_bytes",
            "txn_p95_ms",
        ):
            self.assertIn(key, resources)
            self.assertGreaterEqual(resources[key], 0)
        self.assertGreater(resources["rss_after"], 0)
        self.assertGreater(resources["db_bytes"], 0)
        self.assertEqual(
            resources["rss_delta"],
            resources["rss_after"] - resources["rss_before"],
        )
        self.assertLess(
            wall_s, 60, f"proof slice must stay under ~60s, took {wall_s:.1f}s"
        )


if __name__ == "__main__":
    unittest.main()
