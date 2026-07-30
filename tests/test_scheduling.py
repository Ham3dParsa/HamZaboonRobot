import unittest

from services.scheduling import (
    PLAN_SESSION_CONFIG,
    daily_session_budget,
    consume_session_slot,
    release_session_slot,
)


class TestScheduling(unittest.TestCase):
    def test_plan_session_config_has_expected_plans(self):
        expected = {"free", "silver", "gold"}
        self.assertEqual(set(PLAN_SESSION_CONFIG), expected)

    def test_plan_session_config_positive_values(self):
        for plan, count in PLAN_SESSION_CONFIG.items():
            with self.subTest(plan=plan):
                self.assertGreater(count, 0)

    def test_daily_session_budget_silver(self):
        result = daily_session_budget(123, "silver")
        self.assertEqual(result["total"], PLAN_SESSION_CONFIG["silver"])
        self.assertEqual(result["remaining"], result["total"])
        self.assertEqual(result["used"], 0)
        self.assertEqual(result["plan"], "silver")

    def test_daily_session_budget_free(self):
        result = daily_session_budget(456, "free")
        self.assertEqual(result["total"], PLAN_SESSION_CONFIG["free"])
        self.assertEqual(result["plan"], "free")

    def test_daily_session_budget_gold(self):
        result = daily_session_budget(789, "gold")
        self.assertEqual(result["total"], PLAN_SESSION_CONFIG["gold"])
        self.assertEqual(result["plan"], "gold")

    def test_daily_session_budget_unknown_plan_falls_back_to_free(self):
        result = daily_session_budget(0, "unknown")
        self.assertEqual(result["total"], PLAN_SESSION_CONFIG["free"])
        self.assertEqual(result["plan"], "unknown")

    def test_consume_session_slot_returns_true(self):
        self.assertTrue(consume_session_slot(123))

    def test_release_session_slot_runs(self):
        release_session_slot(123)
