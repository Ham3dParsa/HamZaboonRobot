import os
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
