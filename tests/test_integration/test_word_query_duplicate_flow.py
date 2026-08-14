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
import os
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

    def _cb_update(self, data):
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
        update.effective_user.id = 1
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

    def _run_cb(self, data, context):
        update = self._cb_update(data)
        asyncio.run(bot.callback_router(update, context))
        return update

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


if __name__ == "__main__":
    unittest.main()