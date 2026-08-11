"""Tests for grade-submission feedback intent (#308).

Locked contract: successful grade submissions use a non-blocking toast
(notify_callback intent=SUCCESS); important errors use a blocking modal
(notify_callback intent=IMPORTANT_ERROR). No direct query.answer(...) or
show_alert usage is introduced by the grade-feedback paths.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from handlers import srs_handler
from services.utils.callback_notifications import CallbackNoticeIntent


class GradeFeedbackIntentTests(unittest.TestCase):
    """Assert the semantic intent passed to notify_callback on grade paths."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام.",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
            "synonyms": [],
            "antonyms": [],
            "grammar_tip": "نکته",
        }
        db.add_saved_word(1, "hello", "en", card)
        with db.get_conn() as conn:
            self.word_id = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1"
            ).fetchone()["id"]
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE saved_words SET review_status='pending' WHERE id=?",
                (self.word_id,),
            )
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    def _query(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        query.message.text = "hello"
        return query

    def _update(self, query):
        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query = query
        return update

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        return ctx

    # --- Success: regular review (grade 3) ---
    def test_srs_review_success_uses_success_intent(self):
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(srs_handler._handle_srs_review(update, 3, "1", str(self.word_id), ctx))
            notify.assert_called_once()
            call = notify.call_args
            self.assertEqual(call.kwargs["intent"], CallbackNoticeIntent.SUCCESS)

    # --- Success: first-exposure grade (grade 4) ---
    def test_first_exposure_success_uses_success_intent(self):
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(srs_handler._handle_first_exposure_grade(
                update, ctx, "4", "1", str(self.word_id),
            ))
            notify.assert_called_once()
            call = notify.call_args
            self.assertEqual(call.kwargs["intent"], CallbackNoticeIntent.SUCCESS)

    # --- Error: review belongs to another user ---
    def test_wrong_user_uses_important_error_intent(self):
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(srs_handler._handle_srs_review(update, 3, "999", str(self.word_id), ctx))
            notify.assert_called_once()
            call = notify.call_args
            self.assertEqual(call.kwargs["intent"], CallbackNoticeIntent.IMPORTANT_ERROR)

    # --- Error: word not found in review box ---
    def test_word_not_found_uses_important_error_intent(self):
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(srs_handler._handle_srs_review(update, 3, "1", "999999", ctx))
            notify.assert_called_once()
            call = notify.call_args
            self.assertEqual(call.kwargs["intent"], CallbackNoticeIntent.IMPORTANT_ERROR)


if __name__ == "__main__":
    unittest.main()
