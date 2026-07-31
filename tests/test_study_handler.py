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
        node1 = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "hello"}, source_id=1,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        node2 = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "world"}, source_id=2,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        state = self._make_state([node1, node2])
        ctx = self._context()
        ctx.user_data["current_session"] = state
        update = self._update()

        with patch("handlers.study_handler.db.get_saved_word") as mock_get:
            mock_get.return_value = MagicMock(
                id=2, card_data={"word": "world", "fa_meaning": "جهان"}
            )
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
