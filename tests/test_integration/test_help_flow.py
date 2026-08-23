"""Integration tests for /help, 'راهنما' text, and the help panel callbacks."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class HelpFlowTest(unittest.TestCase):
    def setUp(self):
        import bot

        bot._callback_dedup.clear()
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

    def _make_message_update(self, text: str):
        message = MagicMock()
        message.text = text
        message.reply_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.message = message
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock()
        return ctx

    def _make_callback_update(self, data: str):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = data
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        return update

    def test_help_command_sends_panel_and_menu(self):
        from handlers.help_command import send_help_panel

        update = self._make_message_update("/help")
        ctx = self._make_context()
        asyncio.run(send_help_panel(update, ctx))
        # First message is the intro panel (inline keyboard), second restores menu.
        self.assertEqual(ctx.bot.send_message.call_count, 2)
        first = ctx.bot.send_message.call_args_list[0]
        self.assertIn("هم‌زبان", first.kwargs["text"])
        self.assertIsNotNone(first.kwargs.get("reply_markup"))

    def test_fa_help_text_opens_panel(self):
        from bot import text_router

        update = self._make_message_update("راهنما")
        ctx = self._make_context()
        asyncio.run(text_router(update, ctx))
        self.assertEqual(ctx.bot.send_message.call_count, 2)

    def test_fa_help_ignored_while_awaiting_input(self):
        import bot
        from bot import text_router

        # راهنما typed while awaiting a word query must be treated as input,
        # not open the help panel (post-await routing only).
        spy = MagicMock()
        with patch.object(bot, "send_help_panel", spy), patch(
            "services.db.reserve_word_query", return_value=False
        ):
            ctx = self._make_context()
            ctx.user_data["awaiting"] = "ask_word"
            update = self._make_message_update("راهنما")
            asyncio.run(text_router(update, ctx))
        # Help panel must NOT open; the awaiting input branch handles it instead.
        spy.assert_not_called()
        self.assertGreaterEqual(ctx.bot.send_message.call_count, 1)

    def test_help_section_callback_shows_detail(self):
        from bot import callback_router

        update = self._make_callback_update("help:section:study")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        edit_args = update.callback_query.edit_message_text.call_args
        self.assertIn("شروع مطالعه", edit_args[0][0])
        self.assertIsNotNone(edit_args.kwargs.get("reply_markup"))
        update.callback_query.answer.assert_called_once()

    def test_help_back_callback_restores_panel(self):
        from bot import callback_router

        update = self._make_callback_update("help:back")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        edit_args = update.callback_query.edit_message_text.call_args
        self.assertIn("هم‌زبان", edit_args[0][0])
        self.assertIsNotNone(edit_args.kwargs.get("reply_markup"))

    def test_help_unknown_section_reports_error(self):
        from bot import callback_router

        update = self._make_callback_update("help:section:nope")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.answer.call_args
        self.assertIn("موجود نیست", call_args[0][0])

    def test_non_owner_cannot_open_admin_section(self):
        from bot import callback_router

        # A non-owner crafting help:section:admin must be rejected (owner-only
        # gate must hold at the callback layer, not just the panel).
        update = self._make_callback_update("help:section:admin")
        ctx = self._make_context()
        with patch("handlers.help_command.is_owner", return_value=False):
            asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.answer.call_args
        self.assertIn("موجود نیست", call_args[0][0])
        # The admin detail message must NOT have been edited in.
        update.callback_query.edit_message_text.assert_not_called()

    def test_owner_can_open_admin_section(self):
        from bot import callback_router

        # The owner (is_owner True) must be able to open the admin section.
        update = self._make_callback_update("help:section:admin")
        ctx = self._make_context()
        with patch("handlers.help_command.is_owner", return_value=True):
            asyncio.run(callback_router(update, ctx))
        edit_args = update.callback_query.edit_message_text.call_args
        self.assertIn("مدیریت ربات", edit_args[0][0])
        update.callback_query.answer.assert_called_once()

    def test_about_section_in_panel_and_openable(self):
        from bot import callback_router
        from handlers.help_command import send_help_panel

        # "درباره هم‌زبان" is the first button on the panel and opens for everyone.
        update = self._make_message_update("/help")
        ctx = self._make_context()
        asyncio.run(send_help_panel(update, ctx))
        first = ctx.bot.send_message.call_args_list[0]
        kb = first.kwargs["reply_markup"]
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("help:section:about", callbacks)
        self.assertEqual("help:section:about", callbacks[0])

        update2 = self._make_callback_update("help:section:about")
        ctx2 = self._make_context()
        asyncio.run(callback_router(update2, ctx2))
        edit_args = update2.callback_query.edit_message_text.call_args
        self.assertIn("مهاجرت", edit_args[0][0])
        update2.callback_query.answer.assert_called_once()

    def test_hidden_review_section_not_openable(self):
        from bot import callback_router

        # The review section is deactivated (hidden) for now, so even its
        # callback must be rejected for everyone.
        update = self._make_callback_update("help:section:review")
        ctx = self._make_context()
        with patch("handlers.help_command.is_owner", return_value=True):
            asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_called_once()
        self.assertIn("موجود نیست", update.callback_query.answer.call_args[0][0])
        update.callback_query.edit_message_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
