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
from services.utils.formatting import ASK_WORD_PROMPT, CardPreparationError
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

    def test_happy_path_delivers_card_with_add_and_pronounce_buttons(self):
        context = self._run(
            call_ai_limited=self.card,
            prepare_cached_card=self.card,
        )
        self.assertEqual(self._words_asked(), 1, "happy path consumes one quota")
        # The card + the "returned to menu" message are both sent.
        combined = "\n".join(self._sent_texts(context))
        self.assertIn("سلام", combined)
        self.assertIn("به منوی اصلی برگشتی", combined)
        # The card carries a query_result_keyboard; usage lives in the closing message.
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
            any(p.startswith("query:add:") for p in prefixes),
            "delivered card must keep the add-to-review button",
        )
        self.assertTrue(
            any(p.startswith("tts:pronounce:q:") for p in prefixes),
            "delivered card must always include the 🔊 pronounce button (#390)",
        )
        self.assertFalse(
            any(p.startswith("query:prepare:") for p in prefixes),
            "delivered card must not emit the removed translations button (R2/R3)",
        )
        # The per-token query_kb_ render state was removed with show_pronounce (#390).
        query_tokens = [
            k for k in context.user_data if str(k).startswith("query_kb_")
        ]
        self.assertEqual(len(query_tokens), 0, "no stale query_kb_ render state stored")

    def test_card_renders_translation_spoilers_and_closing_has_usage(self):
        """R1+R6 — translations show ON by default as spoilers; usage moves to closing."""
        context = self._run(
            call_ai_limited=self.card,
            prepare_cached_card=self.card,
        )
        texts = self._sent_texts(context)
        markups = self._sent_markups(context)
        # The card is the message carrying the query_result_keyboard (query:add:);
        # the closing message carries the main-menu markup and the return-to-menu line.
        card_text = None
        closing_text = None
        for text, markup in zip(texts, markups):
            if markup is None or not hasattr(markup, "inline_keyboard"):
                continue
            has_add = any(
                b.callback_data.startswith("query:add:")
                for row in markup.inline_keyboard
                for b in row
            )
            if has_add:
                card_text = text
        closing_text = next(
            (t for t in texts if "به منوی اصلی برگشتی" in t), None
        )
        self.assertIsNotNone(card_text, "card message not found")
        self.assertIsNotNone(closing_text, "closing message not found")
        # R1: translations render as MarkdownV2 spoilers with the prepared label.
        self.assertIn("مثال\u200cها \\+ ترجمه", card_text, "R1: label reflects translations-prepared")
        self.assertIn("||سلام\\!||", card_text, "R1: example translation renders as a spoiler")
        # R6: usage line is NOT in the card footer, but IS in the closing message.
        self.assertNotIn("استفاده امروز", card_text, "R6: usage must not be in the card footer")
        self.assertIn("استفاده امروز", closing_text, "R6: usage must be in the closing message")
        self.assertIn("به منوی اصلی برگشتی", closing_text, "R6: closing keeps the return-to-menu line")

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

    def test_registration_required_blocks_unregistered_and_sends_start(self):
        # Incomplete profile: drop target_lang so the single pipeline gate fires.
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET target_lang=NULL WHERE user_id=1")
            conn.commit()
        ai_mock = AsyncMock()
        update = self._make_update("apple")
        context = self._make_context()
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_call_ai_limited", new=ai_mock), \
             patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
             patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()):
            asyncio.run(bot.text_router(update, context))
        ai_mock.assert_not_called()
        self.assertEqual(self._words_asked(), 0, "registration gate must not reserve quota")
        self.assertIsNone(
            context.user_data.get("awaiting"), "awaiting cleared on registration gate"
        )
        sent = context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("ثبت‌نام", sent, "must point the learner to /start")

    def test_persist_error_releases_quota_and_sends_retry(self):
        # AI returns a card with no usable "word" -> ask refuses to persist it.
        card_no_word = {"fa_meaning": "بی‌محتوا"}
        context = self._run(
            call_ai_limited=card_no_word,
            prepare_cached_card=card_no_word,
        )
        self.assertEqual(self._words_asked(), 0, "persist_error must release quota")
        sent = context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("ذخیره", sent, "must explain the result was not stored")


    def test_ask_word_entry_prompt_uses_card_framing(self):
        """Issue #357: entry prompt must frame the feature as building a card."""
        import handlers.user as user_handlers

        update = self._make_update("anything")
        context = self._make_context()
        asyncio.run(user_handlers.ask_for_ask_word(update, context))
        self.assertTrue(
            context.bot.send_message.called, "ask_for_ask_word must send a prompt"
        )
        prompt = context.bot.send_message.call_args.kwargs["text"]
        # Bind the test to the constant so a per-file drift is caught here too.
        self.assertIn(ASK_WORD_PROMPT, prompt, "entry prompt must use the shared constant")
        self.assertNotIn(
            "معنی/توضیح بدم", prompt, "must not frame as 'give the meaning/explanation'"
        )

    def test_invalid_input_reprompt_uses_card_framing(self):
        """Issue #357: the invalid-input re-prompt (bot.py) must use new wording."""
        # "!!!" is punctuation-only -> validate_word_query returns ERR_INVALID_CHARS.
        ai_mock = MagicMock(side_effect=AssertionError("AI must not run for invalid input"))
        context = self._run(text="!!!", call_ai_limited=ai_mock)
        sent = "\n".join(self._sent_texts(context))
        ai_mock.assert_not_called()
        # Bind the test to the constant so the bot.py copy cannot drift silently.
        self.assertIn(ASK_WORD_PROMPT, sent, "re-prompt must use the shared constant")
        self.assertNotIn(
            "معنی/توضیح بدم", sent, "re-prompt must not use the old definition framing"
        )


if __name__ == "__main__":
    unittest.main()