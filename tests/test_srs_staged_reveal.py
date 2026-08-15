"""Tests for SRS staged-reveal flow with 4-grade buttons."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from handlers import srs_handler
from config.catalog import DISPLAY_TOGGLE_DEFAULTS
from services.utils import formatting as fmt
from config.keyboards import get_review_keyboard, get_first_exposure_keyboard


ALL_TOGGLES_ON = dict(DISPLAY_TOGGLE_DEFAULTS)


class SrsKeyboardTests(unittest.TestCase):
    def test_review_keyboard_has_4_grade_buttons(self):
        markup = get_review_keyboard(123, 456)
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertEqual(callbacks, ["srs:1:123:456", "srs:2:123:456", "srs:3:123:456", "srs:4:123:456"])
        self.assertTrue(all(len(c) < 64 for c in callbacks))

    def test_first_exposure_keyboard_has_4_grade_buttons(self):
        markup = get_first_exposure_keyboard(123, 456)
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertEqual(callbacks, ["srs:fe:1:123:456", "srs:fe:2:123:456", "srs:fe:3:123:456", "srs:fe:4:123:456"])
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

    def test_standard_front_stage_hides_meaning_examples_and_tip(self):
        text = fmt.format_srs_front_stage(
            self._card(),
            "standard",
            toggles=ALL_TOGGLES_ON,
        )
        self.assertIn("hello", text)
        self.assertNotIn("سلام", text)
        self.assertNotIn("Hello there", text)
        self.assertNotIn("یک نکته", text)

    def test_back_stage_shows_full_content(self):
        text = fmt.format_srs_back_stage(self._card(), toggles=ALL_TOGGLES_ON)
        self.assertIn("سلام", text)
        self.assertIn("Hello there", text)
        self.assertIn("یک نکته", text)


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
        # The card starts unexposed (first_exposure_done=0). Review tests first
        # expose it via grade_first_exposure, matching the real session flow.
        self.expose = db.grade_first_exposure(self.word_id, 3, 1)

    def _expose_id(self, card_word: str) -> int:
        """Insert a fresh unexposed card (for wrong-state tests)."""
        card = {
            "word": card_word,
            "fa_meaning": "م",
            "fa_explanation": "ت",
            "examples": ["A!"],
            "example_translations": ["م!"],
        }
        db.add_saved_word(1, card_word, "en", card)
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (card_word,)
            ).fetchone()["id"]

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

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        return ctx

    def _events(self):
        with db.get_conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT grade, activity_type, grade_source, raw_signal, "
                "response_time_ms, outcome FROM review_events ORDER BY id"
            ).fetchall()]

    def _row(self, word_id):
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT * FROM saved_words WHERE id=? AND user_id=1", (word_id,)
            ).fetchone()

    # T-expose — the card is exposed before regular review (persisted schedule).
    def test_first_exposure_persists_schedule(self):
        self.assertTrue(self.expose.ok)
        row = self._row(self.word_id)
        self.assertEqual(row["first_exposure_done"], 1)
        self.assertIsNotNone(row["last_review_at"])
        self.assertIsNotNone(row["next_review_at"])
        self.assertEqual(row["review_status"], "idle")
        self.assertIsNone(row["retry_at"])
        self.assertEqual(row["srs_retry_attempts"], 0)

    # T1 — grade=3 (Good) success path on an exposed card.
    # The DB-level first-exposure exposure writes no event (only the handler
    # writes events), so exactly one review event is expected.
    def test_grade_3_records_success(self):
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        asyncio.run(srs_handler._handle_srs_review(update, 3, "1", str(self.word_id), ctx))
        events = self._events()
        self.assertEqual(len(events), 1)  # only the review event
        review = events[-1]
        self.assertEqual(review["grade"], 3)
        self.assertEqual(review["activity_type"], "srs_review")
        self.assertEqual(review["outcome"], "recalled")

    # T2 — grade=1 (Again) failure path on exposed card
    def test_grade_1_records_failure(self):
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        asyncio.run(srs_handler._handle_srs_review(update, 1, "1", str(self.word_id), ctx))
        events = self._events()
        self.assertEqual(events[-1]["grade"], 1)
        self.assertEqual(events[-1]["outcome"], "again")

    # T3 — all 4 grades produce correct raw_signal (freshly exposed each loop is expensive;
    # reuse the same exposed card across four sequential reviews)
    def test_all_grades_produce_raw_signal(self):
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        for grade in (1, 2, 3, 4):
            asyncio.run(srs_handler._handle_srs_review(update, grade, "1", str(self.word_id), ctx))
        events = self._events()
        self.assertEqual(len(events), 4)  # 4 reviews (DB expose wrote no event)
        for i, grade in enumerate((1, 2, 3, 4)):
            expected = json.dumps({"button_value": grade})
            self.assertEqual(events[i]["raw_signal"], expected)
            self.assertEqual(events[i]["grade"], grade)

    # T4 — response time captured from context.user_data
    def test_response_time_captured(self):
        query = self._query()
        update = self._update(query)
        start = time.time()
        ctx = self._context()
        ctx.user_data[f"card_shown_at_{self.word_id}"] = start - 5  # 5 seconds ago
        asyncio.run(srs_handler._handle_srs_review(update, 3, "1", str(self.word_id), ctx))
        events = self._events()
        rt = events[-1]["response_time_ms"]
        self.assertIsNotNone(rt)
        self.assertGreater(rt, 4000)  # ~5000ms, allow margin

    # T5 — response time None when no timestamp
    def test_response_time_none_when_missing(self):
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        asyncio.run(srs_handler._handle_srs_review(update, 3, "1", str(self.word_id), ctx))
        events = self._events()
        self.assertIsNone(events[-1]["response_time_ms"])

    # T6 — first-exposure grade=4 records correctly
    def test_first_exposure_grade_4(self):
        fresh_id = self._expose_id("fe-again")
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        asyncio.run(srs_handler._handle_first_exposure_grade(
            update, ctx, "4", "1", str(fresh_id),
        ))
        events = self._events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["grade"], 4)
        self.assertEqual(events[0]["activity_type"], "first_exposure")
        self.assertIsNone(events[0]["response_time_ms"])

    # T7 — first-exposure has raw_signal and grade_source
    def test_first_exposure_has_raw_signal(self):
        fresh_id = self._expose_id("fe-signal")
        query = self._query()
        update = self._update(query)
        ctx = self._context()
        asyncio.run(srs_handler._handle_first_exposure_grade(
            update, ctx, "2", "1", str(fresh_id),
        ))
        events = self._events()
        self.assertEqual(events[0]["grade_source"], "direct_button")
        self.assertEqual(events[0]["raw_signal"], json.dumps({"button_value": 2}))

    # T9 — regular review on an unexposed card is a harmless wrong_state:
    # no event, no streak, and no advance.
    def test_review_wrong_state_records_nothing(self):
        fresh_id = self._expose_id("unexposed")
        with patch.object(srs_handler.db, "touch_streak", wraps=db.touch_streak) as touch:
            with patch.object(srs_handler, "advance_session", new=AsyncMock()) as advance:
                query = self._query()
                update = self._update(query)
                ctx = self._context()
                asyncio.run(srs_handler._handle_srs_review(
                    update, 3, "1", str(fresh_id), ctx,
                ))
        self.assertEqual(self._events(), [])
        touch.assert_not_called()
        advance.assert_not_called()
        call_args = query.answer.call_args
        self.assertIsNotNone(call_args)
        self.assertIn("وضعیت مرور نیست", call_args[0][0])

    # T10 — FE double-tap: second tap on an exposed card is harmless wrong_state.
    def test_first_exposure_double_tap_is_wrong_state(self):
        fresh_id = self._expose_id("double-tap")
        with patch.object(srs_handler, "advance_session", new=AsyncMock()) as advance:
            query = self._query()
            update = self._update(query)
            ctx = self._context()
            asyncio.run(srs_handler._handle_first_exposure_grade(
                update, ctx, "4", "1", str(fresh_id),
            ))
            # first tap succeeds
            asyncio.run(srs_handler._handle_first_exposure_grade(
                update, ctx, "4", "1", str(fresh_id),
            ))
        events = self._events()
        self.assertEqual(len(events), 1)  # only one FE event
        self.assertEqual(advance.await_count, 1)  # only first tap advanced
