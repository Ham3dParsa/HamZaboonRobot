"""Integration tests for SRS callback routing and schema migration (1g.7, 1g.8)."""

from __future__ import annotations

import asyncio
import json
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
        self.assertTrue(result, "migrate_saved_words_to_fsrs should return True on first run")

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
        self.assertFalse(
            db.migrate_saved_words_to_fsrs(),
            "Second call must be a no-op and return False once the guard is set",
        )

    def test_migration_guard_set_after_run(self):
        db.create_user_if_needed(1, "learner")
        db.migrate_saved_words_to_fsrs()
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='fsrs_migration_done'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["value"], "1")

    def test_migration_preserves_existing_saved_word_content(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        saved_card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح ذخیره‌شده",
            "examples": ["A!"],
            "example_translations": ["الف!"],
        }
        db.add_saved_word(1, "hello", "en", saved_card)
        daily_card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "کارت روزانه",
            "examples": ["B!"],
            "example_translations": ["ب!"],
        }
        db.add_daily_card(1, "2026-07-12", 0, daily_card)
        db.migrate_saved_words_to_fsrs()
        row = db.get_saved_word(1, user_id=1)
        self.assertEqual(json.loads(row["card_data"])["fa_explanation"], "توضیح ذخیره‌شده")
        self.assertEqual(row["first_exposure_done"], 0)
        self.assertEqual(row["stability"], 0.0)
        self.assertEqual(row["difficulty"], 5.0)

    def test_migration_migrates_daily_cards_as_first_exposure(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        for i, word in enumerate(("alpha", "beta")):
            card = {
                "word": word,
                "fa_meaning": "م",
                "fa_explanation": "ت",
                "examples": [f"{word} A!", f"{word} B!"],
                "example_translations": ["م", "ب"],
            }
            db.add_daily_card(1, "2026-07-12", i, card)
        db.migrate_saved_words_to_fsrs()
        fe = db.get_pre_first_exposure_words(1)
        words = sorted(r["word"] for r in fe)
        self.assertEqual(words, ["alpha", "beta"])
        for row in fe:
            self.assertEqual(row["first_exposure_done"], 0)
            self.assertEqual(row["lang"], "en")
            self.assertIsNotNone(row["added_at"])

    def test_migration_migrated_cards_not_due_tier1(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        card = {
            "word": "gamma",
            "fa_meaning": "م",
            "fa_explanation": "ت",
            "examples": ["G A!", "G B!"],
            "example_translations": ["م", "ب"],
        }
        db.add_daily_card(1, "2026-07-12", 0, card)
        db.migrate_saved_words_to_fsrs()
        # The migrated card must be present as first-exposure (Tier 2)...
        fe_words = [r["word"] for r in db.get_pre_first_exposure_words(1)]
        self.assertEqual(fe_words, ["gamma"])
        # ...but NOT appear as a due Tier 1 word.
        due = db.due_words_for_user(1)
        self.assertEqual(len(due), 0, "First-exposure words must not appear as due Tier 1")

    def test_migration_dedupes_by_user_lang_word(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        card = {
            "word": "delta",
            "fa_meaning": "م",
            "fa_explanation": "ت",
            "examples": ["D A!", "D B!"],
            "example_translations": ["م", "ب"],
        }
        db.add_daily_card(1, "2026-07-11", 0, card)
        db.add_daily_card(1, "2026-07-12", 0, card)
        db.migrate_saved_words_to_fsrs()
        with db.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) c FROM saved_words WHERE user_id=1 AND word='delta'"
            ).fetchone()["c"]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
