"""Proof tests for the capped load-sim runner (locked plan scale/plan-load-sim-capacity, T4 C3).

CI-fast by default: unit tests (cap triplet, child OOM, counters flow)
plus one small capped replay (n=12, generous caps) asserting metrics are
present. The four full capped runs (100-user + 5k-peak x tiny/safe) run
ONLY with ``HAMZABAN_CAPPED_FULL=1`` (optional ``HAMZABAN_CAPPED_RUNS``
comma subset of ``100-safe,100-tiny,5k-safe,5k-tiny``); they write results
incrementally to ``hamzaban_capped_runs.json`` in the temp dir and skip
entries already present, so partial progress survives a timeout.

Harness-only: no production code touched, zero real AI tokens (child
thunks carry the same zero-token guards as the load-sim flow tests).
"""

import json
import os
import sys
import tempfile
import time
import unittest

WINDOWS = sys.platform == "win32"

RESULTS_NAME = "hamzaban_capped_runs.json"

# (run_id, kind, cap_name, thunk_kwargs, timeout_s)
FULL_RUNS = [
    ("100-safe", "100", "safe", {"seed": 7}, 900),
    ("100-tiny", "100", "tiny", {"seed": 7}, 900),
    ("5k-safe", "5k", "safe", {"n": 2800, "seed": 7, "concurrency": 50}, 1800),
    ("5k-tiny", "5k", "tiny", {"n": 2800, "seed": 7, "concurrency": 50}, 1800),
]

ENVELOPE_KEYS = (
    "ok",
    "result",
    "error",
    "wall_s",
    "rss_before",
    "rss_after",
    "cpu_percent",
    "ram_cap_bytes",
    "headroom_bytes",
    "killed",
    "timed_out",
    "cpu_throttled",
    "caps_enforced",
    "mode",
    "cap_error",
)


class CappedRunnerProofTests(unittest.TestCase):
    def test_cap_triplet_applies(self):
        from tools.load_sim import capped

        if not WINDOWS:
            # Job Objects are Windows-only: prove the honest fallback
            # labeling (affinity-estimate, caps NOT enforced, error names
            # the failing API) via a thunk that needs no caps.
            env = capped.run_capped(
                capped.echo_counters,
                {"probe": 1},
                cpu_percent=100,
                ram_bytes=1024**3,
                timeout_s=180,
            )
            for key in ENVELOPE_KEYS:
                self.assertIn(key, env)
            self.assertFalse(env["killed"])
            self.assertTrue(env["ok"], f"fallback probe failed: {env['error']}")
            self.assertFalse(env["caps_enforced"])
            self.assertIn(env["mode"], ("affinity-estimate", "none"))
            self.assertIsNotNone(env["cap_error"])
            return

        env = capped.run_capped(
            capped.apply_and_report,
            50,
            512 * 1024**2,
            cpu_percent=100,
            ram_bytes=1024**3,
            timeout_s=180,
        )
        for key in ENVELOPE_KEYS:
            self.assertIn(key, env)
        self.assertFalse(env["killed"], f"cap probe child died: {env['error']}")
        self.assertTrue(env["ok"], f"cap probe failed: {env['error']}")
        self.assertEqual(env["mode"], "job-objects")
        self.assertTrue(env["caps_enforced"])
        readback = env["result"]["readback"]
        self.assertEqual(readback["process_memory_limit"], 512 * 1024**2)
        self.assertEqual(readback["cpu_rate"], 50 * 100)

    def test_child_oom_reported_not_crashed(self):
        from tools.load_sim import capped

        env = capped.run_capped(
            capped.child_allocate_mb,
            512,
            cpu_percent=100,
            ram_bytes=128 * 1024**2,
            timeout_s=180,
        )
        for key in ENVELOPE_KEYS:
            self.assertIn(key, env)
        # The parent (this test) survived — that IS the assertion that the
        # OOM did not crash the runner. Under a real Job Object RAM cap the
        # child either dies (killed=True) or raises MemoryError into the
        # envelope; without enforcement there is nothing to trip.
        if not WINDOWS:
            self.skipTest("RAM caps need Windows Job Objects")
        tripped = env["killed"] or (
            not env["ok"]
            and env["error"] is not None
            and "memory" in env["error"].lower()
        )
        self.assertTrue(
            tripped,
            f"512MiB alloc under a 128MiB cap must trip; envelope={env}",
        )

    def test_counters_flow_through_child(self):
        from tools.load_sim import capped

        payload = {"word_query_ok": 7, "real_grades": 3, "errors": 0}
        env = capped.run_capped(
            capped.echo_counters,
            payload,
            cpu_percent=100,
            ram_bytes=1024**3,
            timeout_s=180,
        )
        self.assertTrue(env["ok"], f"echo child failed: {env['error']}")
        self.assertFalse(env["killed"])
        self.assertEqual(env["result"], payload)

    def test_small_capped_replay_metrics_present(self):
        from tests.test_integration import helpers
        from tools.load_sim import capped

        holder, db_path = helpers.fresh_db_from_snapshot()
        try:
            env = capped.run_capped(
                capped.replay_100,
                db_path,
                cpu_percent=90,
                ram_bytes=1536 * 1024**2,
                timeout_s=600,
                seed=7,
                sleep_scale=1.0,
                n=12,
            )
        finally:
            holder.cleanup()
        self.assertFalse(env["killed"], f"small replay child died: {env['error']}")
        self.assertTrue(env["ok"], f"small replay failed: {env['error']}")
        metrics = env["result"]
        for key in (
            "total",
            "errors",
            "error_rate",
            "grade_latencies_ms",
            "grade_p95_ms",
            "real_grades",
            "quota_double_spend",
            "report_loss",
            "journey_counts",
        ):
            self.assertIn(key, metrics)
        self.assertEqual(metrics["total"], 12)
        self.assertGreater(metrics["real_grades"], 0)


