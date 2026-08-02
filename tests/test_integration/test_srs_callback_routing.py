"""Integration tests for SRS callback routing and schema migration (1g.7, 1g.8)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class CallbackRoutingTest(unittest.TestCase):
    """1g.7: Verify callback_router dispatches old/new patterns correctly."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_update(self, callback_data: str):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = callback_data
        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query = query
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        return ctx

    def test_old_style_callback_rejected_gracefully(self):
        from bot import callback_router

        update = self._make_update("srs:remember:1:100")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.answer.call_args
        self.assertIn("دیگر معتبر نیست", call_args[0][0])

    def test_new_style_callback_dispatches_to_handler(self):
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
        }
        db.add_saved_word(1, "hello", "en", card)
        row = db.get_saved_word(1, user_id=1)
        word_id = row["id"]

        from bot import callback_router

        update = self._make_update(f"srs:3:1:{word_id}")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        events = self._events()
        self.assertTrue(len(events) >= 1, "Expected at least one review event")
        self.assertEqual(events[-1]["grade"], 3)

    def test_invalid_grade_value_rejected(self):
        from bot import callback_router

        update = self._make_update("srs:99:1:100")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.answer.call_args
        self.assertIn("دیگر معتبر نیست", call_args[0][0])

    def test_wrong_part_count_rejected(self):
        from bot import callback_router

        update = self._make_update("srs:1:1")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.answer.call_args
        self.assertIn("نامعتبر", call_args[0][0])

    def _events(self):
        with db.get_conn() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT grade, activity_type, outcome FROM review_events ORDER BY id"
                ).fetchall()
            ]


class SchemaMigrationTest(unittest.TestCase):
    """1g.8: Verify migrate_saved_words_to_fsrs() runs cleanly on a fresh DB."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_migration_runs_without_error(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "test",
            "fa_meaning": "تست",
            "fa_explanation": "تست.",
            "examples": ["Test!"],
            "example_translations": ["تست!"],
        }
        db.add_saved_word(1, "test", "en", card)
        result = db.migrate_saved_words_to_fsrs()
        self.assertTrue(result, "migrate_saved_words_to_fsrs should return True")

    def test_migration_idempotent(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "سلام.",
            "examples": ["Hi!"],
            "example_translations": ["سلام!"],
        }
        db.add_saved_word(1, "hello", "en", card)
        self.assertTrue(db.migrate_saved_words_to_fsrs())
        self.assertTrue(db.migrate_saved_words_to_fsrs())


if __name__ == "__main__":
    unittest.main()
