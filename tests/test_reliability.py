import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import patch

import bot
import db


class ReliabilityPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        self.tempdir.cleanup()

    def test_word_query_reservation_is_atomic_and_bounded(self):
        db.create_user_if_needed(1, "learner")
        self.assertTrue(db.reserve_word_query(1, 1))
        self.assertFalse(db.reserve_word_query(1, 1))

    def test_grammar_tip_reservation_is_atomic_and_bounded(self):
        db.create_user_if_needed(1, "learner")
        self.assertTrue(db.reserve_grammar_tip(1, 1))
        self.assertFalse(db.reserve_grammar_tip(1, 1))

    def test_saved_word_insert_is_idempotent(self):
        db.create_user_if_needed(1, "learner")
        self.assertTrue(db.add_saved_word(1, "  Hello   ", "en"))
        self.assertFalse(db.add_saved_word(1, "hello", "en"))
        self.assertEqual(len(db.due_words_for_user(1)), 0)

    def test_touch_streak_is_idempotent_within_a_day(self):
        db.create_user_if_needed(1, "learner")
        self.assertEqual(db.touch_streak(1), 1)
        self.assertEqual(db.touch_streak(1), 1)

    def test_manual_daily_card_request_primes_a_shared_batch_reservoir(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "words")
        db.set_user_level(1, "beginner")
        row = db.get_user(1)
        card_date = dt.date(2026, 7, 12).isoformat()
        calls: list[int] = []

        def fake_generate_daily_batch(lang, goal, level, card_count, used_words):
            calls.append(card_count)
            return [
                {
                    "word": f"word-{index}",
                    "translation": f"translation-{index}",
                    "romanization": "",
                    "grammar_tip": "",
                }
                for index in range(card_count)
            ]

        with patch.object(bot, "_generate_daily_batch", side_effect=fake_generate_daily_batch):
            card, index = bot._ensure_next_daily_card(1, row, card_date, 30)

        self.assertEqual(calls, [6])
        self.assertEqual(index, 0)
        self.assertEqual(card["word"], "word-0")
        self.assertEqual(db.count_daily_cards(1, card_date), 6)


if __name__ == "__main__":
    unittest.main()
