"""Fallback + migration regression tests for query_results normalization (PR #586)."""
import asyncio
import datetime
import json
import os
import tempfile
import unittest

os.environ["HAMZABAN_TEST_MODE"] = "1"
import services.db as db
from services.db import schema as db_schema
from services.word_query import ask


def _future_expires(days=30):
    return (db._utc_now() + datetime.timedelta(days=days)).isoformat()


class QueryResultsFallbackTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        db.create_user_if_needed(1, username="t")
        with db.transaction() as conn:
            conn.execute(
                "UPDATE users SET target_lang=?, goal=?, level=?, onboarded=1, plan=? WHERE user_id=?",
                ("en", "general", "beginner", "free", 1),
            )

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def test_legacy_unnormalized_row_hits_pre_ai_without_ai(self):
        legacy_token = "legacybantertoken001"
        now = db._utc_now().isoformat()
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO query_results(token, user_id, query_text, word, lang, result_json, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    legacy_token,
                    1,
                    "BANTER ",
                    "BANTER",
                    "en",
                    json.dumps({"word": "banter", "fa_meaning": "x"}),
                    now,
                    _future_expires(),
                ),
            )

        async def should_not_be_called(**kwargs):
            raise AssertionError("AI should not be called for legacy fallback hit")

        result = asyncio.run(ask(1, "banter", generate_card=should_not_be_called))
        self.assertEqual(result.kind, "duplicate")
        self.assertEqual(result.token, legacy_token)

    def test_fallback_scan_bounded(self):
        for i in range(100):
            db.create_query_result(
                1, f"phrase_b_{i}", f"word_b_{i}", "en", {"word": f"word_b_{i}"}
            )
        self.assertIsNone(db.find_unexpired_query(1, "missing-phrase-xyz", "en"))

    def test_backfill_normalizes_and_sets_marker(self):
        older_created = "2020-01-01T00:00:00+00:00"
        newer_created = "2024-01-01T00:00:00+00:00"
        expires = _future_expires()
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO query_results(token, user_id, query_text, word, lang, result_json, created_at, expires_at, saved_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "backfill-keeper-old",
                    1,
                    "Hello",
                    "Hello",
                    "en",
                    json.dumps({"word": "hello", "fa_meaning": "x"}),
                    older_created,
                    expires,
                    "2024-06-01T00:00:00+00:00",
                ),
            )
            conn.execute(
                "INSERT INTO query_results(token, user_id, query_text, word, lang, result_json, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "backfill-dup-new",
                    1,
                    "HELLO ",
                    "HELLO",
                    "en",
                    json.dumps({"word": "hello", "fa_meaning": "y"}),
                    newer_created,
                    expires,
                ),
            )
            conn.execute(
                "DELETE FROM settings WHERE key='_migration_query_results_normalization_done'"
            )
        db.init_db()
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT token, query_text, word FROM query_results WHERE user_id=1 AND lang='en'"
            ).fetchall()
            marker = conn.execute(
                "SELECT 1 FROM settings WHERE key='_migration_query_results_normalization_done'"
            ).fetchone()
        self.assertEqual(len(rows), 1)
        keeper = rows[0]
        self.assertEqual(keeper["token"], "backfill-keeper-old")
        self.assertEqual(keeper["query_text"], "hello")
        self.assertEqual(keeper["word"], "hello")
        self.assertIsNotNone(marker)


if __name__ == "__main__":
    unittest.main()
