import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from handlers import srs_handler
from services.utils.formatting import format_card, format_srs_prompt
from config.keyboards import srs_hidden_keyboard, srs_revealed_keyboard


class SrsKeyboardTests(unittest.TestCase):
    def test_hidden_keyboard_offers_recall_and_reveal(self):
        markup = srs_hidden_keyboard(123, 456)
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertEqual(callbacks, ["srs:remember:123:456", "srs:reveal:123:456"])
        self.assertTrue(all(len(c) < 64 for c in callbacks))

    def test_revealed_keyboard_has_translations_and_actions(self):
        markup = srs_revealed_keyboard(123, 456)
        rows = markup.inline_keyboard
        self.assertEqual(rows[0][0].callback_data, "srs:prepare:123:456")
        self.assertEqual(rows[1][0].callback_data, "srs:confirm:123:456")
        self.assertEqual(rows[1][1].callback_data, "srs:again:123:456")
        callbacks = [b.callback_data for row in rows for b in row]
        self.assertTrue(all(len(c) < 64 for c in callbacks))


class SrsPromptRenderingTests(unittest.TestCase):
    def _card(self):
        return {
            "word": "hello",
            "phonetic": {"ipa": "hɛ.loʊ"},
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام کردن استفاده می‌شود.",
            "synonyms": ["hi"],
            "antonyms": [],
            "examples": ["Hello there."],
            "example_translations": ["سلام آنجا."],
            "grammar_tip": "یک نکته.",
        }

    def test_hidden_prompt_hides_meaning_examples_and_tip(self):
        text = format_srs_prompt(self._card())
        self.assertIn("hello", text)
        self.assertNotIn("سلام", text)
        self.assertNotIn("Hello there", text)
        self.assertNotIn("یک نکته", text)

    def test_revealed_card_shows_full_content(self):
        text = format_card(self._card(), presentation="detailed")
        self.assertIn("سلام", text)
        self.assertIn("Hello there", text)
        self.assertIn("یک نکته", text)


class ReviewEventPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    def _events(self):
        with db.get_conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT word_id, user_id, revealed_before_answer, outcome FROM review_events ORDER BY id"
            ).fetchall()]

    def test_record_review_event_persists_signal(self):
        db.record_review_event(5, 1, revealed_before_answer=False, outcome="recalled")
        db.record_review_event(5, 1, revealed_before_answer=True, outcome="recalled_after_peek")
        db.record_review_event(5, 1, revealed_before_answer=True, outcome="again")
        events = self._events()
        self.assertEqual(
            events,
            [
                {"word_id": 5, "user_id": 1, "revealed_before_answer": 0, "outcome": "recalled"},
                {"word_id": 5, "user_id": 1, "revealed_before_answer": 1, "outcome": "recalled_after_peek"},
                {"word_id": 5, "user_id": 1, "revealed_before_answer": 1, "outcome": "again"},
            ],
        )

    def test_record_review_event_rejects_unknown_outcome(self):
        with self.assertRaises(ValueError):
            db.record_review_event(5, 1, revealed_before_answer=False, outcome="mystery")

    def test_review_events_table_created_on_upgrade_from_legacy_db(self):
        os.remove(db.DB_PATH)
        with db.get_conn() as conn:
            conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
            conn.commit()
        db.init_db()
        with db.get_conn() as conn:
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("review_events", tables)
        db.record_review_event(1, 1, revealed_before_answer=False, outcome="recalled")
        self.assertEqual(len(self._events()), 1)


class SrsHandlerFlowTests(unittest.TestCase):
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
        # Move the word into the pending-review state the reveal handler requires.
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE saved_words SET review_status='pending' WHERE id=?",
                (self.word_id,),
            )
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    def _query(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        query.message.text = "hello"
        return query

    def _update(self, query):
        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query = query
        return update

    def _events(self):
        with db.get_conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT revealed_before_answer, outcome FROM review_events ORDER BY id"
            ).fetchall()]

    def test_remember_from_hidden_screen_records_pure_recall(self):
        query = self._query()
        update = self._update(query)
        asyncio.run(srs_handler._handle_srs_review(update, "remember", "1", str(self.word_id)))
        self.assertEqual(
            self._events(),
            [{"revealed_before_answer": 0, "outcome": "recalled"}],
        )

    def test_confirm_after_reveal_records_peeked_recall(self):
        query = self._query()
        update = self._update(query)
        card = {"word": "hello", "fa_meaning": "سلام", "fa_explanation": "x"}
        context = MagicMock()
        with patch.object(srs_handler, "_prepare_cached_card", return_value=card):
            asyncio.run(srs_handler._handle_srs_reveal(update, context, "1", str(self.word_id)))
        query.edit_message_text.assert_awaited()
        asyncio.run(srs_handler._handle_srs_review(update, "confirm", "1", str(self.word_id)))
        self.assertEqual(
            self._events(),
            [{"revealed_before_answer": 1, "outcome": "recalled_after_peek"}],
        )

    def test_again_after_reveal_records_failure(self):
        query = self._query()
        update = self._update(query)
        asyncio.run(srs_handler._handle_srs_review(update, "again", "1", str(self.word_id)))
        self.assertEqual(
            self._events(),
            [{"revealed_before_answer": 1, "outcome": "again"}],
        )


if __name__ == "__main__":
    unittest.main()
