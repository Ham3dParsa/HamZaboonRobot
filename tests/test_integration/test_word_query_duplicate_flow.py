"""Locked contract #344 R7 — duplicate-word retrieve-vs-new flow.

Drives the real bot.text_router (ask) and bot.callback_router (query:dup:*)
through the duplicate-detection path:

- First ask of a word persists a card (quota consumed, AI called).
- Re-asking the SAME word detects a prior unexpired card and offers a 2-button
  choice (query:dup:new / query:dup:reuse) WITHOUT consuming quota or calling AI.
- ``query:dup:reuse`` re-renders the stored card — free, no AI, no quota.
- ``query:dup:new`` runs the normal ask — quota consumed, AI called.

Behavior spec (locked, R7): retrieve is free; a fresh card consumes quota/AI.
"""

import asyncio
import datetime
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import bot
from services import db
from services.db import schema as db_schema


class WordQueryDuplicateFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1 WHERE user_id=1")
            conn.commit()
        self.card = {
            "word": "hello",
            "phonetic": "/həˈloʊ/",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام کردن.",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
        }

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _text_update(self, text="hello"):
        message = MagicMock()
        message.text = text
        message.reply_text = AsyncMock()
        chat = MagicMock()
        chat.id = 1
        chat.send_action = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.message = message
        update.effective_chat = chat
        return update

    def _cb_update(self, data, user_id=1):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        message = MagicMock()
        message.message_id = 10
        message.edit_reply_markup = AsyncMock()
        message.reply_text = AsyncMock()
        query.message = message
        chat = MagicMock()
        chat.id = 1
        chat.send_action = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.callback_query = query
        update.effective_message = message
        update.effective_chat = chat
        return update

    def _context(self, send_message=None):
        context = MagicMock()
        context.user_data = {"awaiting": "ask_word"}
        context.bot.send_message = send_message or AsyncMock()
        return context

    def _run_text(self, text, context, ai_return=None):
        patchers = [
            patch.object(bot, "is_owner", return_value=False),
            patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)),
            patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()),
        ]
        ai_mock = AsyncMock()
        if ai_return is not None:
            ai_mock = MagicMock(return_value=ai_return)
            patchers.append(patch.object(bot, "_call_ai_limited", new=ai_mock))
        else:
            patchers.append(patch.object(bot, "_call_ai_limited", new=ai_mock))
        prep = MagicMock(return_value=self.card) if ai_return is not None else AsyncMock()
        patchers.append(patch.object(bot, "_prepare_cached_card", new=prep))
        for p in patchers:
            p.start()
        try:
            asyncio.run(bot.text_router(self._text_update(text), context))
        finally:
            for p in reversed(patchers):
                p.stop()
        return ai_mock

    def _run_cb(self, data, context, user_id=1):
        update = self._cb_update(data, user_id=user_id)
        asyncio.run(bot.callback_router(update, context))
        return update

    def _force_expiry(self, token):
        past = (db._utc_now() - datetime.timedelta(days=1)).isoformat()
        conn = sqlite3.connect(db.DB_PATH)
        try:
            conn.execute(
                "UPDATE query_results SET expires_at=? WHERE token=?",
                (past, token),
            )
            conn.commit()
        finally:
            conn.close()

    def _words_asked(self):
        return db.get_user(1)["words_asked_today"]

    def _last_token(self):
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT token FROM query_results WHERE user_id=1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()["token"]

    def _markup_prefixes(self, context):
        prefixes = []
        for call in context.bot.send_message.call_args_list:
            markup = call.kwargs.get("reply_markup")
            if markup is not None and hasattr(markup, "inline_keyboard"):
                for row in markup.inline_keyboard:
                    for b in row:
                        prefixes.append(b.callback_data)
        return prefixes

    def _markup_labels(self, context):
        labels = []
        for call in context.bot.send_message.call_args_list:
            markup = call.kwargs.get("reply_markup")
            if markup is not None and hasattr(markup, "inline_keyboard"):
                for row in markup.inline_keyboard:
                    for b in row:
                        labels.append(b.text)
        return labels

    def test_retype_word_offers_two_button_choice_without_quota_or_ai(self):
        # First ask consumes quota + AI.
        ctx1 = self._context()
        ai1 = self._run_text("hello", ctx1, ai_return=self.card)
        ai1.assert_called()
        self.assertEqual(self._words_asked(), 1)
        token = self._last_token()

        # Re-ask the SAME word -> duplicate choice, no quota, no AI.
        ctx2 = self._context()
        ai2 = self._run_text("hello", ctx2)  # ai_return=None -> AI patched to no-op mock
        ai2.assert_not_called()
        self.assertEqual(self._words_asked(), 1, "duplicate offer must not consume quota")

        prefixes = self._markup_prefixes(ctx2)
        self.assertTrue(
            any(p.startswith("query:dup:new:") for p in prefixes),
            "choice must offer 'make a new card'",
        )
        self.assertTrue(
            any(p == f"query:dup:reuse:{token}" for p in prefixes),
            "choice must offer 'retrieve prior card' pointing at the prior card",
        )

    def test_retrieve_prior_card_is_free_and_rerenders(self):
        # First ask stores a card.
        ctx1 = self._context()
        self._run_text("hello", ctx1, ai_return=self.card)
        token = self._last_token()
        asked_before = self._words_asked()

        # Re-ask -> duplicate choice.
        ctx2 = self._context()
        self._run_text("hello", ctx2)
        choice_markup = next(
            call.kwargs.get("reply_markup")
            for call in ctx2.bot.send_message.call_args_list
            if call.kwargs.get("reply_markup") is not None
        )
        reuse_data = next(
            b.callback_data
            for row in choice_markup.inline_keyboard
            for b in row
            if b.callback_data.startswith("query:dup:reuse:")
        )

        # Reuse -> re-renders stored card, no quota, no AI.
        ctx3 = self._context()
        ai = AsyncMock()
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_call_ai_limited", new=ai), \
             patch.object(bot, "_prepare_cached_card", new=AsyncMock()):
            self._run_cb(reuse_data, ctx3)
        ai.assert_not_called()
        self.assertEqual(self._words_asked(), asked_before, "reuse must not consume quota")

        texts = [c.kwargs.get("text") for c in ctx3.bot.send_message.call_args_list]
        combined = "\n".join(t for t in texts if t)
        self.assertIn("سلام", combined, "stored card content re-rendered")
        self.assertIn("به منوی اصلی برگشتی", combined, "closing message shown")
        prefixes = self._markup_prefixes(ctx3)
        self.assertTrue(any(p.startswith("query:add:") for p in prefixes), "reuse card keeps add-to-review")

    def test_duplicate_new_runs_fresh_ask_with_quota_and_ai(self):
        ctx1 = self._context()
        self._run_text("hello", ctx1, ai_return=self.card)
        token = self._last_token()

        ctx2 = self._context()
        self._run_text("hello", ctx2)
        asked_before = self._words_asked()
        # Press "new card".
        update = self._cb_update(f"query:dup:new:{token}")
        ai = MagicMock(return_value=self.card)
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
             patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()), \
             patch.object(bot, "_call_ai_limited", new=ai), \
             patch.object(bot, "_prepare_cached_card", new=MagicMock(return_value=self.card)):
            asyncio.run(bot.callback_router(update, ctx2))
        ai.assert_called()
        self.assertEqual(self._words_asked(), asked_before + 1, "fresh ask consumes one quota")

    def test_reuse_rejects_another_users_token(self):
        """R7c — a prior card is scoped to its owner; another user cannot retrieve it."""
        self._run_text("hello", self._context(), ai_return=self.card)
        token = self._last_token()
        # Onboard a second learner.
        db.create_user_if_needed(2, "learner")
        db.set_user_lang_goal(2, "en", "general")
        db.set_user_level(2, "beginner")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1 WHERE user_id=2")
            conn.commit()
        ctx = self._context()
        self._run_cb(f"query:dup:reuse:{token}", ctx, user_id=2)
        self.assertEqual(ctx.bot.send_message.call_count, 0, "no card rendered for foreign token")
        self.assertEqual(self._words_asked(), 1, "foreign tap must not change quota")

    def test_reuse_guards_corrupt_json(self):
        """R7c — corrupt stored JSON is rejected without crashing or rendering."""
        self._run_text("hello", self._context(), ai_return=self.card)
        token = self._last_token()
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE query_results SET result_json='not-json' WHERE token=?",
                (token,),
            )
            conn.commit()
        ctx = self._context()
        self._run_cb(f"query:dup:reuse:{token}", ctx)
        self.assertEqual(ctx.bot.send_message.call_count, 0, "no card rendered for corrupt data")

    def test_reuse_guards_non_dict_json(self):
        """R7c — a non-dict result (e.g. legacy row) is rejected, not rendered."""
        self._run_text("hello", self._context(), ai_return=self.card)
        token = self._last_token()
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE query_results SET result_json='[1,2,3]' WHERE token=?",
                (token,),
            )
            conn.commit()
        ctx = self._context()
        self._run_cb(f"query:dup:reuse:{token}", ctx)
        self.assertEqual(ctx.bot.send_message.call_count, 0, "no card rendered for non-dict data")

    def test_reuse_handles_prior_card_expired_between_offer_and_tap(self):
        """R7c — an offer whose card expires before the tap shows an error, not a stale card."""
        self._run_text("hello", self._context(), ai_return=self.card)
        token = self._last_token()
        self._force_expiry(token)
        ctx = self._context()
        self._run_cb(f"query:dup:reuse:{token}", ctx)
        self.assertEqual(ctx.bot.send_message.call_count, 0, "expired card must not be rendered")

    def test_reuse_shows_remove_button_when_card_already_saved(self):
        """CRITICAL R7c — a retrieved already-saved card must show "remove", not "save".

        Otherwise the learner taps what looks like «ذخیره» and the toggle deletes
        their saved word + FSRS state.
        """
        self._run_text("hello", self._context(), ai_return=self.card)
        token = self._last_token()
        db.mark_query_result_saved(token, 1)
        self._run_text("hello", self._context())
        ctx = self._context()
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_call_ai_limited", new=AsyncMock()), \
             patch.object(bot, "_prepare_cached_card", new=AsyncMock()):
            self._run_cb(f"query:dup:reuse:{token}", ctx)
        labels = self._markup_labels(ctx)
        self.assertTrue(
            any("حذف از جعبه مرور" in l for l in labels),
            "reused saved card must render the remove button, got %r" % labels,
        )

    def test_duplicate_cancel_returns_to_main_menu(self):
        """R7b — the learner can decline both options and return to the menu."""
        self._run_text("hello", self._context(), ai_return=self.card)
        ctx = self._context()
        update = self._cb_update("query:dup:cancel")
        asyncio.run(bot.callback_router(update, ctx))
        texts = [c.kwargs.get("text") for c in ctx.bot.send_message.call_args_list]
        self.assertTrue(any("به منوی اصلی برگشتی" in t for t in texts if t), "main menu shown")
        self.assertFalse(ctx.user_data.get("awaiting"), "no lingering awaiting state")

    def test_choice_keyboard_cleared_after_reuse_tap(self):
        """R7b — after a choice is made, the offer's buttons are removed to stop repeat taps."""
        self._run_text("hello", self._context(), ai_return=self.card)
        token = self._last_token()
        self._run_text("hello", self._context())
        update = self._cb_update(f"query:dup:reuse:{token}")
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_call_ai_limited", new=AsyncMock()), \
             patch.object(bot, "_prepare_cached_card", new=AsyncMock()):
            asyncio.run(bot.callback_router(update, self._context()))
        update.callback_query.message.edit_reply_markup.assert_awaited_with(reply_markup=None)

    def test_duplicate_new_acks_callback(self):
        """R7b — the new-card path acknowledges the callback so the button stops loading."""
        self._run_text("hello", self._context(), ai_return=self.card)
        token = self._last_token()
        update = self._cb_update(f"query:dup:new:{token}")
        ctx = self._context()
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
             patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()), \
             patch.object(bot, "_call_ai_limited", new=MagicMock(return_value=self.card)), \
             patch.object(bot, "_prepare_cached_card", new=MagicMock(return_value=self.card)):
            asyncio.run(bot.callback_router(update, ctx))
        update.callback_query.answer.assert_awaited()
        self.assertFalse(ctx.user_data.get("awaiting"), "fresh ask leaves no lingering awaiting")


if __name__ == "__main__":
    unittest.main()