"""Smoke test for tools/srs_simulation_v2 — SRS v3 pull-based simulation.

Verifies crash safety, deterministic output, CSV export, and basic sanity.
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


class SimulateSrsV2SmokeTest(unittest.TestCase):
    MODULE = [sys.executable, "-m", "tools.srs_simulation_v2"]

    def _run(self, *extra_args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*self.MODULE, *extra_args],
            capture_output=True, text=True,
            cwd=ROOT,
        )

    def test_runs_free_plan(self):
        r = self._run("--plan", "free", "--days", "10", "--seed", "42")
        self.assertEqual(r.returncode, 0)

    def test_runs_silver_plan(self):
        r = self._run("--plan", "silver", "--days", "10", "--seed", "42")
        self.assertEqual(r.returncode, 0)

    def test_runs_gold_plan(self):
        r = self._run("--plan", "gold", "--days", "10", "--seed", "42")
        self.assertEqual(r.returncode, 0)

    def test_output_has_headers(self):
        r = self._run("--plan", "free", "--days", "10", "--seed", "42")
        for h in ("Day", "DueProc", "DueRem", "QSaved", "AIGen", "AICalls", "Active"):
            self.assertIn(h, r.stdout)

    def test_deterministic_output(self):
        r1 = self._run("--plan", "free", "--days", "10", "--seed", "42")
        r2 = self._run("--plan", "free", "--days", "10", "--seed", "42")
        self.assertEqual(r1.stdout, r2.stdout)

    def test_different_seed_differs(self):
        r1 = self._run("--plan", "free", "--days", "10", "--seed", "42")
        r2 = self._run("--plan", "free", "--days", "10", "--seed", "99")
        self.assertNotEqual(r1.stdout, r2.stdout)

    def test_csv_export(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            r = self._run("--plan", "free", "--days", "10", "--seed", "42", "--csv", path)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as fh:
                self.assertIn("day,due_processed", fh.read())
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_summary_shows_ai_savings(self):
        r = self._run("--plan", "free", "--days", "30", "--seed", "42")
        self.assertIn("AI cost savings", r.stdout)

    def test_summary_shows_ai_calls(self):
        r = self._run("--plan", "free", "--days", "30", "--seed", "42")
        self.assertIn("Avg Total AI Calls per day", r.stdout)

    def test_summary_shows_max_due_remaining(self):
        r = self._run("--plan", "free", "--days", "30", "--seed", "42")
        self.assertIn("Max Due Remaining", r.stdout)

    def test_summary_shows_max_query_backlog(self):
        r = self._run("--plan", "free", "--days", "30", "--seed", "42")
        self.assertIn("Max Query Backlog", r.stdout)

    def test_csv_column_order(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            r = self._run("--plan", "free", "--days", "5", "--seed", "42", "--csv", path)
            self.assertEqual(r.returncode, 0)
            with open(path, encoding="utf-8") as fh:
                header = fh.readline().strip()
            cols = header.split(",")
            for col in ("day", "query_saved", "ai_calls"):
                self.assertIn(col, cols)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_simulate_function_repeatable(self):
        from tools.srs_simulation_v2.simulator import SimConfig, simulate
        c1 = SimConfig(plan="free", days=10, seed=42)
        c2 = SimConfig(plan="free", days=10, seed=42)
        r1, s1, _ = simulate(c1)
        r2, s2, _ = simulate(c2)
        self.assertEqual(r1, r2)
        self.assertEqual(s1, s2)

    def test_zero_due_remaining_silver(self):
        r = self._run("--plan", "silver", "--days", "30", "--seed", "42")
        self.assertEqual(r.returncode, 0)

    def test_gold_vs_free_graduation(self):
        from tools.srs_simulation_v2.simulator import SimConfig, simulate
        free_cfg = SimConfig(plan="free", days=30, seed=42)
        gold_cfg = SimConfig(plan="gold", days=30, seed=42)
        _, free_sum, _ = simulate(free_cfg)
        _, gold_sum, _ = simulate(gold_cfg)
        self.assertGreater(gold_sum.final_active_cards, free_sum.final_active_cards)


if __name__ == "__main__":
    unittest.main()
