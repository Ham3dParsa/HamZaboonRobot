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

    def test_delete_cascades_review_events(self):
        from services.db.reviews import record_review_event
        record_review_event(self.word_id, 1, grade=2, activity_type="srs_review")
        with db.get_conn() as conn:
            before = conn.execute(
                "SELECT COUNT(*) c FROM review_events WHERE word_id=?", (self.word_id,)
            ).fetchone()["c"]
        self.assertEqual(before, 1)
        self.assertTrue(db.delete_saved_word(self.word_id, 1))
        with db.get_conn() as conn:
            after = conn.execute(
                "SELECT COUNT(*) c FROM review_events WHERE word_id=?", (self.word_id,)
            ).fetchone()["c"]
        self.assertEqual(after, 0)

    def test_delete_nulls_query_results_saved_word_id(self):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO query_results "
                "(token, user_id, query_text, word, lang, result_json, "
                " created_at, expires_at, saved_at, saved_word_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("tok", 1, "q", "hello", "en", "{}", "2026-01-01", "2026-12-31",
                 "2026-01-01", self.word_id),
            )
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT saved_word_id, saved_at FROM query_results WHERE token='tok'"
            ).fetchone()
        self.assertEqual(row["saved_word_id"], self.word_id)
        self.assertIsNotNone(row["saved_at"])
        self.assertTrue(db.delete_saved_word(self.word_id, 1))
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT saved_word_id, saved_at FROM query_results WHERE token='tok'"
            ).fetchone()
        self.assertIsNone(row["saved_word_id"])
        self.assertIsNone(row["saved_at"])


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


class SrsRefillPriorityTests(unittest.TestCase):
    """Kilo review #406: refill must prefer tier-1 (due) over tier-2 (pre-FE)."""

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

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    def _seed(self, word, expose):
        db.add_saved_word(1, word, "en", {
            "word": word, "fa_meaning": "سلام", "fa_explanation": "توضیح",
            "examples": [f"{word}!"], "example_translations": ["سلام!"],
            "synonyms": [], "antonyms": [], "grammar_tip": "نکته",
        })
        with db.get_conn() as conn:
            word_id = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()["id"]
        if expose:
            self.assertTrue(db.grade_first_exposure(word_id, 3, 1).ok)
        return word_id

    def test_refill_priority_picks_tier1_due_over_tier2_pre_fe(self):
        from handlers.srs_handler import _next_due_node
        from handlers.study_handler import SessionState
        from services.session import SessionNode

        tier1_due = self._seed("alpha", expose=True)      # tier-1 review
        tier2_pre = self._seed("beta", expose=False)      # tier-2 pre-FE
        active_id = self._seed("active", expose=False)    # the card being deleted
        with db.transaction() as conn:
            conn.execute(
                "UPDATE saved_words SET next_review_at=? WHERE id=?",
                ("2000-01-01T00:00:00+00:00", tier1_due),
            )
        state = SessionState(
            nodes=[SessionNode(
                activity_type="srs_review", source_tier=1,
                card_data={"word": "active"}, source_id=active_id,
                activity_meta={"user_id": 1, "target_lang": "en"},
                grade_policy_ref="srs_review",
            )],
            total_cards=1, tier3_context={}, study_msg_id=999, plan="free",
        )
        refill = _next_due_node(1, "en", state)
        self.assertIsNotNone(refill)
        self.assertEqual(refill.source_id, tier1_due)
        self.assertEqual(refill.source_tier, 1)
        self.assertNotEqual(refill.source_id, tier2_pre)

    def test_refill_falls_back_to_tier2_when_tier1_exhausted(self):
        from handlers.srs_handler import _next_due_node
        from handlers.study_handler import SessionState
        from services.session import SessionNode

        tier2_pre = self._seed("beta", expose=False)   # only tier-2 pre-FE available
        active_id = self._seed("active", expose=False)
        state = SessionState(
            nodes=[SessionNode(
                activity_type="srs_review", source_tier=1,
                card_data={"word": "active"}, source_id=active_id,
                activity_meta={"user_id": 1, "target_lang": "en"},
                grade_policy_ref="srs_review",
            )],
            total_cards=1, tier3_context={}, study_msg_id=999, plan="free",
        )
        refill = _next_due_node(1, "en", state)
        self.assertIsNotNone(refill)
        self.assertEqual(refill.source_id, tier2_pre)
        self.assertEqual(refill.source_tier, 2)