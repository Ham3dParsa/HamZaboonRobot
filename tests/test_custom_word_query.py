import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import bot
from services import db
from services.db import schema as db_schema
from services.utils.formatting import escape_mdv2_code, format_card
from services.utils.helpers import _is_cancel_input
from bot import (
    _user_presentation,
)
from services.utils.validation import (
    ERR_EMPTY,
    ERR_INVALID_CHARS,
    ERR_TOO_FEW_LETTERS,
    ERR_TOO_LONG,
    ERR_TOO_MANY_WORDS,
    validate_word_query,
)
from config.keyboards import (
    BTN_ASK_WORD,
    BTN_SETTINGS,
    awaiting_inline_keyboard,
    get_review_keyboard,
    main_menu,
    presentation_settings_keyboard,
    query_result_keyboard,
)


class CustomWordQueryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_query_result_lifecycle_is_persistent_and_idempotent(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")

        token = db.create_query_result(
            1,
            "  hello   world  ",
            "hello",
            "en",
            {"word": "hello", "examples": []},
        )

        row = db.get_query_result(token, user_id=1)
        self.assertIsNotNone(row)
        self.assertEqual(row["query_text"], "hello world")
        self.assertEqual(row["word"], "hello")
        self.assertEqual(json.loads(row["result_json"]), {"word": "hello", "examples": []})
        self.assertIsNone(row["saved_at"])

        self.assertTrue(db.add_saved_word(1, row["word"], row["lang"]))
        db.mark_query_result_saved(token)

        row = db.get_query_result(token, user_id=1)
        self.assertIsNotNone(row["saved_at"])
        self.assertFalse(db.add_saved_word(1, row["word"], row["lang"]))

    def test_query_result_keyboard_uses_short_callback_data(self):
        markup = query_result_keyboard("0123456789abcdef0123456789abcdef")
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.callback_data, "query:add:0123456789abcdef0123456789abcdef")
        self.assertLess(len(button.callback_data), 64)

    def test_query_result_keyboard_can_include_language_label(self):
        markup = query_result_keyboard("0123456789abcdef0123456789abcdef", "en")
        button = markup.inline_keyboard[0][0]
        self.assertIn("انگلیسی", button.text)
        self.assertEqual(button.callback_data, "query:add:0123456789abcdef0123456789abcdef")

    def test_srs_review_keyboard_is_user_scoped_and_short(self):
        markup = get_review_keyboard(123, 456)
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertEqual(callbacks, ["srs:1:123:456", "srs:2:123:456", "srs:3:123:456", "srs:4:123:456"])
        self.assertTrue(all(len(callback) < 64 for callback in callbacks))

    def test_translation_prepare_controls_are_scoped(self):
        query = query_result_keyboard("a" * 32, show_translations=True)
        self.assertEqual(
            query.inline_keyboard[0][1].callback_data,
            f"query:prepare:{'a' * 32}",
        )
        srs = get_review_keyboard(123, 456)
        self.assertEqual(
            srs.inline_keyboard[0][0].callback_data,
            "srs:1:123:456",
        )

    def test_main_menu_no_longer_shows_manual_save_action(self):
        markup = main_menu(False)
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertNotIn("➕ ثبت واژه‌ی دلخواه", labels)
        self.assertIn(BTN_ASK_WORD, labels)
        self.assertNotIn("📝 تنظیم نمایش کارت", labels)
        self.assertIn(BTN_SETTINGS, labels)

    def test_presentation_settings_keyboard_marks_current_mode(self):
        markup = presentation_settings_keyboard("brief")
        self.assertEqual(
            [button.callback_data for button in markup.inline_keyboard[0]],
            ["presentation:set:brief", "presentation:set:detailed"],
        )
        self.assertTrue(markup.inline_keyboard[0][0].text.startswith("✅ "))

    def test_premium_presentation_preference_is_persisted(self):
        db.create_user_if_needed(1, "learner")
        self.assertIsNone(db.get_user(1)["presentation_preference"])
        db.set_plan(1, "silver")
        db.set_presentation_preference(1, "brief")
        self.assertEqual(db.get_user(1)["presentation_preference"], "brief")
        with self.assertRaises(ValueError):
            db.set_presentation_preference(1, "compact")

    def test_user_presentation_falls_back_after_downgrade(self):
        db.create_user_if_needed(1, "learner")
        premium_row = db.get_user(1)
        self.assertEqual(_user_presentation(premium_row), "detailed")
        db.set_plan(1, "silver")
        db.set_presentation_preference(1, "brief")
        self.assertEqual(_user_presentation(db.get_user(1)), "brief")
        db.set_plan(1, "free")
        self.assertEqual(_user_presentation(db.get_user(1)), "detailed")

    def test_saved_words_enter_first_exposure_queue(self):
        db.create_user_if_needed(1, "learner")
        self.assertTrue(db.add_saved_word(1, "query-word", "en"))
        rows = db.get_pre_first_exposure_words(1)
        self.assertEqual([row["word"] for row in rows], ["query-word"])

    def test_toggle_review_word_adds_then_removes_idempotently(self):
        db.create_user_if_needed(1, "learner")
        result_data = {"word": "hello", "fa_meaning": "سلام", "examples": []}
        # Add direction.
        self.assertEqual(db.toggle_review_word(1, "hello", "en", result_data), "saved")
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_words WHERE user_id=1 AND normalized_word='hello'"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_source"], "manual")
        # Idempotent: toggling again while present removes it.
        self.assertEqual(db.toggle_review_word(1, "  Hello  ", "en", result_data), "removed")
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_words WHERE user_id=1 AND normalized_word='hello'"
            ).fetchall()
        self.assertEqual(len(rows), 0)
        # Add again after removal.
        self.assertEqual(db.toggle_review_word(1, "hello", "en", result_data), "saved")
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_words WHERE user_id=1 AND normalized_word='hello'"
            ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_custom_word_validation_rejects_long_or_unrelated_input(self):
        self.assertIsNone(validate_word_query("thick burger", "en"))
        # "همبرگر آفرقایی کلفت" is now considered valid input
        self.assertIsNone(validate_word_query("one two three four", "en"))  # 4 words, Latin target, no Persian
        self.assertEqual(validate_word_query("", "en"), ERR_EMPTY)
        self.assertEqual(validate_word_query("   ", "en"), ERR_EMPTY)

    def test_validate_word_query_rejects_digits_and_non_letters(self):
        # ses_01b176ac re-lock: digits are rejected even inside an otherwise
        # valid phrase (e.g. "قرن ۲۱").
        self.assertEqual(validate_word_query("قرن ۲۱", "en"), ERR_INVALID_CHARS)
        self.assertEqual(validate_word_query("hello123", "en"), ERR_INVALID_CHARS)
        self.assertEqual(validate_word_query("qwrty", "en"), None)  # no vowel heuristic
        self.assertEqual(validate_word_query("Rhythmus", "en"), None)

    def test_validate_word_query_requires_at_least_two_letters(self):
        # Owner decision 2026-08-11: punctuation-only (or single-letter) queries
        # are invalid so they cannot burn daily quota or an AI call.
        self.assertEqual(validate_word_query("-", "en"), ERR_TOO_FEW_LETTERS)
        self.assertEqual(validate_word_query("---", "en"), ERR_TOO_FEW_LETTERS)
        self.assertEqual(validate_word_query("'", "en"), ERR_TOO_FEW_LETTERS)
        self.assertEqual(validate_word_query("a", "en"), ERR_TOO_FEW_LETTERS)
        self.assertEqual(validate_word_query("ab", "en"), None)
        self.assertEqual(validate_word_query("aa", "en"), None)

    def test_validate_word_query_is_unicode_aware(self):
        self.assertIsNone(validate_word_query("همبرگر", "fa"))
        self.assertIsNone(validate_word_query("برگر کلفت", "en"))
        # Persian digits and Latin digits are both non-letters -> rejected.
        self.assertEqual(validate_word_query("ساعت 12", "fa"), ERR_INVALID_CHARS)
        self.assertEqual(validate_word_query("ساعت ۱۲", "fa"), ERR_INVALID_CHARS)

    def test_validate_word_query_allows_punctuation_and_zwnj(self):
        self.assertIsNone(validate_word_query("don't", "en"))
        self.assertIsNone(validate_word_query("میخواهم", "fa"))
        # Hyphen, ZWNJ, apostrophe, and right single quote are the allowed set.
        self.assertIsNone(validate_word_query("self-contained", "en"))
        self.assertIsNone(validate_word_query("خودکار", "fa"))

    def test_validate_word_query_enforces_length_and_word_caps(self):
        self.assertEqual(validate_word_query("a" * 49, "en"), ERR_TOO_LONG)
        self.assertIsNone(validate_word_query("a" * 48, "en"))
        self.assertEqual(
            validate_word_query("one two three four five", "en"),
            ERR_TOO_MANY_WORDS,
        )

    def test_validate_word_query_language_does_not_change_acceptance(self):
        # Rule B: language is retained for message tailoring only.
        self.assertEqual(validate_word_query("قرن ۲۱", "fa"), ERR_INVALID_CHARS)
        self.assertEqual(validate_word_query("قرن ۲۱", "en"), ERR_INVALID_CHARS)
        self.assertIsNone(validate_word_query("Rhythmus", "de"))

    def test_cancel_back_inline_keyboard_is_shared(self):
        markup = awaiting_inline_keyboard()
        labels = [button.text for row in markup.inline_keyboard for button in row]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn("↩️ بازگشت", labels)
        self.assertIn("❌ لغو", labels)
        self.assertIn("flow:back", callbacks)
        self.assertIn("flow:cancel", callbacks)
        self.assertTrue(_is_cancel_input("لغو"))
        self.assertTrue(_is_cancel_input("بازگشت"))

    def test_markdown_code_escaping_does_not_escape_phonetic_punctuation(self):
        self.assertEqual(escape_mdv2_code("hɛ.loʊ"), "hɛ.loʊ")
        card = format_card(
            {
                "word": "hello",
                "fa_meaning": "سلام",
            },
            phonetic_lines=["`hɛ.loʊ`"],
        )
        self.assertIn("`hɛ.loʊ`", card)

    def test_phonetic_rendering(self):
        card = {
            "word": "kompliziert",
            "fa_meaning": "پیچیده",
            "fa_explanation": "به چیزی گفته می‌شود که درک کردن یا انجام دادن آن آسان نیست.",
        }
        phon_lines = ["`IPA: /kɔm.pliˈtsiːʁt/`"]
        rendered = format_card(card, phonetic_lines=phon_lines)
        self.assertIn("`IPA: /kɔm.pliˈtsiːʁt/`", rendered)
        self.assertNotIn("Latin:", rendered)

    def test_brief_and_detailed_render_the_same_card_at_different_detail_levels(self):
        card = {
            "word": "hello",
            "phonetic": "hɛ.loʊ",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام کردن استفاده می‌شود.",
            "synonyms": ["hi", "greetings"],
            "antonyms": [],
            "examples": ["Example one.", "Example two.", "Extra example."],
            "example_translations": ["مثال اول.", "مثال دوم.", "مثال اضافه."],
            "grammar_tip": "یک نکته.",
        }

        detailed = format_card(card, presentation="detailed")
        brief = format_card(card, presentation="brief")

        self.assertIn("Example one", detailed)
        self.assertIn("Example two", detailed)
        self.assertNotIn("Extra example", detailed)
        self.assertIn("greetings", detailed)
        self.assertIn("یک نکته", detailed)
        self.assertIn("hello", brief)
        self.assertIn("سلام", brief)
        self.assertIn("برای سلام کردن", brief)
        self.assertNotIn("Example one", brief)
        self.assertNotIn("greetings", brief)
        self.assertNotIn("یک نکته", brief)

    def test_rendering_does_not_mutate_cached_payload(self):
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام کردن استفاده می‌شود.",
            "examples": ["Example one.", "Example two."],
            "example_translations": ["مثال اول.", "مثال دوم."],
        }
        snapshot = json.loads(json.dumps(card, ensure_ascii=False))
        format_card(card, presentation="brief")
        format_card(card, presentation="detailed")
        self.assertEqual(card, snapshot)

    def test_translation_spoilers_pair_examples_without_leaking_translations(self):
        text = format_card(
            {
                "word": "hello",
                "fa_meaning": "سلام",
                "fa_explanation": "توضیح",
                "examples": ["Hello!.", "Hi!."],
                "example_translations": ["سلام اول.", "سلام دوم."],
            },
            translations_prepared=True,
        )
        lines = [line for line in text.splitlines() if line]
        self.assertIn("📝 *مثال‌ها \\+ ترجمه:*", lines)
        self.assertIn("✦ Hello\\!\\.", lines)
        self.assertIn("✦ Hi\\!\\.", lines)
        self.assertIn("||سلام اول\\.||", lines)
        self.assertIn("||سلام دوم\\.||", lines)
        self.assertNotIn("> ", text)
        self.assertNotIn("— ||", text)
        self.assertNotIn("Hello!. —", text)

    def test_format_card_rejects_unknown_presentation(self):
        with self.assertRaises(ValueError):
            format_card({"word": "hello"}, presentation="compact")


