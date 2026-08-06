"""Tests for callback_router catch-all and error_handler callback answer."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from bot import callback_router, error_handler


class _BaseCallbackRouterTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")

    def tearDown(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def _make_update(self, data, user_id=1):
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = 100
        query = AsyncMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        query.message.delete = AsyncMock()
        query.message.text = ""
        update.callback_query = query
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        return ctx


class TestCatchAllElse(_BaseCallbackRouterTest):
    def test_unrecognized_prefix_gets_answered(self):
        """A callback starting with a recognized prefix but not matching any
        branch must be answered by the catch-all else clause."""
        update = self._make_update("flow:nonexistent_action")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_awaited()
        call_kwargs = update.callback_query.answer.call_args.kwargs
        self.assertIn("عملیات ناموفق بود", call_kwargs.get("args", ("",))[0] if call_kwargs.get("args") else str(update.callback_query.answer.call_args))

    def test_unrecognized_prefix_shows_alert(self):
        """The catch-all must show_alert=True so the user sees the failure."""
        update = self._make_update("presentation:unknown")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_awaited()
        _, kwargs = update.callback_query.answer.call_args
        self.assertTrue(kwargs.get("show_alert", False))

    def test_completely_unrecognized_data_also_answered(self):
        """Callback data that doesn't start with any recognized prefix must
        also be answered (by the prefix guard at the top of the router)."""
        update = self._make_update("totally_unknown_data")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_awaited()


class TestErrorHandlerAnswersCallback(_BaseCallbackRouterTest):
    def test_error_handler_answers_callback(self):
        """When error_handler catches an exception from a callback update,
        it must answer the callback to dismiss the spinner."""
        update = self._make_update("some_callback")
        context = MagicMock()
        context.error = RuntimeError("test error")
        asyncio.run(error_handler(update, context))
        update.callback_query.answer.assert_awaited_once()
        _, kwargs = update.callback_query.answer.call_args
        self.assertTrue(kwargs.get("show_alert", False))

    def test_error_handler_no_answer_for_text_message(self):
        """When error_handler catches an exception from a text message update
        (not a callback), it must NOT try to answer a callback_query."""
        update = MagicMock()
        update.callback_query = None  # text message, not callback
        context = MagicMock()
        context.error = RuntimeError("test error")
        # Should not raise
        asyncio.run(error_handler(update, context))
        # No answer call possible since callback_query is None


class TestSettingsHandlersAnswerCallback(_BaseCallbackRouterTest):
    def test_change_lang_start_answers(self):
        from handlers.user import change_lang_start
        update = self._make_update("settings:lang")
        ctx = self._make_context()
        asyncio.run(change_lang_start(update, ctx))
        update.callback_query.answer.assert_awaited()

    def test_change_goal_start_answers(self):
        from handlers.user import change_goal_start
        update = self._make_update("settings:goal")
        ctx = self._make_context()
        asyncio.run(change_goal_start(update, ctx))
        update.callback_query.answer.assert_awaited()

    def test_change_level_start_answers(self):
        from handlers.user import change_level_start
        update = self._make_update("settings:level")
        ctx = self._make_context()
        asyncio.run(change_level_start(update, ctx))
        update.callback_query.answer.assert_awaited()

    def test_show_status_answers(self):
        from handlers.user import show_status
        update = self._make_update("settings:status")
        ctx = self._make_context()
        asyncio.run(show_status(update, ctx))
        update.callback_query.answer.assert_awaited()

    def test_show_settings_menu_answers(self):
        from handlers.user import _show_settings_menu
        update = self._make_update("settings:back")
        ctx = self._make_context()
        asyncio.run(_show_settings_menu(update, ctx))
        update.callback_query.answer.assert_awaited()


if __name__ == "__main__":
    unittest.main()
