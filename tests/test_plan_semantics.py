import os
import tempfile
import unittest

from config.plan_identity import is_premium
from services import db
from services.db import schema as db_schema
from services.db.plans import effective_plan, plan_spec


class PlanSemanticsTests(unittest.TestCase):
    """Lock R5: plan quota semantics live in plans.py; a missing/inactive/
    unreadable plan resolves to the 'free' spec; effective_plan bypass -> gold.
    Plan *identity* (set membership / premium tiering) lives in the
    config/plan_identity.py leaf (J-B6); is_premium is imported from there."""

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

    def test_plan_spec_reads_armed_db_rows(self):
        for plan, expected in {
            "free": {"query": 2, "sessions": 2, "cards": 3},
            "bronze": {"query": 4, "sessions": 3, "cards": 3},
            "silver": {"query": 7, "sessions": 3, "cards": 5},
            "gold": {"query": 12, "sessions": 4, "cards": 7},
            "emerald": {"query": 20, "sessions": 5, "cards": 9},
        }.items():
            with self.subTest(plan=plan):
                spec = plan_spec(plan)
                self.assertEqual(spec["query_quota"], expected["query"])
                self.assertEqual(spec["max_sessions"], expected["sessions"])
                self.assertEqual(spec["cards_per_session"], expected["cards"])
                self.assertTrue(spec["is_active"])

    def test_plan_spec_unknown_falls_back_to_free(self):
        free_spec = plan_spec("free")
        unknown_spec = plan_spec("does-not-exist")
        for key in ("query_quota", "max_sessions", "cards_per_session", "display_name"):
            self.assertEqual(unknown_spec[key], free_spec[key], key)

    def test_plan_spec_inactive_plan_falls_back_to_free(self):
        db.set_plan_active("silver", False)
        silver = plan_spec("silver")
        self.assertNotEqual(silver["query_quota"], 7)
        self.assertEqual(silver["query_quota"], plan_spec("free")["query_quota"])

    def test_is_premium_membership(self):
        for plan, expected in {
            "free": False,
            "bronze": False,
            "silver": True,
            "gold": True,
            "emerald": True,
        }.items():
            with self.subTest(plan=plan):
                self.assertEqual(is_premium(plan), expected)

    def test_effective_plan(self):
        self.assertEqual(effective_plan("gold"), "gold")
        self.assertEqual(effective_plan("does-not-exist"), "free")
        self.assertEqual(effective_plan("free", bypass_limits=True), "gold")


if __name__ == "__main__":
    unittest.main()