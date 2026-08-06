"""Tests for session scheduling — quota enforcement via settings table."""

from __future__ import annotations

import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema
from services.scheduling import (
    consume_session_slot,
    daily_session_budget,
    release_session_slot,
)


class TestScheduling(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_plan_session_config_has_expected_plans(self):
        expected = {"free", "bronze", "silver", "gold", "emerald"}
        self.assertEqual({p["name"] for p in db.list_plans()}, expected)

    def test_plan_session_config_positive_values(self):
        for plan in db.list_plans():
            with self.subTest(plan=plan["name"]):
                self.assertGreater(plan["max_sessions"], 0)
                self.assertGreater(plan["cards_per_session"], 0)

    def test_daily_session_budget_silver(self):
        result = daily_session_budget(123, "silver")
        self.assertEqual(result["total"], db.get_plan("silver")["max_sessions"])
        self.assertEqual(result["remaining"], result["total"])
        self.assertEqual(result["used"], 0)
        self.assertEqual(result["plan"], "silver")

    def test_daily_session_budget_free(self):
        result = daily_session_budget(456, "free")
        self.assertEqual(result["total"], db.get_plan("free")["max_sessions"])
        self.assertEqual(result["plan"], "free")

    def test_daily_session_budget_gold(self):
        result = daily_session_budget(789, "gold")
        self.assertEqual(result["total"], db.get_plan("gold")["max_sessions"])
        self.assertEqual(result["plan"], "gold")

    def test_daily_session_budget_unknown_plan_falls_back_to_free(self):
        result = daily_session_budget(0, "unknown")
        self.assertEqual(result["total"], db.get_plan("free")["max_sessions"])
        self.assertEqual(result["plan"], "unknown")

    def test_consume_session_slot_returns_true_under_limit(self):
        self.assertTrue(consume_session_slot(1, "free"))

    def test_consume_session_slot_increments_used(self):
        consume_session_slot(2, "free")
        budget = daily_session_budget(2, "free")
        self.assertEqual(budget["used"], 1)
        # free plan: 2 sessions/day -> after one, 1 remaining
        self.assertEqual(budget["remaining"], 1)

    def test_consume_session_slot_exceeds_limit(self):
        # free plan: 2 sessions/day
        self.assertTrue(consume_session_slot(3, "free"))
        self.assertTrue(consume_session_slot(3, "free"))
        self.assertFalse(consume_session_slot(3, "free"))

    def test_consume_session_slot_silver_allows_three(self):
        for i in range(3):
            self.assertTrue(consume_session_slot(4, "silver"), f"slot {i+1} should succeed")
        self.assertFalse(consume_session_slot(4, "silver"), "4th slot should fail")

    def test_release_session_slot_decrements(self):
        consume_session_slot(5, "free")
        budget_before = daily_session_budget(5, "free")
        self.assertEqual(budget_before["used"], 1)
        release_session_slot(5)
        budget_after = daily_session_budget(5, "free")
        self.assertEqual(budget_after["used"], 0)
        self.assertEqual(budget_after["remaining"], 2)

    def test_release_session_slot_does_not_go_below_zero(self):
        release_session_slot(999)
        budget = daily_session_budget(999, "free")
        self.assertEqual(budget["used"], 0)

    def test_daily_session_budget_reflects_actual_usage(self):
        consume_session_slot(10, "silver")
        consume_session_slot(10, "silver")
        budget = daily_session_budget(10, "silver")
        self.assertEqual(budget["used"], 2)
        self.assertEqual(budget["remaining"], 1)