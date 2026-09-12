"""REF1-T4: group-1 callbacks route via the central registry with identical
dispatch and a single callback answer.

Covers flow/settings/help/presentation/lang/goal/level through
``bot.callback_router`` (which must hand them to ``routing_dispatch``):
registered prefixes, byte-identical toasts/fallbacks, exactly one
``query.answer`` per callback.
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

from services import db
from services.db import schema as db_schema


def _answer_texts(query):
    texts = []
    for call in query.answer.await_args_list:
        args, kwargs = call
        if args:
            texts.append(args[0])
        elif "text" in kwargs:
            texts.append(kwargs["text"])
    return texts


class RoutingGroup1FlowTests(unittest.TestCase):
    def setUp(self):
        import bot

        bot._callback_dedup.clear()
        self._offline = bot._telegram_offline
        bot._telegram_offline = False
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        # Onboarded learner for settings/presentation flows.
        db.create_user_if_needed(11, "learner")
        db.set_user_lang_goal(11, "en", "general")
        db.set_user_level(11, "beginner")

    def tearDown(self):
        import bot

        bot._telegram_offline = self._offline
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def _make_update(self, data, user_id=11):
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = 100
        query = AsyncMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        query.message.delete = AsyncMock()
        update.callback_query = query
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        return ctx

    def _run(self, data, user_id=11):
        import bot

        update = self._make_update(data, user_id=user_id)
        ctx = self._make_context()
        asyncio.run(bot.callback_router(update, ctx))
        return update, ctx

    def test_group1_prefixes_registered(self):
        import handlers.admin  # noqa: F401
        import handlers.help_command  # noqa: F401
        import handlers.user  # noqa: F401
        from services.routing import ROUTES

        registered = {prefix for (prefix, _, _) in ROUTES}
        for prefix in ("flow", "settings", "help", "presentation", "lang", "goal", "level"):
            self.assertIn(prefix, registered)

    def test_help_back_single_answer(self):
        update, _ = self._run("help:back")
        update.callback_query.answer.assert_awaited_once()

    def test_settings_status_single_answer(self):
        update, _ = self._run("settings:status")
        update.callback_query.answer.assert_awaited_once()

    def test_settings_unknown_action_fallback(self):
        update, _ = self._run("settings:bogus")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("عملیات ناموفق بود" in t for t in texts))
        _, kwargs = update.callback_query.answer.call_args
        self.assertTrue(kwargs.get("show_alert", False))

    def test_flow_unknown_action_fallback(self):
        update, _ = self._run("flow:nonexistent_action")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("عملیات ناموفق بود" in t for t in texts))

    def test_presentation_unknown_fallback(self):
        update, _ = self._run("presentation:unknown")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("عملیات ناموفق بود" in t for t in texts))
        _, kwargs = update.callback_query.answer.call_args
        self.assertTrue(kwargs.get("show_alert", False))

    def test_lang_invalid_value_toast(self):
        update, _ = self._run("lang:xx_invalid")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("زبان نامعتبر است" in t for t in texts))

    def test_goal_invalid_value_toast(self):
        update, _ = self._run("goal:xx_invalid")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("هدف نامعتبر است" in t for t in texts))

    def test_level_invalid_value_toast(self):
        update, _ = self._run("level:xx_invalid")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("سطح نامعتبر است" in t for t in texts))

    def test_settings_close_single_answer(self):
        update, _ = self._run("settings:close")
        update.callback_query.answer.assert_awaited_once()

    def test_lang_onboarding_selection_single_answer(self):
        update, _ = self._run("lang:en", user_id=99)
        update.callback_query.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
