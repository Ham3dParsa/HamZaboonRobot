"""Tests for Session P-DB remaining (#11 db-on-loop, #12 busy-timeout)."""
import pathlib
import unittest


class TestBusyTimeout(unittest.TestCase):
    def test_busy_timeout_is_10000(self):
        from services.db import schema as db_schema

        self.assertEqual(db_schema._DB_BUSY_TIMEOUT, 10000)

    def test_get_conn_pragma_and_timeout_agree(self):
        import tempfile
        import os
        from services import db
        from services.db import schema as db_schema

        tmp = tempfile.TemporaryDirectory()
        prev_db = db.DB_PATH
        prev_schema = db_schema.DB_PATH
        path = os.path.join(tmp.name, "test.sqlite")
        db.DB_PATH = path
        db_schema.DB_PATH = path
        try:
            db.init_db()
            with db.get_conn() as conn:
                row = conn.execute("PRAGMA busy_timeout").fetchone()
                self.assertEqual(int(row[0]), 10000)
            self.assertEqual(db_schema._DB_BUSY_TIMEOUT, 10000)
        finally:
            db.DB_PATH = prev_db
            db_schema.DB_PATH = prev_schema
            tmp.cleanup()

    def test_srs_handler_uses_to_thread(self):
        src = pathlib.Path("handlers/srs_handler.py").read_text(encoding="utf-8")
        self.assertIn("import asyncio", src)
        self.assertIn("asyncio.to_thread", src)
        # Spot-check the specific hot-path DB calls are wrapped (allow multiline)
        # F1: the per-tap streak touch moved inside the batched grade
        # transaction (words.grade_* via touch_streak_in_txn), so the handler
        # no longer calls db.touch_streak directly; word_query.ask still does.
        for needle in [
            "db.get_saved_word",
            "db.get_display_toggles",
            "db.is_word_graded",
            "db.grade_word_review",
            "db.grade_first_exposure",
            "db.delete_saved_word",
        ]:
            self.assertIn(needle, src)
            # each should be near a to_thread call
        self.assertGreater(src.count("asyncio.to_thread"), 5)

    def test_word_query_uses_to_thread(self):
        src = pathlib.Path("services/word_query.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.to_thread", src)
        for needle in [
            "db.get_query_result",
            "db.toggle_review_word",
            "db.get_user",
            "db.reserve_word_query",
            "db.create_query_result",
        ]:
            self.assertIn(needle, src)
