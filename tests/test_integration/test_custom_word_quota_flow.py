"""Rule A — quota is released whenever a card is NOT delivered (custom-word query).

Regression coverage for #306: the ask_word branch reserves a word-query quota
atomically, but a Telegram network failure during the final card delivery used to
propagate without releasing the reservation, so the learner "paid" for a card
they never received.
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import bot
from services import db
from services.db import schema as db_schema
from telegram.error import NetworkError
from handlers.srs_handler import _handle_query_add


class CustomWordQuotaReleaseFlowTests(unittest.TestCase):
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

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_update(self):
        message = MagicMock()
        message.text = "hello"
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

    def _card(self):
        return {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام کردن.",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
        }

    def test_undelivered_card_releases_word_query_quota(self):
        update = self._make_update()
        context = self._make_context(send_side_effect=NetworkError("network down"))

        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_call_ai_limited", return_value=self._card()), \
             patch.object(bot, "_prepare_cached_card", return_value=self._card()), \
             patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
             patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()):
            with self.assertRaises(NetworkError):
                asyncio.run(bot.text_router(update, context))

        self.assertEqual(
            db.get_user(1)["words_asked_today"],
            0,
            "an undelivered card must release the reserved word-query quota",
        )


class GrammarTipQuotaReleaseFlowTests(unittest.TestCase):
    """Rule A mirror: an undelivered grammar tip must release its reservation."""

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

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_undelivered_grammar_tip_releases_quota(self):
        from handlers import user as user_handlers

        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        context = MagicMock()
        context.user_data = {}
        context.bot.send_message = AsyncMock(side_effect=NetworkError("network down"))

        tip = {"title": "نکته", "explanation": "توضیح", "example": "مثال"}
        with patch.object(user_handlers, "is_owner", return_value=False), \
             patch.object(user_handlers, "_call_ai_limited", return_value=tip), \
             patch.object(user_handlers, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
             patch.object(user_handlers, "_finish_llm_wait_state", new=AsyncMock()):
            # The tip-send NetworkError is caught by the outer except, which then
            # re-sends a generic error message; that re-send also fails, so the
            # NetworkError observed here originates from the generic-error path.
            # The meaningful assertion is the released grammar-tip quota below.
            with self.assertRaises(NetworkError):
                asyncio.run(user_handlers.send_grammar_tip(update, context))

        self.assertEqual(
            db.get_user(1)["grammar_tips_asked_today"],
            0,
            "an undelivered grammar tip must release the reserved quota",
        )


class CustomWordValidationFlowTests(unittest.TestCase):
    """Rule B: invalid input is rejected before quota reserve and AI.

    A query containing digits (e.g. Persian "قرن ۲۱" or Latin "hello123") must be
    rejected by the validate_word_query seam before reserve_word_query runs and
    before any AI call, so the learner is neither charged nor billed.
    """

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

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_update(self, text):
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

    def _run_invalid(self, text):
        update = self._make_update(text)
        context = MagicMock()
        context.user_data = {"awaiting": "ask_word"}
        context.bot.send_message = AsyncMock()
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_call_ai_limited", new=AsyncMock()) as ai_mock:
            asyncio.run(bot.text_router(update, context))
        return context, ai_mock

    def test_digit_query_is_rejected_before_reserve_and_ai(self):
        for bad in ("قرن ۲۱", "hello123", "ساعت ۱۲"):
            with self.subTest(bad=bad):
                context, ai_mock = self._run_invalid(bad)
                self.assertEqual(
                    db.get_user(1)["words_asked_today"],
                    0,
                    f"invalid query {bad!r} must not reserve word-query quota",
                )
                ai_mock.assert_not_called()
                sent = context.bot.send_message.call_args.kwargs["text"]
                self.assertIn("لطفاً فقط واژه یا عبارت ساده بفرست", sent)

    def test_punctuation_only_query_is_rejected_before_reserve_and_ai(self):
        # Owner decision 2026-08-11: punctuation-only input (no real word) must
        # not reserve quota or trigger an AI call.
        context, ai_mock = self._run_invalid("---")
        self.assertEqual(db.get_user(1)["words_asked_today"], 0)
        ai_mock.assert_not_called()
        sent = context.bot.send_message.call_args.kwargs["text"]
        self.assertIn("یک واژه یا عبارت واقعی بفرست", sent)

    def test_valid_digit_free_query_still_reaches_ai(self):
        context = MagicMock()
        update = self._make_update("hello")
        context.user_data = {"awaiting": "ask_word"}
        context.bot.send_message = AsyncMock()
        card = {"word": "hello", "fa_meaning": "سلام", "fa_explanation": "برای سلام", "examples": []}
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_call_ai_limited", return_value=card) as ai_mock, \
             patch.object(bot, "_prepare_cached_card", return_value=card), \
             patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
             patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()):
            asyncio.run(bot.text_router(update, context))
        ai_mock.assert_called()
        self.assertEqual(db.get_user(1)["words_asked_today"], 1)


class QueryAddToggleFlowTests(unittest.TestCase):
    """Rule D+E: the manual save button is an idempotent toggle with toasts.

    Tapping saves the word and flips the button to "remove"; tapping again
    removes it and flips the button back. The callback prefix stays
    ``query:add:{token}``; only the semantics become a toggle.
    """

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
        self.result_data = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام کردن.",
            "examples": ["Hello!"],
        }
        self.token = db.create_query_result(1, "hello", "hello", "en", self.result_data)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_update(self):
        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query.answer = AsyncMock()
        update.effective_message.edit_reply_markup = AsyncMock()
        return update

    def _word_count(self):
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM saved_words WHERE user_id=1 AND word='hello'"
            ).fetchone()["c"]

    def test_toggle_saves_then_removes_with_toast_and_label_flip(self):
        update = self._make_update()
        context = MagicMock()
        # Render-time flags are stored in user_data; the toggle must preserve the
        # pronounce button when it edits the card (pronounce always present, R1).
        context.user_data = {
            f"query_kb_{self.token}": {},
        }

        asyncio.run(_handle_query_add(update, context, self.token))
        self.assertEqual(self._word_count(), 1, "first tap saves the word")
        self.assertEqual(
            update.callback_query.answer.call_args[0][0],
            "در جعبه مرور ذخیره شد!",
        )
        saved_markup = update.effective_message.edit_reply_markup.call_args.kwargs["reply_markup"]
        saved_calls = [b.callback_data for r in saved_markup.inline_keyboard for b in r]
        self.assertIn("حذف از جعبه مرور", saved_markup.inline_keyboard[0][0].text)
        self.assertIsNotNone(
            db.get_query_result(self.token, user_id=1)["saved_at"],
            "save sets the saved marker",
        )
        self.assertFalse(
            any(c.startswith("query:prepare:") for c in saved_calls),
            "toggle edit must not emit the removed translations button",
        )
        self.assertTrue(
            any(c.startswith("tts:pronounce:q:") for c in saved_calls),
            "toggle edit must preserve the pronounce button",
        )

        # Second tap removes.
        update = self._make_update()
        asyncio.run(_handle_query_add(update, context, self.token))
        self.assertEqual(self._word_count(), 0, "second tap removes the word")
        self.assertEqual(
            update.callback_query.answer.call_args[0][0],
            "از جعبه مرور حذف شد!",
        )
        removed_markup = update.effective_message.edit_reply_markup.call_args.kwargs["reply_markup"]
        self.assertIn("ذخیره در جعبه مرور", removed_markup.inline_keyboard[0][0].text)
        self.assertIsNone(
            db.get_query_result(self.token, user_id=1)["saved_at"],
            "removal clears the saved marker",
        )

        # Third tap saves again (idempotent round-trip).
        update = self._make_update()
        asyncio.run(_handle_query_add(update, context, self.token))
        self.assertEqual(self._word_count(), 1)


class ShowStatusQuotaRenderTests(unittest.TestCase):
    """Rule C — the settings panel (show_status) renders remaining quota."""

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

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_show_status_renders_remaining_word_and_grammar_quota(self):
        from handlers.user import show_status
        from config import _app_today
        limit = db.get_quota_status(1)["word_query"]["limit"]
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE users SET words_asked_today=1, grammar_tips_asked_today=2, "
                "words_asked_date=?, grammar_tips_asked_date=? WHERE user_id=1",
                (_app_today(), _app_today()),
            )
            conn.commit()

        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        context = MagicMock()

        captured = {}
        with patch("handlers.user._edit_or_send", new=AsyncMock()) as edit_mock:
            edit_mock.side_effect = lambda u, c, text, **kw: captured.update(text=text)
            asyncio.run(show_status(update, context))

        self.assertIn("پرسش واژه", captured["text"])
        self.assertIn(f"1/{limit} (باقی‌مانده {max(limit - 1, 0)})", captured["text"])
        self.assertIn("نکته گرامری", captured["text"])
        self.assertIn(f"2/{limit} (باقی‌مانده {max(limit - 2, 0)})", captured["text"])


if __name__ == "__main__":
    unittest.main()
