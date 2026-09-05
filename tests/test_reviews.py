"""Tests for review_events schema migration and insert_review_event."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema


class ReviewEventsSchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    def _column_names(self, table):
        with db.get_conn() as conn:
            return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _record(self, word_id, user_id, grade, activity_type, **kwargs):
        """Caller-owned transaction around insert_review_event (grade-path pattern)."""
        with db.transaction() as conn:
            db.insert_review_event(conn, word_id, user_id, grade, activity_type, **kwargs)

    # R5 — schema migration adds all 5 new columns
    def test_schema_migration_adds_new_columns(self):
        db.init_db()
        columns = self._column_names("review_events")
        for col in ("grade", "activity_type", "grade_source", "raw_signal", "response_time_ms"):
            self.assertIn(col, columns)

    # R1 — new function persists all 5 new columns
    def test_insert_review_event_persists_all_columns(self):
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.add_saved_word(1, "hello", "en", {"word": "hello"})
        with db.get_conn() as conn:
            word_id = conn.execute("SELECT id FROM saved_words WHERE user_id=1").fetchone()["id"]
        self._record(
            word_id, 1, 3, "srs_review",
            grade_source="direct_button",
            raw_signal=json.dumps({"button_value": 3}),
            response_time_ms=2500,
        )
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM review_events WHERE id=1").fetchone()
        self.assertEqual(row["word_id"], word_id)
        self.assertEqual(row["user_id"], 1)
        self.assertEqual(row["grade"], 3)
        self.assertEqual(row["activity_type"], "srs_review")
        self.assertEqual(row["grade_source"], "direct_button")
        self.assertEqual(row["raw_signal"], json.dumps({"button_value": 3}))
        self.assertEqual(row["response_time_ms"], 2500)

    # R2 — nullable response_time is NULL
    def test_nullable_response_time(self):
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.add_saved_word(1, "hello", "en", {"word": "hello"})
        with db.get_conn() as conn:
            word_id = conn.execute("SELECT id FROM saved_words WHERE user_id=1").fetchone()["id"]
        self._record(
            word_id, 1, 2, "first_exposure",
            raw_signal=json.dumps({"button_value": 2}),
            response_time_ms=None,
        )
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM review_events WHERE id=1").fetchone()
        self.assertIsNone(row["response_time_ms"])
        self.assertEqual(row["grade"], 2)

    # R3 — grade >= 2 derives outcome="recalled" (Hard is success)
    def test_grade_2_derives_recalled(self):
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.add_saved_word(1, "hello", "en", {"word": "hello"})
        with db.get_conn() as conn:
            word_id = conn.execute("SELECT id FROM saved_words WHERE user_id=1").fetchone()["id"]
        self._record(word_id, 1, 2, "srs_review")
        with db.get_conn() as conn:
            row = conn.execute("SELECT outcome FROM review_events WHERE id=1").fetchone()
        self.assertEqual(row["outcome"], "recalled")

    # R4 — grade=1 derives outcome="again"
    def test_grade_1_derives_again(self):
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.add_saved_word(1, "hello", "en", {"word": "hello"})
        with db.get_conn() as conn:
            word_id = conn.execute("SELECT id FROM saved_words WHERE user_id=1").fetchone()["id"]
        self._record(word_id, 1, 1, "srs_review")
        with db.get_conn() as conn:
            row = conn.execute("SELECT outcome FROM review_events WHERE id=1").fetchone()
        self.assertEqual(row["outcome"], "again")
