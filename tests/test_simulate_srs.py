"""Smoke test for tools/srs_simulation — SRS v2.8 simulation tool.

Verifies the tool runs without crash, produces expected output headers,
and produces byte-identical output when run twice with the same seed.
"""

import os
import subprocess
import sys
import unittest


ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


class SimulateSrsSmokeTest(unittest.TestCase):
    MODULE = [sys.executable, "-m", "tools.srs_simulation"]

    def _run(self, *extra_args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*self.MODULE, *extra_args],
            capture_output=True, text=True,
            cwd=ROOT,
        )

    def test_runs_without_crash_free_plan(self):
        result = self._run("--plan", "free", "--days", "10", "--seed", "42")
        self.assertEqual(result.returncode, 0)

    def test_runs_without_crash_silver_plan(self):
        result = self._run("--plan", "silver", "--days", "10", "--seed", "42")
        self.assertEqual(result.returncode, 0)

    def test_runs_without_crash_gold_plan(self):
        result = self._run("--plan", "gold", "--days", "10", "--seed", "42")
        self.assertEqual(result.returncode, 0)

    def test_output_contains_expected_headers(self):
        result = self._run("--plan", "free", "--days", "10", "--seed", "42")
        self.assertIn("Day", result.stdout)
        self.assertIn("Backlog", result.stdout)
        self.assertIn("DueProc", result.stdout)
        self.assertIn("DueCarry", result.stdout)
        self.assertIn("Grad", result.stdout)
        self.assertIn("Final Summary", result.stdout)

    def test_deterministic_output_with_same_seed(self):
        result1 = self._run("--plan", "free", "--days", "10", "--seed", "42")
        result2 = self._run("--plan", "free", "--days", "10", "--seed", "42")
        self.assertEqual(result1.stdout, result2.stdout)
        self.assertEqual(result1.stderr, result2.stderr)

    def test_different_seed_produces_different_output(self):
        result1 = self._run("--plan", "free", "--days", "10", "--seed", "42")
        result2 = self._run("--plan", "free", "--days", "10", "--seed", "99")
        self.assertNotEqual(result1.stdout, result2.stdout)

    def test_overflow_threshold_flag_works(self):
        result = self._run(
            "--plan", "free", "--days", "30", "--seed", "42",
            "--overflow-session-threshold", "10",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("overflow", result.stdout.lower())

    def test_csv_output_flag(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name
        try:
            result = self._run(
                "--plan", "free", "--days", "10", "--seed", "42",
                "--csv", csv_path,
            )
            self.assertEqual(result.returncode, 0)
            self.assertTrue(os.path.exists(csv_path))
            with open(csv_path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("day,backlog", content)
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_summary_rejection_pct(self):
        result = self._run("--plan", "free", "--days", "30", "--seed", "42")
        self.assertIn("rejection", result.stdout.lower())
        self.assertIn("%", result.stdout)

    def test_summary_carry_streak(self):
        result = self._run("--plan", "free", "--days", "30", "--seed", "42")
        self.assertIn("carry streak", result.stdout.lower())
        self.assertIn("days", result.stdout.lower())

    def test_summary_avg_backlog(self):
        result = self._run("--plan", "free", "--days", "30", "--seed", "42")
        self.assertIn("average backlog", result.stdout.lower())
        self.assertIn("7", result.stdout.lower())

    def test_simulate_function_repeatable(self):
        from tools.srs_simulation.simulator import SimConfig, simulate
        cfg1 = SimConfig(plan="free", days=10, seed=42)
        cfg2 = SimConfig(plan="free", days=10, seed=42)
        rows1, sum1, _ = simulate(cfg1)
        rows2, sum2, _ = simulate(cfg2)
        self.assertEqual(rows1, rows2)
        self.assertEqual(sum1, sum2)


if __name__ == "__main__":
    unittest.main()
