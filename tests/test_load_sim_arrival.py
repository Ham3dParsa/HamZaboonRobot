"""RED test for the 100-user load-simulation arrival model (locked R1/R2).

Behavior spec: sample_workload(n, seed) assigns each synthetic user a plan
and a journey per the locked realistic mix, deterministically per seed.
This test must FAIL until tools/load_sim/plan_mix.py exists.
"""

import unittest


class TestLoadSimArrivalModel(unittest.TestCase):
    def test_plan_mix_matches_locked_distribution(self):
        from tools.load_sim.plan_mix import sample_workload

        users = sample_workload(n=100, seed=7)
        self.assertEqual(len(users), 100)
        plans = [u["plan"] for u in users]
        for code in ("free", "bronze", "silver", "gold", "emerald"):
            self.assertIn(code, plans)
        free_share = plans.count("free") / 100
        self.assertGreaterEqual(free_share, 0.60)
        self.assertLessEqual(free_share, 0.80)

    def test_same_seed_is_deterministic(self):
        from tools.load_sim.plan_mix import sample_workload

        first = sample_workload(n=100, seed=7)
        second = sample_workload(n=100, seed=7)
        self.assertEqual(first, second)

    def test_partial_sessions_and_queries_have_noise(self):
        from tools.load_sim.plan_mix import sample_workload

        users = sample_workload(n=100, seed=7)
        journeys = [u["journey"] for u in users]
        self.assertIn("partial", journeys)
        self.assertIn("word_query", journeys)


if __name__ == "__main__":
    unittest.main()
