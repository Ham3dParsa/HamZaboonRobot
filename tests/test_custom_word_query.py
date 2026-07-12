import json
import os
import tempfile
import unittest

import db
from keyboards import main_menu, query_result_keyboard, BTN_ASK_WORD


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


if __name__ == "__main__":
    unittest.main()
