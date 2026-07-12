import datetime as dt
import os
import tempfile
import unittest

import db
from scheduling import plan_sessions, planned_datetime, session_sizes


class SchedulingPolicyTests(unittest.TestCase):
    def test_roadmap_session_sizes(self):
        self.assertEqual(session_sizes(4), [2, 1, 1])
        self.assertEqual(session_sizes(12), [3, 3, 3, 3])
        self.assertEqual(session_sizes(24), [4, 4, 4, 4, 4, 4])
        self.assertEqual(session_sizes(30), [5, 5, 5, 5, 5, 5])

    def test_shared_preferred_hour_is_spread_across_capacity(self):
        loads = {}
        planned = []
        for _ in range(12):
            sessions = plan_sessions(
                3,
                preferred_minute=9 * 60,
                active_start=8 * 60,
                active_end=12 * 60,
                slot_minutes=30,
                bucket_capacity=2,
                bucket_loads=loads,
            )
            minute = sessions[0].planned_minute
            planned.append(minute)
            loads[minute] = loads.get(minute, 0) + 1

        self.assertGreater(len(set(planned)), 1)
        self.assertLessEqual(max(planned), 12 * 60)
        self.assertGreaterEqual(min(planned), 8 * 60)

    def test_sessions_stay_within_active_window(self):
        sessions = plan_sessions(30, 600, 540, 900)
        self.assertEqual(sum(session.card_count for session in sessions), 30)
        self.assertTrue(all(540 <= session.planned_minute <= 900 for session in sessions))

    def test_planned_datetime_uses_configured_timezone(self):
        planned = planned_datetime(dt.date(2026, 7, 12), 540, "Asia/Tehran")
        self.assertIn("09:00:00+03:30", planned)


class DurableQueueTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        self.tempdir.cleanup()

    def test_queue_is_idempotent_and_has_durable_states(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_level(1, "beginner")
        sessions = plan_sessions(4, 540, 480, 1260)
        date = dt.date(2026, 7, 12).isoformat()
        db.enqueue_delivery_sessions(1, date, sessions)
        db.enqueue_delivery_sessions(1, date, sessions)

        rows = db.delivery_queue_for_user(1, date)
        self.assertEqual(len(rows), 3)
        claimed = db.claim_delivery_queue(rows[0]["id"])
        self.assertEqual(claimed["status"], "processing")
        db.mark_delivery_failed(claimed["id"], "temporary")
        self.assertEqual(db.delivery_queue_for_user(1, date)[0]["status"], "failed")
        claimed = db.claim_delivery_queue(rows[0]["id"])
        db.mark_delivery_sent(claimed["id"])
        self.assertEqual(db.delivery_queue_for_user(1, date)[0]["status"], "sent")


if __name__ == "__main__":
    unittest.main()
