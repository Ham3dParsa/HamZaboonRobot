"""Locked contract #344 R7a/R8a — duplicate-word detection + 30-day retention.

Unit coverage for the DB layer (``db.find_unexpired_query``, the default
30-day TTL on ``db.create_query_result``) and the orchestration helper
``word_query.find_duplicate``.

Behavior spec (locked, R7/R8):
- R7a: a "prior card" is the most recent unexpired query_result for the same
  user + lang + normalized query_text (the text the user typed), within the
  retention window.
- R8a: the default retention window for a stored query_result is 30 days.
"""

import datetime
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from services import db
from services import word_query
from services.db import schema as db_schema


class QueryResultRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        db.create_user_if_needed(2, "learner")
        db.set_user_lang_goal(2, "en", "general")
        db.set_user_level(2, "beginner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _card(self):
        return {"word": "hello", "fa_meaning": "سلام", "examples": []}

    def _force_expiry(self, token):
        past = (db._utc_now() - datetime.timedelta(days=1)).isoformat()
        conn = sqlite3.connect(db.DB_PATH)
        try:
            conn.execute(
                "UPDATE query_results SET expires_at=? WHERE token=?",
                (past, token),
            )
            conn.commit()
        finally:
            conn.close()

    def test_create_query_result_default_ttl_is_30_days(self):
        """R8a — the default retention window is 30 days, not 24 hours."""
        token = db.create_query_result(1, "hello", "hello", "en", self._card())
        row = db.get_query_result(token, user_id=1, include_expired=True)
        now = db._utc_now()
        expires_at = datetime.datetime.fromisoformat(row["expires_at"])
        delta = expires_at - now
        self.assertGreaterEqual(delta, datetime.timedelta(days=29, hours=23))
        self.assertLessEqual(delta, datetime.timedelta(days=30, seconds=2))

    def test_create_query_result_accepts_explicit_ttl_override(self):
        """Explicit ttl_seconds still works (retains the knob for tests)."""
        token = db.create_query_result(
            1, "hello", "hello", "en", self._card(), ttl_seconds=3600
        )
        row = db.get_query_result(token, user_id=1, include_expired=True)
        delta = datetime.datetime.fromisoformat(row["expires_at"]) - db._utc_now()
        self.assertLessEqual(delta, datetime.timedelta(hours=1, seconds=2))
        self.assertGreater(delta, datetime.timedelta(minutes=59))

    def test_find_unexpired_query_matches_normalized_text_user_lang(self):
        """R7a — matches on normalized query_text + same user + same lang."""
        db.create_query_result(1, "  hello   world  ", "hello", "en", self._card())
        row = db.find_unexpired_query(1, "hello   world", "en")
        self.assertIsNotNone(row)
        self.assertEqual(row["query_text"], "hello world")
        self.assertEqual(row["lang"], "en")

    def test_find_unexpired_query_ignores_expired_rows(self):
        """R7a — an expired row is not a usable prior card."""
        token = db.create_query_result(1, "hello", "hello", "en", self._card())
        self._force_expiry(token)
        self.assertIsNone(db.find_unexpired_query(1, "hello", "en"))

    def test_find_unexpired_query_ignores_different_user_and_lang(self):
        """R7a — a prior card is scoped to the same user and lang."""
        db.create_query_result(1, "hello", "hello", "en", self._card())
        db.create_query_result(1, "bonjour", "bonjour", "fr", self._card())
        # Different lang, same user.
        self.assertIsNone(db.find_unexpired_query(1, "hello", "fr"))
        # Different user, same lang.
        self.assertIsNone(db.find_unexpired_query(2, "hello", "en"))

    def test_find_unexpired_query_returns_most_recent(self):
        """R7a — the most recent match wins when several prior cards exist."""
        db.create_query_result(1, "hello", "hello", "en", {"word": "old"})
        newer = db.create_query_result(1, "hello", "hello", "en", {"word": "new"})
        row = db.find_unexpired_query(1, "hello", "en")
        self.assertEqual(row["token"], newer)


class WordQueryDuplicateOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1 WHERE user_id=1")
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _card(self):
        return {"word": "hello", "fa_meaning": "سلام", "examples": []}

    def test_find_duplicate_returns_none_when_no_prior_card(self):
        self.assertIsNone(word_query.find_duplicate(1, "hello", "en"))

    def test_find_duplicate_returns_prior_card_without_ai(self):
        token = db.create_query_result(1, "hello", "hello", "en", self._card())
        with patch.object(word_query.db, "find_unexpired_query", wraps=db.find_unexpired_query) as lu:
            dup = word_query.find_duplicate(1, "hello", "en")
            lu.assert_called_once()
        self.assertEqual(dup, token)

    def test_find_duplicate_returns_none_for_corrupt_json(self):
        db.create_query_result(1, "hello", "hello", "en", self._card())
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE query_results SET result_json='not-json' WHERE user_id=1"
            )
            conn.commit()
        self.assertIsNone(word_query.find_duplicate(1, "hello", "en"))


if __name__ == "__main__":
    unittest.main()
