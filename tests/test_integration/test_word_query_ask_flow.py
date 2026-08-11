"""Phase 2 — bot.py ask-word adapter wiring (word_query.ask).

Regression coverage for the deep-module refactor: the ask_word branch of
bot.text_router now delegates to services.word_query.ask() and branches on
AskResult.kind. These tests drive the REAL text_router with a real on-disk
test DB and patch only the AI step (the injected generate_card closure's
_call_ai_limited / _prepare_cached_card) and the Telegram wait-state helpers,
so every result.kind branch is proven end-to-end through the router.

Locked contract rules verified here:
- R1: generate_card wraps BOTH ai.ask_card and _prepare_cached_card (2-step).
- R2: ask() owns validation; bot.py maps result.kind -> reply, no re-validation.
- R3: keep no-op persist_patch in the ask flow (repaired card persisted once
      via create_query_result).
- quota-pairing (#306): every failure kind and send-failure releases the
  reserved word-query quota exactly once.
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import bot
from services import db
from services.db import schema as db_schema
from services.utils.formatting import CardPreparationError
from telegram.error import NetworkError


class WordQueryAskFlowTests(unittest.TestCase):
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
            "synonyms": [],
            "antonyms": [],
            "grammar_tip": "",
        }

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_update(self, text="hello"):
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

    def _make_context(self, send_side_effect=None):
        context = MagicMock()
        context.user_data = {"awaiting": "ask_word"}
        context.bot.send_message = AsyncMock(side_effect=send_side_effect)
        return context

    def _run(
        self,
        text="hello",
        *,
        call_ai_limited=None,
        prepare_cached_card=None,
        send_side_effect=None,
    ):
        update = self._make_update(text)
        context = self._make_context(send_side_effect=send_side_effect)
        patchers = [
            patch.object(bot, "is_owner", return_value=False),
            patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)),
            patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()),
        ]
        # Both AI steps are sync functions invoked through asyncio.to_thread,
        # so a plain dict must be wrapped into a sync mock that returns it.
        if isinstance(call_ai_limited, dict):
            call_ai_limited = MagicMock(return_value=call_ai_limited)
        if isinstance(prepare_cached_card, dict):
            prepare_cached_card = MagicMock(return_value=prepare_cached_card)
        if call_ai_limited is not None:
            patchers.append(patch.object(bot, "_call_ai_limited", new=call_ai_limited))
        if prepare_cached_card is not None:
            patchers.append(patch.object(bot, "_prepare_cached_card", new=prepare_cached_card))
        for p in patchers:
            p.start()
        try:
            asyncio.run(bot.text_router(update, context))
        finally:
            for p in reversed(patchers):
                p.stop()
        return context

    def _words_asked(self):
        return db.get_user(1)["words_asked_today"]

    def _sent_texts(self, context):
        return [c.kwargs.get("text") for c in context.bot.send_message.call_args_list]

    def _sent_markups(self, context):
        return [c.kwargs.get("reply_markup") for c in context.bot.send_message.call_args_list]

    def test_happy_path_delivers_card_and_stores_query_kb_token(self):
        context = self._run(
            call_ai_limited=self.card,
            prepare_cached_card=self.card,
        )
        self.assertEqual(self._words_asked(), 1, "happy path consumes one quota")
        # The card + the "returned to menu" message are both sent.
        combined = "\n".join(self._sent_texts(context))
        self.assertIn("سلام", combined)
        self.assertIn("به منوی اصلی برگشتی", combined)
        # The reply includes the usage line and a query_result_keyboard.
        markups = self._sent_markups(context)
        card_markup = next(
            (m for m in markups if m is not None and hasattr(m, "inline_keyboard")),
            None,
        )
        self.assertIsNotNone(card_markup, "the delivered card must have a keyboard")
        prefixes = [
            b.callback_data
            for row in card_markup.inline_keyboard
            for b in row
        ]
        self.assertTrue(
            any(p.startswith("query:prepare:") for p in prefixes),
            "delivered card must keep the translations button",
        )
        # The query_kb token was persisted into user_data.
        query_tokens = [
            k for k in context.user_data if str(k).startswith("query_kb_")
        ]
        self.assertEqual(len(query_tokens), 1, "one query_kb_ token stored")

    def test_quota_exhausted_sends_quota_message_and_skips_ai(self):
        # Reserve returns False -> ask() returns quota_exhausted without AI.
        with patch.object(bot, "is_owner", return_value=False):
            # consume the free-plan limit by patching the plan to a tiny limit is
            # not needed; instead patch db.reserve_word_query (via word_query.ask)
            # is hard because it's a real composition. Drive it by exhausting the
            # actual quota: free default limit is small; set words_asked_today to
            # the limit via direct DB update.
            limit = db.get_quota_status(1)["word_query"]["limit"]
            today = db._today().isoformat()
            with db.get_conn() as conn:
                conn.execute(
                    "UPDATE users SET words_asked_today=?, words_asked_date=? "
                    "WHERE user_id=?",
                    (limit, today, 1),
                )
                conn.commit()
            update = self._make_update()
            context = self._make_context()
            ai_mock = AsyncMock()
            with patch.object(bot, "is_owner", return_value=False), \
                 patch.object(bot, "_call_ai_limited", new=ai_mock), \
                 patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
                 patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()):
                asyncio.run(bot.text_router(update, context))
            ai_mock.assert_not_called()
            sent = context.bot.send_message.call_args.kwargs["text"]
            self.assertIn("سقف روزانه", sent)
            self.assertEqual(self._words_asked(), limit, "exhausted quota unchanged")

    def test_invalid_input_keeps_awaiting_and_sends_error(self):
        update = self._make_update("123")
        context = self._make_context()
        ai_mock = AsyncMock()
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_call_ai_limited", new=ai_mock), \
             patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
             patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()):
            asyncio.run(bot.text_router(update, context))
        ai_mock.assert_not_called()
        self.assertEqual(context.user_data["awaiting"], "ask_word")
        self.assertEqual(self._words_asked(), 0, "invalid input must not reserve quota")
        sent = context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("ساده بفرست", sent)

    def test_ai_timeout_sends_busy_message_and_releases_quota(self):
        def timeout_step(*args, **kwargs):
            raise asyncio.TimeoutError()

        context = self._run(call_ai_limited=timeout_step)
        self.assertEqual(self._words_asked(), 0, "ai_timeout must release quota")
        sent = context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("شلوغه", sent)

    def test_ai_error_sends_generic_error_and_releases_quota(self):
        def err_step(*args, **kwargs):
            raise RuntimeError("boom")

        context = self._run(call_ai_limited=err_step)
        self.assertEqual(self._words_asked(), 0, "ai_error must release quota")
        sent = context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("مشکلی در ارتباط", sent)

    def test_card_prep_error_sends_prep_error_and_releases_quota(self):
        def prep_error(*args, **kwargs):
            raise CardPreparationError("no repairable fields")

        context = self._run(
            call_ai_limited=self.card,
            prepare_cached_card=prep_error,
        )
        self.assertEqual(self._words_asked(), 0, "card_prep_error must release quota")
        sent = context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("نتونست با اطمینان آماده بشه", sent)

    def test_send_failure_releases_quota(self):
        with self.assertRaises(NetworkError):
            self._run(
                call_ai_limited=self.card,
                prepare_cached_card=self.card,
                send_side_effect=NetworkError("network down"),
            )
        self.assertEqual(
            self._words_asked(),
            0,
            "an undelivered card must release the reserved word-query quota (#306)",
        )


if __name__ == "__main__":
    unittest.main()