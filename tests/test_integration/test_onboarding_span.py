"""Integration tests for the onboarding span fixes (R3, T4).

Verifies that the welcome / language / level messages are built from span
``Message`` objects so bold is emitted structurally (``*…*`` MDV2 markup)
instead of being escaped away by ``escape_mdv2`` — the root cause of the
``*bold*``-shows-as-plain bug.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class OnboardingSpanTest(unittest.TestCase):
    def setUp(self):
        import bot

        self.offline_patcher = patch.object(bot, "_telegram_offline", False)
        self.offline_patcher.start()
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = self.tempdir.name + "/test.sqlite"
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        self.offline_patcher.stop()
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _message_update(self, text: str = ""):
        message = MagicMock()
        message.text = text
        message.reply_text = AsyncMock()
        user = MagicMock()
        user.id = 1
        user.username = "learner"
        user.first_name = "Learner"
        update = MagicMock()
        update.effective_user = user
        update.effective_chat.id = 1
        update.message = message
        update.callback_query = None
        return update

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock()
        ctx.bot.get_me = AsyncMock(return_value=MagicMock(username="bot"))
        return ctx

    def _callback_update(self, data: str = ""):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message.chat.id = 1
        query.data = data
        user = MagicMock()
        user.id = 1
        user.username = "learner"
        user.first_name = "Learner"
        update = MagicMock()
        update.effective_user = user
        update.effective_chat.id = 1
        update.callback_query = query
        update.message = None
        return update

    def test_start_welcome_emits_bold_markup(self):
        from handlers.user import cmd_start

        update = self._message_update("/start")
        ctx = self._context()
        asyncio.run(cmd_start(update, ctx))

        ctx.bot.send_message.assert_called_once()
        args, kwargs = ctx.bot.send_message.call_args
        text = kwargs["text"]
        # The message is routed through _send_with_retry(bot, chat_id, text, ...).
        self.assertIn("*هم‌زبان*", text)
        self.assertIn("سلام", text)

    def test_lang_selected_emits_bold_markup(self):
        from handlers.user import on_lang_selected

        update = self._callback_update("lang:en")
        ctx = self._context()
        asyncio.run(on_lang_selected(update, ctx, "en"))

        query = update.callback_query
        query.edit_message_text.assert_called_once()
        args, kwargs = query.edit_message_text.call_args
        text = args[0]
        self.assertIn("*انگلیسی*", text)

    def test_level_selected_emits_bold_markup(self):
        from handlers.user import on_level_selected

        update = self._callback_update("level:b1")
        ctx = self._context()
        asyncio.run(on_level_selected(update, ctx, "b1"))

        query = update.callback_query
        query.edit_message_text.assert_called_once()
        args, kwargs = query.edit_message_text.call_args
        text = args[0]
        self.assertIn("*", text)
        self.assertIn("ثبت شد", text)


if __name__ == "__main__":
    unittest.main()