"""Phase 3 — toggle_save wiring (word_query.toggle_save).

Regression coverage for the deep-module refactor: the save-toggle (`query:add:`)
callback is a thin adapter over services.word_query.toggle_save. These tests
drive the REAL handler (`handlers.srs_handler._handle_query_add`) with a temp
on-disk DB, patching only the Telegram edit helper, so every result.kind branch
is proven end-to-end.

Locked contract rules verified here:
- Save/remove toggle: first tap saves + marks, second tap removes + clears.
- Expired token: friendly toast, no state change.
- Keyboard reflects saved state (remove vs add) and pronounce, and no longer
  emits the removed `query:prepare:` (translations) button (R2/R3 of the
  word-query card-consistency spec #340).
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

from handlers.srs_handler import _handle_query_add
from services import db
from services.db import schema as db_schema


class WordQueryToggleFlowTests(unittest.TestCase):
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
        self.card = {
            "word": "hello",
            "phonetic": "/həˈloʊ/",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام کردن.",
            "examples": ["Hello!"],
        }

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_update(self):
        update = MagicMock()
        update.effective_user.id = 1
        query = MagicMock()
        query.answer = AsyncMock()
        message = MagicMock()
        message.edit_reply_markup = AsyncMock()
        query.message = message
        update.callback_query = query
        update.effective_message = message
        return update

    def _context(self, user_data=None):
        context = MagicMock()
        context.user_data = user_data if user_data is not None else {}
        context.bot = MagicMock()
        return context

    def test_toggle_saves_then_removes(self):
        token = db.create_query_result(1, "hello", "hello", "en", self.card)
        update = self._make_update()
        context = self._context(
            {f"query_kb_{token}": {}}
        )
        asyncio.run(_handle_query_add(update, context, token))
        self.assertIsNotNone(
            db.get_query_result(token, user_id=1)["saved_at"],
            "first tap saves and marks the result",
        )
        self.assertIn("ذخیره شد", update.callback_query.answer.call_args[0][0])
        markup = update.effective_message.edit_reply_markup.call_args.kwargs["reply_markup"]
        self.assertTrue(any("حذف" in b.text for r in markup.inline_keyboard for b in r))

        asyncio.run(_handle_query_add(update, context, token))
        self.assertIsNone(
            db.get_query_result(token, user_id=1)["saved_at"],
            "second tap removes and clears the marker",
        )
        self.assertIn("حذف شد", update.callback_query.answer.call_args[0][0])

    def test_toggle_expired_notifies(self):
        token = "missing-token"
        update = self._make_update()
        context = self._context()
        asyncio.run(_handle_query_add(update, context, token))
        self.assertIn("منقضی شده", update.callback_query.answer.call_args[0][0])

    def test_toggle_keyboard_has_add_and_pronounce_no_translate_button(self):
        token = db.create_query_result(1, "hello", "hello", "en", self.card)
        update = self._make_update()
        context = self._context(
            {f"query_kb_{token}": {}}
        )
        asyncio.run(_handle_query_add(update, context, token))
        markup = update.effective_message.edit_reply_markup.call_args.kwargs["reply_markup"]
        flat = [b.callback_data for r in markup.inline_keyboard for b in r]
        self.assertTrue(any(c.startswith("query:add:") for c in flat))
        self.assertTrue(any(c.startswith("tts:pronounce:q:") for c in flat))
        self.assertFalse(
            any(c.startswith("query:prepare:") for c in flat),
            "the removed translations (query:prepare:) button must not be emitted",
        )


if __name__ == "__main__":
    unittest.main()
