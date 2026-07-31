"""Tests for study handler — session start, auto-advance, quota enforcement."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from handlers import study_handler
from handlers.study_handler import SessionState, advance_session, handle_study_start


class _BaseStudyHandlerTest(unittest.TestCase):
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

    def _update(self, user_id=1):
        update = MagicMock()
        update.effective_user.id = user_id
        update.callback_query = AsyncMock()
        update.callback_query.answer = AsyncMock()
        update.effective_chat.id = 100
        return update

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        return ctx


class TestSessionStateDataclass(_BaseStudyHandlerTest):
    def test_session_state_has_required_fields(self):
        state = SessionState(
            nodes=[], total_cards=0, tier3_context={},
            study_msg_id=None, plan="free",
        )
        self.assertEqual(state.nodes, [])
        self.assertEqual(state.total_cards, 0)
        self.assertIsNone(state.study_msg_id)

    def test_total_cards_is_independent_of_nodes(self):
        state = SessionState(
            nodes=[], total_cards=5, tier3_context={},
            study_msg_id=None, plan="silver",
        )
        self.assertEqual(state.total_cards, 5)
        self.assertEqual(len(state.nodes), 0)


class TestHandleStudyStart(_BaseStudyHandlerTest):
    def test_empty_session_releases_slot(self):
        update = self._update()
        ctx = self._context()
        asyncio.run(handle_study_start(update, ctx))
        # Slot was consumed then released — budget should be 0 used
        budget = db.get_setting("sessions_used_1_*", None)
        # Verify the callback was answered with "no cards" message
        update.callback_query.answer.assert_awaited()
        call_args = update.callback_query.answer.call_args
        self.assertTrue(call_args[1].get("show_alert", False) or "نداری" in call_args[0][0])

    def test_empty_session_does_not_store_session_state(self):
        update = self._update()
        ctx = self._context()
        asyncio.run(handle_study_start(update, ctx))
        self.assertNotIn("current_session", ctx.user_data)

    @patch("handlers.study_handler.build_session_list")
    def test_quota_exceeded_shows_message(self, mock_build):
        mock_build.return_value = ([], {})
        # Consume the slot first
        db.create_user_if_needed(2, "learner2")
        db.set_user_lang_goal(2, "en", "general")
        db.set_user_level(2, "beginner")
        update = self._update(user_id=2)
        ctx = self._context()
        # Manually set the session count to exceed free limit
        from services.scheduling import _session_key
        db.set_setting(_session_key(2), "1")
        asyncio.run(handle_study_start(update, ctx))
        update.callback_query.answer.assert_awaited()
        call_args = update.callback_query.answer.call_args
        self.assertIn("تموم شده", call_args[0][0])

    @patch("handlers.study_handler.build_session_list")
    @patch("handlers.study_handler.consume_session_slot", return_value=True)
    def test_creates_session_state_on_success(self, mock_consume, mock_build):
        from services.session import SessionNode
        node = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "hello"}, source_id=1,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        mock_build.return_value = ([node], {"user_id": 1, "remaining_slots": 0})
        update = self._update()
        ctx = self._context()
        asyncio.run(handle_study_start(update, ctx))
        self.assertIn("current_session", ctx.user_data)
        state = ctx.user_data["current_session"]
        self.assertEqual(state.total_cards, 1)
        self.assertEqual(state.plan, "free")


class TestAdvanceSession(_BaseStudyHandlerTest):
    def _make_state(self, nodes, total_cards=None):
        return SessionState(
            nodes=nodes,
            total_cards=total_cards or len(nodes),
            tier3_context={},
            study_msg_id=999,
            plan="free",
        )

    @patch("handlers.study_handler.generate_tier3_node", return_value=None)
    def test_session_complete_when_no_nodes(self, mock_tier3):
        from services.session import SessionNode
        state = self._make_state([], total_cards=3)
        ctx = self._context()
        ctx.user_data["current_session"] = state
        update = self._update()
        asyncio.run(advance_session(update, ctx))
        ctx.bot.edit_message_text.assert_awaited_once()
        # Session should be cleaned up
        self.assertNotIn("current_session", ctx.user_data)

    @patch("handlers.study_handler.generate_tier3_node", return_value=None)
    def test_advances_to_next_node(self, mock_tier3):
        from services.session import SessionNode
        # Seed real saved words so rendering decodes a real sqlite3.Row
        # (card_data stored as a genuine JSON string by add_saved_word).
        self.assertTrue(db.add_saved_word(1, "hello", "en", {"word": "hello", "fa_meaning": "سلام"}))
        self.assertTrue(db.add_saved_word(1, "world", "en", {"word": "world", "fa_meaning": "جهان"}))
        with db.get_conn() as conn:
            hello_id = conn.execute("SELECT id FROM saved_words WHERE word='hello'").fetchone()["id"]
            world_id = conn.execute("SELECT id FROM saved_words WHERE word='world'").fetchone()["id"]
        node1 = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "hello"}, source_id=hello_id,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        node2 = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "world"}, source_id=world_id,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        state = self._make_state([node1, node2])
        ctx = self._context()
        ctx.user_data["current_session"] = state
        update = self._update()

        asyncio.run(advance_session(update, ctx))

        # Should have popped node1, now showing node2
        self.assertEqual(len(state.nodes), 1)
        self.assertEqual(state.nodes[0].card_data["word"], "world")
        ctx.bot.edit_message_text.assert_awaited_once()

    def test_noop_when_no_session_state(self):
        ctx = self._context()
        update = self._update()
        # Should not raise
        asyncio.run(advance_session(update, ctx))
        ctx.bot.edit_message_text.assert_not_awaited()


class TestStudyStartEntryPoints(_BaseStudyHandlerTest):
    """Item-1 integration coverage: text-menu entry and JSON round-trip."""

    def _text_update(self, user_id=1):
        update = MagicMock()
        update.effective_user.id = user_id
        update.callback_query = None
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        update.effective_chat.id = 100
        return update

    def _events(self):
        with db.get_conn() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT grade, activity_type FROM review_events ORDER BY id"
                ).fetchall()
            ]

    @patch("handlers.study_handler.build_session_list")
    def test_text_entry_quota_full_replies_inline(self, mock_build):
        # Text-menu entry has no callback_query — the reply must go out as a
        # normal message with the real quota message, not crash on None.answer.
        db.create_user_if_needed(2, "learner2")
        db.set_user_lang_goal(2, "en", "general")
        db.set_user_level(2, "beginner")
        from services.scheduling import _session_key
        db.set_setting(_session_key(2), "1")  # free limit is 1 session/day
        update = self._text_update(user_id=2)
        ctx = self._context()
        asyncio.run(handle_study_start(update, ctx))
        update.message.reply_text.assert_awaited_once()
        call_args = update.message.reply_text.call_args
        self.assertIn("تموم شده", call_args[0][0])

    @patch("handlers.study_handler.generate_tier3_node", return_value=None)
    @patch("handlers.study_handler.build_session_list")
    def test_full_session_round_trips_json_card_and_writes_review_event(
        self, mock_build, mock_tier3
    ):
        from services.session import SessionNode
        card = {
            "word": "hello",
            "phonetic": "/həˈloʊ/",
            "fa_meaning": "سلام",
            "fa_explanation": "درود هنگام دیدار",
            "examples": ["Hello there!"],
            "example_translations": ["سلام!"],
            "grammar_tip": "سلام به انگلیسی hello است.",
        }
        self.assertTrue(db.add_saved_word(1, "hello", "en", card))
        with db.get_conn() as conn:
            word_id = conn.execute(
                "SELECT id FROM saved_words WHERE word='hello'"
            ).fetchone()["id"]
        node = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "hello"}, source_id=word_id,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        mock_build.return_value = ([node], {"user_id": 1})

        update = self._update()
        ctx = self._context()
        asyncio.run(handle_study_start(update, ctx))

        # Rendering must decode the stored JSON string from a real
        # sqlite3.Row (add_saved_word stores card_data as JSON text).
        ctx.bot.send_message.assert_awaited_once()
        rendered = ctx.bot.send_message.call_args.kwargs.get("text") or ctx.bot.send_message.call_args[0][1]
        # Round-trip proof: these fields live only inside the card_data JSON
        # string, so their presence means the real sqlite3.Row was decoded.
        self.assertIn("hello", rendered)
        self.assertIn("/həˈloʊ/", rendered)
        self.assertIn("سلام", rendered)
        # Full card via format_card — the hidden SRS instruction is not shown.
        self.assertNotIn("مرور فاصله", rendered)
        # Persian-digit progress footer (pipe escaped by MarkdownV2).
        self.assertIn("نشست ۱ \\| کارت ۱ از ۱", rendered)

        # Grade through the real callback route with the live session.
        import bot
        from bot import callback_router
        # Order-independence: earlier tests may leave the circuit breaker
        # armed (test_reliability sets bot._telegram_offline=True and never
        # restores it). Reset so callback_router reaches the grade handler.
        bot._telegram_offline = False
        grade_update = MagicMock()
        grade_update.effective_user.id = 1
        grade_update.callback_query = MagicMock()
        grade_update.callback_query.answer = AsyncMock()
        grade_update.callback_query.data = f"srs:3:1:{word_id}"
        grade_update.effective_chat.id = 100
        asyncio.run(callback_router(grade_update, ctx))

        # Review event persisted with the resolved grade and activity type.
        events = self._events()
        self.assertTrue(events, "expected at least one review event")
        self.assertEqual(events[-1]["grade"], 3)
        self.assertEqual(events[-1]["activity_type"], "srs_review")
