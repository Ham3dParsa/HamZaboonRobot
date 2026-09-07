"""Capacity proof tests (locked plan scale/plan-load-sim-capacity, T1).

Harness-only: covers the R1 percentile summary, R2 CPU accounting helper,
R3 RAM-band verdicts, and R4 safety margin — plus two small deterministic
replays proving the driver reports them. Zero real AI tokens (same guards
as the load-sim flow tests); no production code touched.
"""

import unittest
from unittest.mock import MagicMock, patch

from tests.test_integration import helpers

PCT_KEYS = ("p50", "p90", "p95", "p99", "max", "count")


def _assert_ordered(test, pct):
    for key in PCT_KEYS:
        test.assertIn(key, pct)
    test.assertLessEqual(pct["p50"], pct["p90"])
    test.assertLessEqual(pct["p90"], pct["p95"])
    test.assertLessEqual(pct["p95"], pct["p99"])
    test.assertLessEqual(pct["p99"], pct["max"])


class CapacityPureTests(unittest.TestCase):
    def test_percentile_summary_fixed_values(self):
        from tools.load_sim.resources import p95_ms, percentile_summary

        pct = percentile_summary([float(v) for v in range(1, 101)])
        self.assertEqual(
            {k: pct[k] for k in PCT_KEYS},
            {
                "p50": 50.0,
                "p90": 90.0,
                "p95": 95.0,
                "p99": 99.0,
                "max": 100.0,
                "count": 100,
            },
        )
        self.assertEqual(pct["p95"], p95_ms([float(v) for v in range(1, 101)]))

    def test_percentile_summary_empty(self):
        from tools.load_sim.resources import percentile_summary

        self.assertEqual(
            percentile_summary([]),
            {
                "p50": 0.0,
                "p90": 0.0,
                "p95": 0.0,
                "p99": 0.0,
                "max": 0.0,
                "count": 0,
            },
        )

    def test_apply_margin_scales_by_1_5(self):
        from tools.load_sim.capacity import SAFETY_MARGIN, apply_margin

        self.assertEqual(SAFETY_MARGIN, 1.5)
        self.assertAlmostEqual(apply_margin(100.0), 150.0)
        self.assertAlmostEqual(apply_margin(0.0), 0.0)

    def test_cpu_clock_margin_is_explicit_2x(self):
        from tools.load_sim.capacity import CPU_CLOCK_MARGIN, capacity_for_cpu

        self.assertEqual(CPU_CLOCK_MARGIN, 2.0)
        # 1000 ms/s budget vs 100 ms/s per-user demand, doubled -> 5 users.
        self.assertEqual(capacity_for_cpu(1000.0, 100.0), 5)
        self.assertEqual(capacity_for_cpu(0.0, 100.0), 0)
        self.assertEqual(capacity_for_cpu(1000.0, 0.0), 0)
        self.assertEqual(capacity_for_cpu(-5.0, 100.0), 0)

    def test_verdict_for_bands_fixed_numbers_with_overlap(self):
        from tools.load_sim.capacity import verdict_for_bands

        # 80 + 0.5*100 (*2 overlap) = 180 raw; x1.5 margin = 270.
        out = verdict_for_bands(80.0, 0.5, 100)
        self.assertEqual(out[256]["verdict"], "fail")
        self.assertEqual(out[512]["verdict"], "pass")
        self.assertEqual(out[1024]["verdict"], "pass")
        for band in (256, 512, 1024):
            entry = out[band]
            self.assertAlmostEqual(entry["projected_mb"], 180.0)
            self.assertAlmostEqual(
                entry["projected_mb_margin_included"], 270.0
            )
            self.assertIn("180.00", entry["arithmetic"])
            self.assertIn("270.00", entry["arithmetic"])
            self.assertIn("margin-included", entry["arithmetic"])

    def test_verdict_for_bands_no_overlap(self):
        from tools.load_sim.capacity import verdict_for_bands

        # 80 + 0.5*100 (no overlap) = 130 raw; x1.5 margin = 195.
        out = verdict_for_bands(80.0, 0.5, 100, deploy_overlap_x2=False)
        self.assertEqual(out[256]["verdict"], "pass")
        self.assertAlmostEqual(
            out[256]["projected_mb_margin_included"], 195.0
        )


class CapacityDriverProofTests(unittest.IsolatedAsyncioTestCase):
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
        # Zero-real-token guards (same as the load-sim flow tests).
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

    async def test_run_load_reports_percentiles_and_cpu(self):
        from tools.load_sim.driver import run_load

        metrics = await run_load(
            n=20, seed=7, db_path=self.db_path, bot_mock=None, ai_mock=None
        )
        self.assertEqual(metrics["total"], 20)
        # R1: back-compat p95 plus the six-key summary, ordered.
        self.assertIn("grade_p95_ms", metrics)
        _assert_ordered(self, metrics["grade_pct"])
        self.assertGreater(metrics["grade_pct"]["count"], 0)
        self.assertEqual(
            metrics["grade_pct"]["count"], len(metrics["grade_latencies_ms"])
        )
        self.assertAlmostEqual(
            metrics["grade_pct"]["p95"], metrics["grade_p95_ms"]
        )
        # R2: CPU total plus per-kind split (or empty split when the
        # process CPU source is unavailable — keys still present).
        self.assertIn("cpu_total_ms", metrics)
        self.assertIn("cpu_ms_per_journey", metrics)
        self.assertIn("cpu_note", metrics)
        if metrics["cpu_total_ms"] is None:
            self.assertEqual(metrics["cpu_ms_per_journey"], {})
        else:
            self.assertGreaterEqual(metrics["cpu_total_ms"], 0.0)
            self.assertAlmostEqual(
                sum(metrics["cpu_ms_per_journey"].values()),
                metrics["cpu_total_ms"],
                places=3,
            )

    async def test_run_load_5k_reports_txn_and_lag_percentiles(self):
        from tools.load_sim.driver import run_load_5k

        metrics = await run_load_5k(
            n=20, seed=11, db_path=self.db_path, concurrency=2
        )
        self.assertEqual(metrics["total"], 20)
        for key in ("grade_pct", "txn_pct", "loop_lag_pct"):
            _assert_ordered(self, metrics[key])
        self.assertEqual(metrics["txn_pct"]["count"], 20)
        self.assertAlmostEqual(
            metrics["txn_pct"]["p95"], metrics["txn_p95_ms"]
        )
        self.assertAlmostEqual(
            metrics["loop_lag_pct"]["p95"],
            metrics["resources"]["loop_lag_p95_ms"],
        )
        self.assertEqual(
            metrics["resources"]["txn_pct"], metrics["txn_pct"]
        )
        self.assertEqual(
            metrics["resources"]["loop_lag_pct"], metrics["loop_lag_pct"]
        )
        self.assertIn("cpu_total_ms", metrics)
        self.assertIn("replay_wall_s", metrics)
        self.assertGreater(metrics["replay_wall_s"], 0.0)


if __name__ == "__main__":
    unittest.main()
