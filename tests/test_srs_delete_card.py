"""Tests for the physical saved-word delete (Rule 4) — services/db/words.py::delete_saved_word."""

from __future__ import annotations

import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema
from config.keyboards import (
    get_review_keyboard,
    get_first_exposure_keyboard,
    get_srs_delete_confirm_keyboard,
)


class SrsDeleteDbTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام.",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
            "synonyms": [],
            "antonyms": [],
            "grammar_tip": "نکته",
        }
        db.add_saved_word(1, "hello", "en", card)
        with db.get_conn() as conn:
            self.word_id = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1"
            ).fetchone()["id"]

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    def test_delete_owned_word_returns_true_and_removes_row(self):
        self.assertTrue(db.delete_saved_word(self.word_id, 1))
        self.assertIsNone(db.get_saved_word(self.word_id))

    def test_delete_missing_word_is_idempotent_returns_false(self):
        self.assertTrue(db.delete_saved_word(self.word_id, 1))
        self.assertFalse(db.delete_saved_word(self.word_id, 1))

    def test_delete_wrong_user_returns_false_and_keeps_row(self):
        self.assertFalse(db.delete_saved_word(self.word_id, 999))
        self.assertIsNotNone(db.get_saved_word(self.word_id))

    def test_delete_non_existent_id_returns_false(self):
        self.assertFalse(db.delete_saved_word(999999, 1))


class SrsDeleteKeyboardTests(unittest.TestCase):
    def test_revealed_review_keyboard_has_delete_row(self):
        markup = get_review_keyboard(123, 456)
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("srs:delete:123:456", callbacks)

    def test_revealed_fe_keyboard_has_delete_row(self):
        markup = get_first_exposure_keyboard(123, 456)
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("srs:delete:123:456", callbacks)

    def test_delete_confirm_keyboard_yes_no(self):
        markup = get_srs_delete_confirm_keyboard(123, 456)
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertEqual(
            callbacks, ["srs:delete:yes:123:456", "srs:delete:no:123:456"]
        )