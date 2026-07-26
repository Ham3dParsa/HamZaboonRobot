"""Smoke test for scripts/simulate_srs.py.

Verifies the script runs without crash, produces expected output headers,
and produces byte-identical output when run twice with the same seed.
"""

import subprocess
import sys
import unittest


class SimulateSrsSmokeTest(unittest.TestCase):
    SCRIPT = ["python", "scripts/simulate_srs.py"]

    def _run(self, *extra_args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*self.SCRIPT, *extra_args],
            capture_output=True, text=True,
            cwd=sys.path[0] if sys.path[0] else None,
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
        from scripts.simulate_srs import parse_args, simulate
        args1 = parse_args(["--plan", "free", "--days", "10", "--seed", "42"])
        args2 = parse_args(["--plan", "free", "--days", "10", "--seed", "42"])
        rows1, sum1, _ = simulate(args1)
        rows2, sum2, _ = simulate(args2)
        self.assertEqual(rows1, rows2)
        self.assertEqual(sum1, sum2)


if __name__ == "__main__":
    unittest.main()
