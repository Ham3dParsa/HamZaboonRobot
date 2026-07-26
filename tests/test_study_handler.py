import unittest
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, User
from handlers.study_handler import handle_study_start
from services import db


class StudyHandlerTextRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db.init_db()
        db.create_user_if_needed(1, "test_user")
        db.set_user_lang_goal(1, "en", "conversation")
        db.set_user_level(1, "beginner")
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE users SET onboarded=1, plan='free'"
            )
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        self.tempdir.cleanup()

    def _make_text_update(self):
        user = MagicMock(spec=User)
        user.id = 1
        message = AsyncMock(spec=Message)
        message.reply_text = AsyncMock()
        update = MagicMock(spec=Update)
        update.effective_user = user
        update.message = message
        update.callback_query = None
        return update

    async def test_text_route_does_not_crash(self):
        update = self._make_text_update()
        context = MagicMock()
        context.user_data = {}
        await handle_study_start(update, context)
        update.message.reply_text.assert_awaited_once()

    async def test_text_route_shows_empty_message_when_no_content(self):
        update = self._make_text_update()
        context = MagicMock()
        context.user_data = {}
        await handle_study_start(update, context)
        text = update.message.reply_text.await_args[0][0]
        self.assertIn("فردا منتظرتان هستیم", text)

    async def test_text_route_stores_session_in_user_data(self):
        db.add_saved_word(1, "test_word", "en", {
            "word": "test_word",
            "fa_meaning": "سلام",
        })
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE saved_words SET interval_idx=0, next_review='2020-01-01'"
            )
            conn.commit()
        update = self._make_text_update()
        context = MagicMock()
        context.user_data = {}
        await handle_study_start(update, context)
        self.assertIn("study_session", context.user_data)
        self.assertGreater(len(context.user_data["study_session"]["nodes"]), 0)


class StudyHandlerCallbackRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db.init_db()
        db.create_user_if_needed(1, "test_user")
        db.set_user_lang_goal(1, "en", "conversation")
        db.set_user_level(1, "beginner")
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE users SET onboarded=1, plan='free'"
            )
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        self.tempdir.cleanup()

    def _make_callback_update(self):
        user = MagicMock(spec=User)
        user.id = 1
        query = AsyncMock()
        query.answer = AsyncMock()
        query.message = AsyncMock(spec=Message)
        query.message.reply_text = AsyncMock()
        update = MagicMock(spec=Update)
        update.effective_user = user
        update.callback_query = query
        update.message = None
        return update

    async def test_callback_route_answers_and_sends_card(self):
        db.add_saved_word(1, "callback_word", "en", {
            "word": "callback_word",
            "fa_meaning": "سلام",
        })
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE saved_words SET interval_idx=0, next_review='2020-01-01'"
            )
            conn.commit()
        update = self._make_callback_update()
        context = MagicMock()
        context.user_data = {}
        await handle_study_start(update, context)
        update.callback_query.answer.assert_awaited_once()
        update.callback_query.message.reply_text.assert_awaited_once()

    async def test_callback_route_shows_empty_message_when_no_content(self):
        update = self._make_callback_update()
        context = MagicMock()
        context.user_data = {}
        await handle_study_start(update, context)
        text = update.callback_query.message.reply_text.await_args[0][0]
        self.assertIn("فردا منتظرتان هستیم", text)

    async def test_callback_route_without_content_does_not_call_answer_with_alert(self):
        update = self._make_callback_update()
        context = MagicMock()
        context.user_data = {}
        await handle_study_start(update, context)
        update.callback_query.answer.assert_awaited_once_with()
