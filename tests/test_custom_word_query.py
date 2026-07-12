import json
import os
import tempfile
import unittest

import db
from bot import _custom_word_input_error, _is_cancel_input
from keyboards import (
    BTN_ASK_WORD,
    awaiting_inline_keyboard,
    daily_card_keyboard,
    daily_review_dates_keyboard,
    daily_review_menu_keyboard,
    main_menu,
    query_result_keyboard,
)


class CustomWordQueryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
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

    def test_main_menu_no_longer_shows_manual_save_action(self):
        markup = main_menu(False)
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertNotIn("➕ ثبت واژه‌ی دلخواه", labels)
        self.assertIn(BTN_ASK_WORD, labels)

    def test_recent_daily_card_dates_are_sorted_descending(self):
        db.create_user_if_needed(1, "learner")
        db.add_daily_card(1, "2026-07-10", 0, {"word": "a"})
        db.add_daily_card(1, "2026-07-12", 0, {"word": "b"})
        db.add_daily_card(1, "2026-07-11", 0, {"word": "c"})
        self.assertEqual(
            db.get_recent_daily_card_dates(1, limit=3),
            ["2026-07-12", "2026-07-11", "2026-07-10"],
        )

    def test_review_keyboards_expose_dates_and_menu(self):
        menu = daily_review_menu_keyboard()
        self.assertEqual(menu.inline_keyboard[0][0].callback_data, "review:menu")

        dates = daily_review_dates_keyboard(["2026-07-12", "2026-07-11"])
        self.assertEqual(dates.inline_keyboard[0][0].callback_data, "review:date:2026-07-12")
        self.assertEqual(dates.inline_keyboard[1][0].callback_data, "review:date:2026-07-11")

        next_card = daily_card_keyboard(1, "2026-07-12", 0, True, callback_prefix="review:next")
        self.assertEqual(
            next_card.inline_keyboard[0][0].callback_data,
            "review:next:1:2026-07-12:0",
        )

    def test_custom_word_validation_rejects_long_or_unrelated_input(self):
        self.assertIsNone(_custom_word_input_error("thick burger", "en"))
        self.assertIsNotNone(_custom_word_input_error("همبرگر آفرقایی کلفت", "en"))
        self.assertIsNotNone(_custom_word_input_error("one two three four", "en"))
        self.assertIsNotNone(_custom_word_input_error("", "en"))

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


if __name__ == "__main__":
    unittest.main()