@unittest.skipUnless(
    os.getenv("HAMZABAN_CAPPED_FULL") == "1",
    "full capped runs only with HAMZABAN_CAPPED_FULL=1",
)
class CappedFullRunsTests(unittest.TestCase):
    def test_four_capped_runs(self):
        from tests.test_integration import helpers
        from tools.load_sim import capped

        only = os.getenv("HAMZABAN_CAPPED_RUNS")
        wanted = (
            {r.strip() for r in only.split(",") if r.strip()} if only else None
        )
        out_path = os.path.join(tempfile.gettempdir(), RESULTS_NAME)
        try:
            with open(out_path, encoding="utf-8") as fh:
                collected = json.load(fh)
        except (OSError, ValueError):
            collected = {}

        for run_id, kind, cap_name, thunk_kwargs, timeout_s in FULL_RUNS:
            if wanted is not None and run_id not in wanted:
                continue
            if run_id in collected:
                continue
            cap = dict(capped.SAFE_ZONE if cap_name == "safe" else capped.TINY_BOX)
            thunk = capped.replay_100 if kind == "100" else capped.replay_5k
            thunk_kwargs = dict(
                thunk_kwargs, sleep_scale=capped.SLEEP_SCALE
            )
            holder, db_path = helpers.fresh_db_from_snapshot()
            try:
                t0 = time.perf_counter()
                env = capped.run_capped(
                    thunk,
                    db_path,
                    cpu_percent=cap["cpu_percent"],
                    ram_bytes=cap["ram_bytes"],
                    timeout_s=timeout_s,
                    **thunk_kwargs,
                )
                # Parent-side wall (includes spawn + import overhead).
                parent_wall_s = time.perf_counter() - t0
            finally:
                holder.cleanup()
            record = {"run_id": run_id, "kind": kind, "cap": cap_name,
                      "cap_spec": cap, "envelope": _jsonable(env)}
            metrics = env.get("result") if isinstance(env.get("result"), dict) else None
            if metrics is not None:
                grades = list(metrics.get("grade_latencies_ms") or [])
                record["summary"] = {
                    "total": metrics.get("total"),
                    "errors": metrics.get("errors"),
                    "error_rate": metrics.get("error_rate"),
                    "grade_n": len(grades),
                    "grade_ms": capped.percentiles_ms(grades),
                    "telegram_429": metrics.get("telegram_429"),
                    "telegram_retries": metrics.get("telegram_retries"),
                    "db_busy_retries": metrics.get("db_busy_retries"),
                    "ai_timeouts": metrics.get("ai_timeouts"),
                    "ai_error": metrics.get("ai_error"),
                    "word_query_ok": metrics.get("word_query_ok"),
                    "quota_double_spend": metrics.get("quota_double_spend"),
                    "report_loss": metrics.get("report_loss"),
                    "real_grades": metrics.get("real_grades"),
                    "card_lookup_miss": metrics.get("card_lookup_miss"),
                    "grade_check_failed": metrics.get("grade_check_failed"),
                    "journey_counts": metrics.get("journey_counts"),
                    "child_wall_s": env.get("wall_s"),
                    "parent_wall_s": parent_wall_s,
                    "killed": env.get("killed"),
                    "timed_out": env.get("timed_out"),
                    "rss_after": env.get("rss_after"),
                    "headroom_bytes": env.get("headroom_bytes"),
                    "mode": env.get("mode"),
                }
                summ = record["summary"]
                print(
                    "\n[capped-run] id={} cap={}({}%cpu/{}MB) n={} "
                    "p50={:.1f} p95={:.1f} p99={:.1f}ms errors={} "
                    "err_rate={:.4f} child_wall={:.1f}s parent_wall={:.1f}s "
                    "killed={} timeout={} headroom={}MB grades={} "
                    "ds={} loss={} busy={}".format(
                        run_id,
                        cap_name,
                        cap["cpu_percent"],
                        cap["ram_bytes"] // 1024**2,
                        summ["total"],
                        summ["grade_ms"]["p50"],
                        summ["grade_ms"]["p95"],
                        summ["grade_ms"]["p99"],
                        summ["errors"],
                        summ["error_rate"] or 0.0,
                        summ["child_wall_s"] or 0.0,
                        parent_wall_s,
                        summ["killed"],
                        summ["timed_out"],
                        _mb(summ["headroom_bytes"]),
                        summ["real_grades"],
                        summ["quota_double_spend"],
                        summ["report_loss"],
                        summ["db_busy_retries"],
                    )
                )
            else:
                record["summary"] = {
                    "ok": env.get("ok"),
                    "error": env.get("error"),
                    "killed": env.get("killed"),
                    "timed_out": env.get("timed_out"),
                    "parent_wall_s": parent_wall_s,
                    "mode": env.get("mode"),
                }
                print(f"\n[capped-run] id={run_id} NO METRICS: {record['summary']}")
            collected[run_id] = record
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(collected, fh, indent=1)
            print(f"[capped-run] results so far -> {out_path}")

        self.assertTrue(collected, "no capped runs executed")


def _jsonable(obj):
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return {"unjsonable": repr(obj)}


def _mb(value):
    if value is None:
        return "n/a"
    return f"{value / 1024**2:.1f}"


if __name__ == "__main__":
    unittest.main()
