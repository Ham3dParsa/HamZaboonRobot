"""Integration flow for #338 Phase 2 + CARD-MODES T2/T3.

Drives the real callback_router + handlers through the full user journey:
study start -> front stage -> reveal -> back stage + grades -> grade -> advance,
plus the first-exposure staged path (front + new-card badge -> reveal -> FE
grade grid -> grade -> advance) and the immediate-mode variants for both card
types (full card + grade grid directly, no reveal).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class StagedRevealFlowTest(unittest.TestCase):
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

    def _events(self):
        with db.get_conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT grade, activity_type FROM review_events ORDER BY id"
            ).fetchall()]

    def test_review_flow_front_reveal_grade_advance(self):
        from handlers.study_handler import handle_study_start
        from bot import callback_router

        word_id = self._seed_word("hello", expose=True)
        node = self._node("srs_review", word_id)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node], {"user_id": 1, "remaining_slots": 0})):
            from services.utils import formatting as fmt
            ctx = self._context()
            # Force the "standard" prompt so the meaning stays hidden on the front.
            with patch.object(fmt.random, "randrange", return_value=0):
                asyncio.run(handle_study_start(self._study_update(), ctx))

        # Front stage sent: meaning hidden, reveal action present, no grades yet.
        front = ctx.bot.send_message.call_args.kwargs["text"]
        self.assertIn("نمایش پاسخ", front)
        self.assertNotIn("سلام", front)
        front_kb = ctx.bot.send_message.call_args.kwargs["reply_markup"]
        front_cbs = [b.callback_data for row in front_kb.inline_keyboard for b in row]
        self.assertEqual(front_cbs, [f"srs:reveal:1:{word_id}"])
        self.assertTrue(ctx.user_data.get(f"prompt_type_{word_id}"))
        self.assertTrue(ctx.user_data.get(f"card_shown_at_{word_id}"))

        # Reveal: the same message (999) becomes the back stage with grades.
        ctx.bot.edit_message_text.reset_mock()
        reveal_update = self._callback_update(f"srs:reveal:1:{word_id}")
        asyncio.run(callback_router(reveal_update, ctx))
        ctx.bot.edit_message_text.assert_awaited_once()
        back_kwargs = ctx.bot.edit_message_text.call_args.kwargs
        self.assertEqual(back_kwargs["message_id"], 999)
        self.assertIn("سلام", back_kwargs["text"])
        back_kb = back_kwargs["reply_markup"]
        back_cbs = [b.callback_data for row in back_kb.inline_keyboard for b in row]
        # Pronounce is free to every plan (J-B6, 2026-08-17), so the grade grid is
        # followed by the 🔊 button for the default free test user.
        self.assertEqual(back_cbs, [
            f"srs:2:1:{word_id}", f"srs:1:1:{word_id}",
            f"srs:4:1:{word_id}", f"srs:3:1:{word_id}",
            f"srs:delete:1:{word_id}",
            f"tts:pronounce:s:1:{word_id}",
        ])
        self.assertTrue(ctx.user_data.get(f"revealed_{word_id}"))

        # Grade: telemetry persisted, session advances to completion.
        grade_update = self._callback_update(f"srs:3:1:{word_id}")
        asyncio.run(callback_router(grade_update, ctx))
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[-1]["grade"], 3)
        self.assertEqual(events[-1]["activity_type"], "srs_review")
        self.assertNotIn("current_session", ctx.user_data)  # session completed

    def test_first_exposure_staged_flow_front_reveal_grade_advance(self):
        """CARD-MODES Rule 1: default staged FE flow — hidden front stage with
        badge + reveal -> back stage + FE grade grid -> grade -> advance."""
        from handlers.study_handler import handle_study_start
        from bot import callback_router
        from services.utils import formatting as fmt

        word_id = self._seed_word("hello", expose=False)
        node = self._node("first_exposure", word_id)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            with patch.object(fmt.random, "randrange", return_value=0):
                asyncio.run(handle_study_start(self._study_update(), ctx))

        # Front stage sent: badge present, meaning hidden, reveal action, no grades.
        front = ctx.bot.send_message.call_args.kwargs["text"]
        self.assertIn("کارت جدید ✨", front)
        self.assertNotIn("سلام", front)
        front_kb = ctx.bot.send_message.call_args.kwargs["reply_markup"]
        front_cbs = [b.callback_data for row in front_kb.inline_keyboard for b in row]
        self.assertEqual(front_cbs, [f"srs:reveal:1:{word_id}"])
        self.assertTrue(ctx.user_data.get(f"prompt_type_{word_id}"))
        self.assertTrue(ctx.user_data.get(f"card_shown_at_{word_id}"))

        # Reveal: same message (999) becomes the back stage with FE grade grid.
        ctx.bot.edit_message_text.reset_mock()
        reveal_update = self._callback_update(f"srs:reveal:1:{word_id}")
        asyncio.run(callback_router(reveal_update, ctx))
        ctx.bot.edit_message_text.assert_awaited_once()
        back_kwargs = ctx.bot.edit_message_text.call_args.kwargs
        self.assertEqual(back_kwargs["message_id"], 999)
        self.assertIn("سلام", back_kwargs["text"])
        self.assertIn("ترجمه", back_kwargs["text"])  # Rule 3: translations follow toggle
        back_kb = back_kwargs["reply_markup"]
        back_cbs = [b.callback_data for row in back_kb.inline_keyboard for b in row]
        self.assertEqual(back_cbs, [
            f"srs:fe:2:1:{word_id}", f"srs:fe:1:1:{word_id}",
            f"srs:fe:4:1:{word_id}", f"srs:fe:3:1:{word_id}",
            f"srs:delete:1:{word_id}",
            f"tts:pronounce:s:1:{word_id}",
        ])
        self.assertTrue(ctx.user_data.get(f"revealed_{word_id}"))

        # Grade the familiarity rating; session advances to completion.
        grade_update = self._callback_update(f"srs:fe:3:1:{word_id}")
        asyncio.run(callback_router(grade_update, ctx))
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[-1]["activity_type"], "first_exposure")
        self.assertNotIn("current_session", ctx.user_data)  # session completed

    def test_first_exposure_immediate_flow_full_card_grade_advance(self):
        """CARD-MODES Rule 1: immediate FE mode shows the full card with badge
        and drops straight onto the FE grade grid (no front/reveal)."""
        from handlers.study_handler import handle_study_start
        from bot import callback_router

        db.set_global_card_mode("first_exposure", "immediate")
        word_id = self._seed_word("hello", expose=False)
        node = self._node("first_exposure", word_id)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            asyncio.run(handle_study_start(self._study_update(), ctx))

        # Full card + badge + FE grade grid immediately; no reveal action.
        front = ctx.bot.send_message.call_args.kwargs["text"]
        self.assertIn("کارت جدید ✨", front)
        self.assertIn("سلام", front)
        front_kb = ctx.bot.send_message.call_args.kwargs["reply_markup"]
        front_cbs = [b.callback_data for row in front_kb.inline_keyboard for b in row]
        self.assertEqual(front_cbs, [
            f"srs:fe:2:1:{word_id}", f"srs:fe:1:1:{word_id}",
            f"srs:fe:4:1:{word_id}", f"srs:fe:3:1:{word_id}",
            f"srs:delete:1:{word_id}",
            f"tts:pronounce:s:1:{word_id}",
        ])

        # Grade the familiarity rating; session advances to completion.
        grade_update = self._callback_update(f"srs:fe:3:1:{word_id}")
        asyncio.run(callback_router(grade_update, ctx))
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[-1]["activity_type"], "first_exposure")
        self.assertNotIn("current_session", ctx.user_data)  # session completed

    def test_review_immediate_flow_full_card_grade_advance(self):
        """CARD-MODES Rule 2: review immediate mode renders the full card +
        review grade grid directly (no front/reveal, no prompt stash)."""
        from handlers.study_handler import handle_study_start
        from bot import callback_router

        db.set_global_card_mode("review", "immediate")
        word_id = self._seed_word("hello", expose=True)
        node = self._node("srs_review", word_id)

        with patch("handlers.study_handler.build_session_list",
                   return_value=([node], {"user_id": 1, "remaining_slots": 0})):
            ctx = self._context()
            asyncio.run(handle_study_start(self._study_update(), ctx))

        # Full card + review grade grid immediately; no reveal action, no stash.
        front = ctx.bot.send_message.call_args.kwargs["text"]
        self.assertIn("سلام", front)
        self.assertNotIn("نمایش پاسخ", front)
        front_kb = ctx.bot.send_message.call_args.kwargs["reply_markup"]
        front_cbs = [b.callback_data for row in front_kb.inline_keyboard for b in row]
        # Pronounce is free to every plan (J-B6, 2026-08-17), so the grade grid is
        # followed by the 🔊 button for the default free test user.
        self.assertEqual(front_cbs, [
            f"srs:2:1:{word_id}", f"srs:1:1:{word_id}",
            f"srs:4:1:{word_id}", f"srs:3:1:{word_id}",
            f"srs:delete:1:{word_id}",
            f"tts:pronounce:s:1:{word_id}",
        ])
        self.assertNotIn(f"prompt_type_{word_id}", ctx.user_data)
        self.assertNotIn(f"card_shown_at_{word_id}", ctx.user_data)

        # Grade; session advances to completion.
        grade_update = self._callback_update(f"srs:3:1:{word_id}")
        asyncio.run(callback_router(grade_update, ctx))
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[-1]["activity_type"], "srs_review")
        self.assertNotIn("current_session", ctx.user_data)  # session completed


if __name__ == "__main__":
    unittest.main()