"""Proof tests for the peak-window concurrent probe (T12, hybrid H1-H3).

Harness-only: tiny synthetic timelines (small cohorts, few days, minimal
``fast_scale``) assert the pre-scan finds windows, each window replays
CONCURRENTLY (``max_inflight > 1``), and per-window pressure metrics plus
the overlap histogram are recorded. No production code touched; zero real
AI tokens.
"""

import unittest
from unittest.mock import MagicMock, patch

from tests.test_integration import helpers


class PeakProbeTests(unittest.IsolatedAsyncioTestCase):
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

    def test_histogram_and_window_slice_are_pure(self):
        from tools.load_sim.multiday import build_cohort
        from tools.load_sim.peak_probe import overlap_histogram, window_events
        from tools.load_sim.timeline import (
            compile_timeline,
            scan_top_windows,
        )

        cohort = build_cohort(n=6, seed=7)
        events = compile_timeline(
            cohort, days=2, seed=7, anchor_today_iso="2026-03-01"
        )
        self.assertGreater(len(events), 0)
        windows = scan_top_windows(events, top_k=2)
        self.assertGreater(len(windows), 0)
        for win in windows:
            sliced = window_events(
                events, win["window_start_vtime"], 900.0
            )
            self.assertEqual(len(sliced), win["count"])
            self.assertTrue(
                all(
                    win["window_start_vtime"]
                    <= e["vtime"]
                    <= win["window_start_vtime"] + 900.0
                    for e in sliced
                )
            )
        hist = overlap_histogram(events)
        self.assertGreater(hist["buckets"], 0)
        self.assertEqual(hist["total"], len(events))
        self.assertEqual(sum(hist["per_minute_counts"]), len(events))
        self.assertGreaterEqual(hist["max"], hist["p95"])
        self.assertGreaterEqual(hist["p95"], hist["p50"])
        empty = overlap_histogram([])
        self.assertEqual(empty["buckets"], 0)
        self.assertEqual(empty["per_minute_counts"], [])

    def test_edge_peaks_cover_all_three_herds(self):
        from tools.load_sim.peak_probe import compile_edge_peaks
        from tools.load_sim.plan_mix import EDGE_SCENARIOS

        peaks = compile_edge_peaks(
            n_edge=4, seed=7, anchor_today_iso="2026-03-01", days=2
        )
        self.assertEqual(set(peaks.keys()), set(EDGE_SCENARIOS))
        for name in EDGE_SCENARIOS:
            self.assertGreater(len(peaks[name]["events"]), 0)
            self.assertIsNotNone(peaks[name]["window"])
            self.assertGreaterEqual(peaks[name]["window"]["count"], 1)

    async def test_peak_windows_probed_concurrently_with_metrics(self):
        from tools.load_sim.multiday import build_cohort
        from tools.load_sim.peak_probe import compile_edge_peaks, run_peak_probe
        from tools.load_sim.timeline import compile_timeline

        cohort = build_cohort(n=6, seed=7)
        events = compile_timeline(
            cohort, days=2, seed=7, anchor_today_iso="2026-03-01"
        )
        peaks = compile_edge_peaks(
            n_edge=4, seed=7, anchor_today_iso="2026-03-01", days=2
        )
        edge_events = {name: peaks[name]["events"] for name in peaks}
        result = await run_peak_probe(
            events,
            self.db_path,
            seed=7,
            concurrency=20,
            top_k=2,
            fast_scale=0.0001,
            edge_events=edge_events,
            baseline_cap=10,
        )
        self.assertEqual(result["concurrency"], 20)
        sources = {w["source"] for w in result["windows"]}
        self.assertIn("prescan_top0", sources)
        for name in edge_events:
            self.assertIn(name, sources)
        for window in result["windows"]:
            for key in (
                "window_start_vtime",
                "day_iso",
                "count",
                "participants",
                "events_probed",
                "errors",
                "db_busy_retries",
                "busy_retry_rate",
                "txn_p95_ms",
                "loop_lag_p95_ms",
                "max_inflight",
            ):
                self.assertIn(key, window)
            self.assertGreaterEqual(window["participants"], 1)
            self.assertGreater(window["events_probed"], 0)
            self.assertGreaterEqual(window["busy_retry_rate"], 0.0)
            self.assertGreaterEqual(window["txn_p95_ms"], 0.0)
            self.assertGreaterEqual(window["loop_lag_p95_ms"], 0.0)
        probed_windows = [
            w for w in result["windows"] if w["events_probed"] > 1
        ]
        self.assertGreater(len(probed_windows), 0)
        self.assertTrue(
            any(w["max_inflight"] > 1 for w in probed_windows),
            "at least one multi-event window must show concurrent in-flight",
        )
        hist = result["overlap_histogram"]
        self.assertGreater(hist["buckets"], 0)
        self.assertEqual(hist["total"], len(events))
        self.assertIn("events_probed", result["baseline"])
        self.assertGreaterEqual(result["baseline"]["txn_p95_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
