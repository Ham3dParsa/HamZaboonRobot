"""Integration flow — study-session restart persistence (Bug 1).

Contract (locked 2026-08-15, both rules Option A):
- Rule 1: the active study session is persisted to SQLite so an in-progress
  session survives a bot restart.
- Rule 2: «شروع مطالعه امروز» resumes a persisted session only when its
  `session_date` equals today; an overnight session is discarded and a fresh
  session is built (quota consumed normally).

Drives the real handlers (handle_study_start / callback_router / grade paths).
A "restart" is simulated by invoking the handler with a fresh context whose
`user_data` is empty (the in-memory session dict is gone) while the DB row
persisted by the pre-restart handler still exists.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from telegram.error import BadRequest


class StudySessionRestartFlowTest(unittest.TestCase):
    def setUp(self):
        import bot

        self.offline_patcher = patch.object(bot, "_telegram_offline", False)
        self.offline_patcher.start()
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")

    def tearDown(self):
        self.offline_patcher.stop()
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _card(self, word):
        return {
            "word": word,
            "phonetic": "/w/",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "synonyms": ["hi"],
            "antonyms": ["bye"],
            "examples": [f"{word} there!"],
            "example_translations": ["سلام!"],
            "grammar_tip": "نکته",
        }

    def _seed_word(self, word, expose=False):
        db.add_saved_word(1, word, "en", self._card(word))
        with db.get_conn() as conn:
            word_id = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()["id"]
        if expose:
            self.assertTrue(db.grade_first_exposure(word_id, 3, 1).ok)
        return word_id

    def _node(self, activity, word_id):
        from services.session import SessionNode
        return SessionNode(
            activity_type=activity, source_tier=1,
            card_data={"word": "hello"}, source_id=word_id,
            activity_meta={"user_id": 1}, grade_policy_ref=activity,
        )

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        # T4: completion summary ships via Backend.RICH (do_api_request).
        ctx.bot.do_api_request = AsyncMock(return_value={"message_id": 5})
        return ctx

    def _study_update(self):
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 100
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        return update

    def _callback_update(self, data):
        query = MagicMock()
        query.answer = AsyncMock()
        query.message = MagicMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 100
        update.callback_query = query
        update.callback_query.data = data
        return update

    def _sessions_used(self):
        from services.scheduling import _session_key
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (_session_key(1),),
            ).fetchone()
        return int(row["value"]) if row else 0

    def _persisted_row(self):
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT session_date FROM study_sessions WHERE user_id=1"
            ).fetchone()

    def test_restart_resumes_same_session_and_does_not_consume_extra_slot(self):
        """Rule 1 + 2: after a restart, «شروع مطالعه امروز» resumes the
        persisted session (card 2 of 2) instead of building a fresh one, and
        the session quota is not double-consumed."""
        from handlers.study_handler import handle_study_start
        from bot import callback_router

        w1 = self._seed_word("hello", expose=True)
        w2 = self._seed_word("world", expose=True)
        node1 = self._node("srs_review", w1)
        node2 = self._node("srs_review", w2)

        # Start the session with 2 cards.
        with patch("handlers.study_handler.build_session_list",
                   return_value=([node1, node2], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            asyncio.run(handle_study_start(self._study_update(), ctx))

        self.assertEqual(self._sessions_used(), 1)
        self.assertIsNotNone(self._persisted_row())

        # Grade card 1 -> advance to card 2; the DB row tracks the remaining node.
        grade_update = self._callback_update(f"srs:3:1:{w1}")
        asyncio.run(callback_router(grade_update, ctx))
        self.assertTrue(ctx.user_data["current_session"].nodes)
        self.assertEqual(len(ctx.user_data["current_session"].nodes), 1)
        self.assertIsNotNone(self._persisted_row())

        # Simulate a restart: fresh context with empty user_data, same DB.
        ctx2 = self._context()
        asyncio.run(handle_study_start(self._study_update(), ctx2))

        # Resume message sent; card 2 of 2 rendered; no extra slot consumed.
        self.assertIsNotNone(ctx2.bot.send_message)
        self.assertEqual(self._sessions_used(), 1)
        footer = ctx2.bot.send_message.call_args.kwargs["text"]
        self.assertIn("کارت ۲ از ۲", footer)
        self.assertIn("نشست ۱", footer)

    def test_restart_does_not_build_new_session(self):
        """Rule 1: resuming from the persisted row must not call
        build_session_list (no fresh assembly, no fresh quota)."""
        from handlers.study_handler import handle_study_start

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node1], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            asyncio.run(handle_study_start(self._study_update(), ctx))

        ctx2 = self._context()
        with patch("handlers.study_handler.build_session_list") as mock_build:
            asyncio.run(handle_study_start(self._study_update(), ctx2))
            mock_build.assert_not_called()

    def test_stale_day_row_is_discarded_and_fresh_session_built(self):
        """Rule 2: a persisted session from a prior day is discarded; a fresh
        session is assembled and a slot is consumed."""
        from handlers.study_handler import handle_study_start

        import datetime
        from config import APP_TZ
        yesterday = (datetime.datetime.now(APP_TZ).date()
                     - datetime.timedelta(days=1)).isoformat()
        db.save_study_session(1, yesterday, '{"nodes": [], "total_cards": 0}')

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node1], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            asyncio.run(handle_study_start(self._study_update(), ctx))

        # Fresh session was built (a slot consumed) and the stale row was
        # discarded — the new persisted row now carries today's date.
        self.assertEqual(self._sessions_used(), 1)
        self.assertIsNotNone(self._persisted_row())
        import datetime
        from config import APP_TZ
        self.assertEqual(
            self._persisted_row()["session_date"],
            datetime.datetime.now(APP_TZ).date().isoformat(),
        )

    def test_completion_clears_persisted_row(self):
        """Rule 1: when a session completes, the DB row is cleared so a later
        «شروع مطالعه امروز» starts a brand-new session."""
        from handlers.study_handler import handle_study_start
        from bot import callback_router

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node1], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            asyncio.run(handle_study_start(self._study_update(), ctx))

        self.assertIsNotNone(self._persisted_row())

        grade_update = self._callback_update(f"srs:3:1:{w1}")
        asyncio.run(callback_router(grade_update, ctx))
        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(self._persisted_row())

    def test_completion_clears_row_after_message(self):
        """Bug report 2026-08-19 (overturns the 2026-08-15 clear-before-send
        decision): the completion/report message is rendered FIRST and only on
        success is the row cleared. If the completion edit fails (weak network),
        the session is rolled back and preserved so a re-tap of the already
        graded last card retries the edit and the session still completes —
        never a stuck, re-gradable card with no report."""
        from handlers.study_handler import handle_study_start
        from bot import callback_router

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node1], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            asyncio.run(handle_study_start(self._study_update(), ctx))
            self.assertIsNotNone(self._persisted_row())

        # Completion message send fails: the session must be rolled back and
        # preserved (self-healing), NOT cleared, so the next tap can retry.
        # T4: the completion report ships via do_api_request (RICH).
        ctx.bot.do_api_request = AsyncMock(side_effect=RuntimeError("boom"))
        grade_update = self._callback_update(f"srs:3:1:{w1}")
        asyncio.run(callback_router(grade_update, ctx))
        self.assertIn("current_session", ctx.user_data)
        self.assertIsNotNone(self._persisted_row())

        # Re-tap of the already-graded last card: skips the re-grade (no double
        # grade), retries the completion edit which now succeeds, and only then
        # clears the row — the session completes and shows the report.
        ctx.bot.do_api_request = AsyncMock(return_value={"message_id": 5})
        asyncio.run(callback_router(grade_update, ctx))
        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(self._persisted_row())

    def test_completion_badrequest_ends_session_with_minimal_fallback(self):
        """kilo r3816695425: a permanent completion-edit BadRequest (message
        not found / not modified / MarkdownV2 parse error) must end the session
        (no re-tap soft-lock) AND surface a minimal plain-text completion so a
        report escaping regression is never a silent report loss."""
        from handlers.study_handler import handle_study_start
        from bot import callback_router

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node1], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            asyncio.run(handle_study_start(self._study_update(), ctx))
            self.assertIsNotNone(self._persisted_row())

        # Completion edit fails permanently (e.g. "can't parse entities") on
        # both the Rich seam and its MDV2 fallback.
        # T4: the completion report ships via do_api_request (RICH).
        ctx.bot.do_api_request = AsyncMock(
            side_effect=BadRequest("Bad Request: can't parse entities")
        )
        ctx.bot.edit_message_text = AsyncMock(
            side_effect=BadRequest("Bad Request: can't parse entities")
        )
        grade_update = self._callback_update(f"srs:3:1:{w1}")
        asyncio.run(callback_router(grade_update, ctx))

        # The session ended (cleared), and a minimal completion was sent so the
        # learner still sees a finish signal.
        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(self._persisted_row())
        sent = ctx.bot.send_message.call_args.kwargs["text"]
        self.assertIn("جلسه مطالعه تموم شد", sent)

    def test_completion_not_modified_clears_session_without_duplicate_fallback(self):
        """kilo r3816832249: when the completion edit returns "message is not
        modified" the completion is already on screen — treat it as success:
        clear the session and do NOT send a duplicate fallback message."""
        from handlers.study_handler import handle_study_start
        from bot import callback_router

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node1], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            asyncio.run(handle_study_start(self._study_update(), ctx))
            self.assertIsNotNone(self._persisted_row())

        ctx.bot.send_message.reset_mock()
        # T4: the completion report ships via do_api_request (RICH); a
        # "not modified" Rich failure falls back to the MDV2 edit, which the
        # handler then treats as already-on-screen success.
        ctx.bot.do_api_request = AsyncMock(
            side_effect=BadRequest("Bad Request: message is not modified")
        )
        grade_update = self._callback_update(f"srs:3:1:{w1}")
        asyncio.run(callback_router(grade_update, ctx))

        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(self._persisted_row())
        ctx.bot.send_message.assert_not_awaited()

    def test_persist_attempted_before_first_card_render(self):
        """Owner decision 2026-08-15: the session is persisted to the DB before
        the first card is rendered, so a DB failure is surfaced before any card
        reaches the screen."""
        from handlers.study_handler import handle_study_start
        from services.session import store as session_store

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        save_spy = MagicMock(wraps=session_store.save_study_session)
        with patch("handlers.study_handler.build_session_list",
                   return_value=([node1], {"user_id": 1, "remaining_slots": 0})), \
                patch.object(session_store, "save_study_session", save_spy):
            ctx = self._context()
            # send_message fails AFTER persist; row must be cleared by the handler.
            ctx.bot.send_message = AsyncMock(side_effect=RuntimeError("render boom"))
            asyncio.run(handle_study_start(self._study_update(), ctx))
            self.assertTrue(save_spy.called)
            self.assertIsNone(self._persisted_row())
            self.assertNotIn("current_session", ctx.user_data)


if __name__ == "__main__":
    unittest.main()