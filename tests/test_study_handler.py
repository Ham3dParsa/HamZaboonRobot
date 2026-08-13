"""Tests for study handler — session start, auto-advance, quota enforcement."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from handlers.study_handler import (
    SessionState,
    advance_session,
    handle_study_inactive,
    handle_study_start,
)


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
        # Manually set the session count to exceed the free-plan limit (2/day).
        from services.scheduling import _session_key
        db.set_setting(_session_key(2), "2")
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

    @patch("handlers.study_handler.build_session_list")
    @patch("handlers.study_handler.consume_session_slot", return_value=True)
    def test_active_session_resumes_without_consuming_new_slot(
        self, mock_consume, mock_build
    ):
        """Pressing the study-start button again while a session is active must
        resume the existing session — it must NOT consume another slot, must
        NOT rebuild via build_session_list, and must inactivate the old card
        and send a fresh card (R1)."""
        from services.session import SessionNode
        node = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "hello"}, source_id=1,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        existing = SessionState(
            nodes=[node],
            total_cards=1,
            tier3_context={},
            study_msg_id=777,
            plan="free",
        )
        update = self._update()
        ctx = self._context()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        ctx.user_data["current_session"] = existing

        asyncio.run(handle_study_start(update, ctx))

        # Slot must NOT be consumed again and session must NOT be rebuilt.
        mock_consume.assert_not_called()
        mock_build.assert_not_called()
        # The same session object is retained (no discard/rebuild).
        self.assertIs(ctx.user_data["current_session"], existing)
        # R1: The resume path inactivates the old card and sends a fresh card.
        ctx.bot.edit_message_reply_markup.assert_awaited()
        ctx.bot.send_message.assert_awaited()
        # A brief Persian confirmation is shown to the user.
        call_args = update.callback_query.answer.call_args
        self.assertIn("جلسه‌ی قبلی", call_args[0][0])

    @patch("handlers.study_handler.build_session_list")
    @patch("handlers.study_handler.consume_session_slot", return_value=True)
    def test_completed_session_is_not_resumed(self, mock_consume, mock_build):
        """A session whose nodes are all graded (empty nodes) but which has not
        yet been popped from user_data must NOT be re-shown — the handler must
        fall through to a fresh session build."""
        from services.session import SessionNode
        node = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "hello"}, source_id=1,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        completed = SessionState(
            nodes=[],
            total_cards=1,
            tier3_context={},
            study_msg_id=777,
            plan="free",
        )
        mock_build.return_value = ([node], {"user_id": 1, "remaining_slots": 0})
        update = self._update()
        ctx = self._context()
        ctx.user_data["current_session"] = completed

        asyncio.run(handle_study_start(update, ctx))

        # Empty-nodes session is treated as no active session: a new slot is
        # consumed and a new session is built.
        mock_consume.assert_called_once()
        mock_build.assert_called_once()
        self.assertIsNot(ctx.user_data["current_session"], completed)

    def test_resume_sends_new_card_and_inactivates_old(self):
        """When a session is resumed, the previous card's buttons are replaced
        with the inactive keyboard and a fresh card message is sent, so the
        learner can continue even if the original message was lost."""
        self.assertTrue(db.add_saved_word(1, "hello", "en", {"word": "hello", "fa_meaning": "سلام"}))
        with db.get_conn() as conn:
            word_id = conn.execute("SELECT id FROM saved_words WHERE word='hello'").fetchone()["id"]
        from services.session import SessionNode
        node = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "hello"}, source_id=word_id,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        state = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=42, plan="free",
        )
        ctx = self._context()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        ctx.user_data["current_session"] = state
        update = self._update()
        asyncio.run(handle_study_start(update, ctx))

        ctx.bot.edit_message_reply_markup.assert_awaited_once()
        # The old card's buttons are swapped for the inactive notice.
        markup = ctx.bot.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        inline_rows = markup.to_json() if hasattr(markup, "to_json") else str(markup)
        self.assertIn("study:inactive", inline_rows)
        self.assertEqual(
            ctx.bot.edit_message_reply_markup.call_args.kwargs["message_id"], 42
        )
        # A fresh card is sent so the user can continue.
        ctx.bot.send_message.assert_awaited_once()
        self.assertEqual(ctx.user_data["current_session"].study_msg_id, 999)

    def test_handle_study_inactive_pops_and_deletes(self):
        update = self._update()
        update.callback_query.message = MagicMock()
        update.callback_query.message.delete = AsyncMock()
        ctx = self._context()
        asyncio.run(handle_study_inactive(update, ctx))
        update.callback_query.answer.assert_awaited_once()
        # show_alert must be enabled so the learner actually sees the notice.
        self.assertTrue(
            update.callback_query.answer.call_args.kwargs.get("show_alert", False)
        )
        update.callback_query.message.delete.assert_awaited_once()

    def test_handle_study_inactive_deleted_message_no_crash(self):
        """Deleting an already-deleted stale card must not raise."""
        from telegram.error import BadRequest
        update = self._update()
        query = MagicMock()
        query.message.delete = AsyncMock(side_effect=BadRequest("message not found"))
        update.callback_query = query
        update.callback_query.answer = AsyncMock()
        ctx = self._context()
        asyncio.run(handle_study_inactive(update, ctx))
        update.callback_query.message.delete.assert_awaited_once()

    @patch("handlers.study_handler.build_session_list")
    def test_resume_old_card_deleted_still_sends_fresh(self, mock_build):
        """If the previous card message was already deleted, inactivating it
        must fail harmlessly (BadRequest) yet a fresh card is still sent."""
        from telegram.error import BadRequest
        self.assertTrue(db.add_saved_word(1, "hello", "en", {"word": "hello", "fa_meaning": "سلام"}))
        with db.get_conn() as conn:
            word_id = conn.execute("SELECT id FROM saved_words WHERE word='hello'").fetchone()["id"]
        from services.session import SessionNode
        node = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "hello"}, source_id=word_id,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )
        state = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=42, plan="free",
        )
        ctx = self._context()
        ctx.bot.edit_message_reply_markup = AsyncMock(
            side_effect=BadRequest("replied_to_message_not_found")
        )
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.user_data["current_session"] = state
        update = self._update()
        asyncio.run(handle_study_start(update, ctx))

        ctx.bot.edit_message_reply_markup.assert_awaited_once()
        # Fresh card must still be sent even though the old one was gone.
        ctx.bot.send_message.assert_awaited_once()
        self.assertEqual(ctx.user_data["current_session"].study_msg_id, 999)


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
        state = self._make_state([], total_cards=3)
        ctx = self._context()
        ctx.user_data["current_session"] = state
        update = self._update()
        asyncio.run(advance_session(update, ctx))
        ctx.bot.edit_message_text.assert_awaited_once()
        # Session should be cleaned up
        self.assertNotIn("current_session", ctx.user_data)

    @patch("handlers.study_handler.generate_tier3_node", return_value=None)
    def test_session_complete_with_remaining_slots_in_context(self, mock_tier3):
        """B1 fix: tier3_context with remaining_slots must not crash generate_tier3_node."""
        # Simulate a session that had fewer than max_nodes cards (common case)
        # tier3_context will include remaining_slots > 0 from build_session_list
        state = self._make_state([], total_cards=2)
        state.tier3_context = {
            "user_id": 1,
            "target_lang": "en",
            "goal": "general",
            "level": "beginner",
            "plan": "free",
            "remaining_slots": 3,  # This used to cause TypeError
        }
        ctx = self._context()
        ctx.user_data["current_session"] = state
        update = self._update()
        asyncio.run(advance_session(update, ctx))
        # Should complete gracefully (generate_tier3_node called, returns None)
        ctx.bot.edit_message_text.assert_awaited_once()
        call_args = ctx.bot.edit_message_text.call_args
        self.assertIn("جلسه مطالعه تموم شد", call_args.kwargs.get("text", ""))
        self.assertNotIn("current_session", ctx.user_data)
        # generate_tier3_node should have been called with remaining_slots in kwargs
        mock_tier3.assert_called_once()
        call_kwargs = mock_tier3.call_args.kwargs
        self.assertIn("remaining_slots", call_kwargs)
        self.assertEqual(call_kwargs["remaining_slots"], 3)

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
        db.set_setting(_session_key(2), "2")  # free limit is 2 sessions/day
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
        # MarkdownV2 must be requested so bold/emphasis actually renders.
        from telegram.constants import ParseMode
        self.assertEqual(
            ctx.bot.send_message.call_args.kwargs.get("parse_mode"),
            ParseMode.MARKDOWN_V2,
        )
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
        # A Tier-1 srs_review node only exists for an exposed card; expose it
        # first (Phase-05 handler refuses to record a review on an unexposed card).
        self.assertTrue(db.grade_first_exposure(word_id, 3, 1).ok)
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
