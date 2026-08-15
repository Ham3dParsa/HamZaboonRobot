"""Study-session restart persistence — Bug 1 (owner report 2026-08-15).

Contract (locked 2026-08-15, both rules Option A):
- Rule 1: persist the active study session to the SQLite `study_sessions`
  table; restore it after a bot restart.
- Rule 2: only resume a persisted session whose `session_date` equals today's
  application day; an overnight session is discarded and a fresh one is built.

DB layer is pure JSON I/O — no Telegram/handler imports (no circular deps).
"""

import json
import os
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema
from services.db import sessions as sessions_module


def _column_names(table):
    with db_module.get_conn() as conn:
        return {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }


class StudySessionTableTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "sessions.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_fresh_db_has_study_sessions_table(self):
        with db_module.get_conn() as conn:
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("study_sessions", tables)

    def test_study_sessions_columns(self):
        cols = _column_names("study_sessions")
        for col in ("user_id", "session_date", "state_json", "updated_at"):
            self.assertIn(col, cols, f"study_sessions.{col} missing")

    def test_init_db_idempotent(self):
        db_module.init_db()
        db_module.init_db()
        with db_module.get_conn() as conn:
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("study_sessions", tables)


class StudySessionPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "sessions.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def _sample_state(self):
        return json.dumps(
            {
                "nodes": [
                    {
                        "activity_type": "first_exposure",
                        "source_tier": 1,
                        "card_data": {"word": "hello", "fa_meaning": "سلام"},
                        "source_id": 42,
                        "activity_meta": {"user_id": 1},
                        "grade_policy_ref": "first_exposure",
                        "interaction_schema": None,
                    }
                ],
                "total_cards": 1,
                "tier3_context": {"user_id": 1, "remaining_slots": 0},
                "study_msg_id": 999,
                "plan": "free",
            }
        )

    def test_save_load_roundtrip(self):
        state_json = self._sample_state()
        sessions_module.save_study_session(1, "2026-08-15", state_json)
        row = sessions_module.load_study_session(1)
        self.assertIsNotNone(row)
        session_date, loaded = row
        self.assertEqual(session_date, "2026-08-15")
        self.assertEqual(json.loads(loaded), json.loads(state_json))

    def test_load_missing_user_returns_none(self):
        self.assertIsNone(sessions_module.load_study_session(999))

    def test_clear_removes_row(self):
        sessions_module.save_study_session(1, "2026-08-15", self._sample_state())
        sessions_module.clear_study_session(1)
        self.assertIsNone(sessions_module.load_study_session(1))

    def test_clear_missing_user_is_noop(self):
        sessions_module.clear_study_session(999)
        self.assertIsNone(sessions_module.load_study_session(999))

    def test_save_overwrites_same_user(self):
        sessions_module.save_study_session(1, "2026-08-15", self._sample_state())
        newer = json.dumps({"nodes": [], "total_cards": 0})
        sessions_module.save_study_session(1, "2026-08-15", newer)
        row = sessions_module.load_study_session(1)
        self.assertIsNotNone(row)
        self.assertEqual(json.loads(row[1]), json.loads(newer))

    def test_different_users_do_not_clobber(self):
        sessions_module.save_study_session(1, "2026-08-15", self._sample_state())
        sessions_module.save_study_session(2, "2026-08-15", self._sample_state())
        row = sessions_module.load_study_session(1)
        self.assertIsNotNone(row)
        row2 = sessions_module.load_study_session(2)
        self.assertIsNotNone(row2)

    def test_save_persist_then_clear_removes_row(self):
        sessions_module.save_study_session(1, "2026-08-15", self._sample_state())
        sessions_module.clear_study_session(1)
        self.assertIsNone(sessions_module.load_study_session(1))


if __name__ == "__main__":
    unittest.main()