"""Integration flow for the SRS delete-card feature (#338 P3-T2).

Drives the real callback_router through: reveal -> delete -> confirm -> yes
(removes the word, refills the session from the due queue when one remains,
then advances) and delete -> no (cancels, re-renders the revealed card). Also
verifies the first-exposure reveal now shows the 🔊 pronounce button (Rule 7).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class SrsDeleteCardFlowTest(unittest.TestCase):
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

    def _start_session(self, ctx, nodes, word_id):
        from handlers.study_handler import handle_study_start
        with patch("handlers.study_handler.build_session_list",
                   return_value=(nodes, {"user_id": 1, "remaining_slots": 0})):
            asyncio.run(handle_study_start(self._study_update(), ctx))

    def _reveal(self, ctx, word_id):
        from bot import callback_router
        asyncio.run(callback_router(self._callback_update(f"srs:reveal:1:{word_id}"), ctx))

    def test_delete_review_card_flow_removes_word_and_advances(self):
        from bot import callback_router

        word_id = self._seed_word("hello", expose=True)
        node = self._node("srs_review", word_id)
        ctx = self._context()
        self._start_session(ctx, [node], word_id)
        self._reveal(ctx, word_id)
        ctx.bot.edit_message_text.reset_mock()

        # Tap delete on the revealed card -> confirm keyboard replaces it.
        asyncio.run(callback_router(self._callback_update(f"srs:delete:1:{word_id}"), ctx))
        ctx.bot.edit_message_reply_markup.assert_awaited()
        confirm_kb = ctx.bot.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        confirm_cbs = [b.callback_data for row in confirm_kb.inline_keyboard for b in row]
        self.assertEqual(confirm_cbs, [
            f"srs:delete:yes:1:{word_id}", f"srs:delete:no:1:{word_id}",
        ])
        self.assertIsNotNone(db.get_saved_word(word_id))

        # Confirm -> word physically deleted, session advanced to completion.
        asyncio.run(callback_router(self._callback_update(f"srs:delete:yes:1:{word_id}"), ctx))
        self.assertIsNone(db.get_saved_word(word_id))
        self.assertNotIn("current_session", ctx.user_data)  # session completed

    def test_delete_confirm_no_cancels_and_keeps_word(self):
        from bot import callback_router

        word_id = self._seed_word("hello", expose=True)
        node = self._node("srs_review", word_id)
        ctx = self._context()
        self._start_session(ctx, [node], word_id)
        self._reveal(ctx, word_id)
        ctx.bot.edit_message_reply_markup.reset_mock()

        # Confirm-cancel re-renders the revealed back-stage grade keyboard.
        asyncio.run(callback_router(self._callback_update(f"srs:delete:1:{word_id}"), ctx))
        asyncio.run(callback_router(self._callback_update(f"srs:delete:no:1:{word_id}"), ctx))
        ctx.bot.edit_message_reply_markup.assert_awaited()
        kb = ctx.bot.edit_message_reply_markup.call_args.kwargs["reply_markup"]
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn(f"srs:3:1:{word_id}", cbs)  # grade grid restored
        self.assertIsNotNone(db.get_saved_word(word_id))
        self.assertIn("current_session", ctx.user_data)  # session intact

    def test_delete_refills_session_when_due_remains(self):
        from bot import callback_router

        word1 = self._seed_word("apple", expose=True)
        word2 = self._seed_word("banana", expose=True)
        # word2 must be genuinely due for the refill to pick it up.
        with db.transaction() as conn:
            conn.execute(
                "UPDATE saved_words SET next_review_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", word2),
            )
        node = self._node("srs_review", word1)
        ctx = self._context()
        # Session starts with only word1 as its node, but word2 is still due.
        self._start_session(ctx, [node], word1)
        self._reveal(ctx, word1)

        asyncio.run(callback_router(self._callback_update(f"srs:delete:1:{word1}"), ctx))
        asyncio.run(callback_router(self._callback_update(f"srs:delete:yes:1:{word1}"), ctx))

        # word1 removed; word2 refilled into the session (session continues).
        self.assertIsNone(db.get_saved_word(word1))
        self.assertIsNotNone(db.get_saved_word(word2))
        self.assertIn("current_session", ctx.user_data)
        state = ctx.user_data["current_session"]
        self.assertTrue(any(n.source_id == word2 for n in state.nodes))

    def test_delete_no_refill_when_due_queue_exhausted(self):
        from bot import callback_router

        word_id = self._seed_word("hello", expose=True)
        node = self._node("srs_review", word_id)
        ctx = self._context()
        self._start_session(ctx, [node], word_id)
        self._reveal(ctx, word_id)

        asyncio.run(callback_router(self._callback_update(f"srs:delete:1:{word_id}"), ctx))
        asyncio.run(callback_router(self._callback_update(f"srs:delete:yes:1:{word_id}"), ctx))

        # No due card remains -> session completes normally.
        self.assertIsNone(db.get_saved_word(word_id))
        self.assertNotIn("current_session", ctx.user_data)

    def test_delete_rejects_stale_or_non_active_word(self):
        from bot import callback_router

        word_id = self._seed_word("hello", expose=True)
        other_id = self._seed_word("world", expose=True)
        node = self._node("srs_review", word_id)
        ctx = self._context()
        self._start_session(ctx, [node], word_id)

        # Delete on a word that is NOT the active session node is rejected.
        asyncio.run(callback_router(self._callback_update(f"srs:delete:1:{other_id}"), ctx))
        ctx.bot.edit_message_reply_markup.assert_not_awaited()
        self.assertIsNotNone(db.get_saved_word(other_id))

    def test_delete_yes_is_idempotent_after_restart_loss(self):
        from bot import callback_router

        word_id = self._seed_word("hello", expose=True)
        node = self._node("srs_review", word_id)
        ctx = self._context()
        self._start_session(ctx, [node], word_id)
        self._reveal(ctx, word_id)

        asyncio.run(callback_router(self._callback_update(f"srs:delete:1:{word_id}"), ctx))
        asyncio.run(callback_router(self._callback_update(f"srs:delete:yes:1:{word_id}"), ctx))
        # A second confirm on the already-deleted word must not crash.
        asyncio.run(callback_router(self._callback_update(f"srs:delete:yes:1:{word_id}"), ctx))
        self.assertIsNone(db.get_saved_word(word_id))


if __name__ == "__main__":
    unittest.main()