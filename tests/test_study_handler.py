import unittest
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, User
from handlers.study_handler import (
    handle_study_start,
    _handle_study_remember,
    _handle_study_again,
    _handle_study_next,
)
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
        self._ai_patcher = patch(
            "services.srs_engine._call_ai_limited",
            side_effect=lambda *a, **kw: [],
        )
        self._ai_patcher.start()

    def tearDown(self):
        self._ai_patcher.stop()
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
        self._ai_patcher = patch(
            "services.srs_engine._call_ai_limited",
            side_effect=lambda *a, **kw: [],
        )
        self._ai_patcher.start()

    def tearDown(self):
        self._ai_patcher.stop()
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


class StudySessionActionTests(unittest.IsolatedAsyncioTestCase):
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
        self._nodes = [
            MagicMock(source_tier=1, source_id=100, card_data={"word": "w1"}),
            MagicMock(source_tier=2, source_id=200, card_data={"word": "w2"}),
        ]
        self._patcher = patch(
            "handlers.study_handler.generate_v3_session",
            new=AsyncMock(return_value={
                "nodes": self._nodes,
                "slot_count": 2,
                "session_size": 5,
            }),
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        db.DB_PATH = self.previous_db_path
        self.tempdir.cleanup()

    def _make_callback_update(self):
        user = MagicMock(spec=User)
        user.id = 1
        query = AsyncMock()
        query.answer = AsyncMock()
        query.message = AsyncMock(spec=Message)
        query.message.reply_text = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        update = MagicMock(spec=Update)
        update.effective_user = user
        update.callback_query = query
        update.message = None
        return update

    def _make_context_with_session(self):
        context = MagicMock()
        context.user_data = {
            "study_session": {
                "user_id": 1,
                "nodes": self._nodes,
                "current_index": 0,
            }
        }
        return context

    async def test_remember_advances_word_and_moves_next(self):
        with patch("services.db.advance_word_review") as mock_adv:
            update = self._make_callback_update()
            context = self._make_context_with_session()
            await _handle_study_remember(update, context, "100", "0", "2")
        mock_adv.assert_called_once_with(100)
        update.callback_query.answer.assert_awaited_once()

    async def test_again_defers_word_and_moves_next(self):
        with patch("services.db.defer_word_review") as mock_def:
            update = self._make_callback_update()
            context = self._make_context_with_session()
            await _handle_study_again(update, context, "200", "0", "2")
        mock_def.assert_called_once_with(200)
        update.callback_query.answer.assert_awaited_once()

    async def test_next_skips_srs_and_moves_forward(self):
        update = self._make_callback_update()
        context = self._make_context_with_session()
        await _handle_study_next(update, context, "0", "2")
        update.callback_query.answer.assert_awaited_once()

    async def test_last_card_shows_completion_message(self):
        update = self._make_callback_update()
        context = self._make_context_with_session()
        context.user_data["study_session"]["current_index"] = 1
        await _handle_study_next(update, context, "1", "2")
        text = update.callback_query.message.reply_text.await_args[0][0]
        self.assertIn("آخرین کارت", text)
        self.assertNotIn("study_session", context.user_data)

    async def test_send_session_card_uses_keyboard(self):
        with patch("handlers.study_handler.study_session_keyboard") as mock_kb:
            mock_kb.return_value = None
            with patch("handlers.study_handler.format_card", return_value="card"):
                update = self._make_callback_update()
                context = self._make_context_with_session()
                await handle_study_start(update, context)
                update.callback_query.message.reply_text.assert_awaited_once()