class AskWordKeyboardRestoreTests(unittest.TestCase):
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
        return update, message

    def _make_context(self):
        context = MagicMock()
        context.user_data = {"awaiting": "ask_word"}
        context.bot.send_message = AsyncMock(return_value=MagicMock())
        return context

    def test_ask_word_completion_restores_main_menu_keyboard(self):
        update, message = self._make_update()
        context = self._make_context()
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام کردن.",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
        }
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "_call_ai_limited", return_value=card), \
             patch.object(bot, "_prepare_cached_card", return_value=card), \
             patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
             patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()):
            asyncio.run(bot.text_router(update, context))

        reply_markups = [
            call.kwargs.get("reply_markup")
            for call in context.bot.send_message.call_args_list
            if call.kwargs.get("reply_markup") is not None
        ]
        self.assertTrue(reply_markups, "expected at least one reply with a keyboard")
        from telegram import ReplyKeyboardMarkup

        restored = [m for m in reply_markups if isinstance(m, ReplyKeyboardMarkup)]
        self.assertTrue(
            restored,
            "ask_word completion must restore the main-menu ReplyKeyboardMarkup",
        )
        labels = [
            button.text
            for markup in restored
            for row in markup.keyboard
            for button in row
        ]
        self.assertIn(BTN_ASK_WORD, labels)

    def test_ask_word_limit_exhausted_restores_main_menu_keyboard(self):
        update, message = self._make_update()
        context = self._make_context()
        with patch.object(bot, "is_owner", return_value=False), \
             patch.object(db, "reserve_word_query", return_value=False):
            asyncio.run(bot.text_router(update, context))

        from telegram import ReplyKeyboardMarkup

        restored = [
            call.kwargs.get("reply_markup")
            for call in context.bot.send_message.call_args_list
            if isinstance(call.kwargs.get("reply_markup"), ReplyKeyboardMarkup)
        ]
        self.assertTrue(
            restored,
            "quota-exhausted exit must restore the main-menu ReplyKeyboardMarkup",
        )


if __name__ == "__main__":
    unittest.main()
