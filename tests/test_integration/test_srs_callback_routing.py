"""Integration tests for SRS callback routing and schema migration (1g.7, 1g.8)."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class CallbackRoutingTest(unittest.TestCase):
    """1g.7: Verify callback_router dispatches old/new patterns correctly."""

    def setUp(self):
        import bot

        self.offline_patcher = patch.object(bot, "_telegram_offline", False)
        self.offline_patcher.start()
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        self.offline_patcher.stop()
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_update(self, callback_data: str):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = callback_data
        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query = query
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        return ctx

    def test_old_style_callback_rejected_gracefully(self):
        from bot import callback_router

        update = self._make_update("srs:remember:1:100")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.answer.call_args
        self.assertIn("دیگر معتبر نیست", call_args[0][0])

    def test_new_style_callback_dispatches_to_handler(self):
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
        }
        db.add_saved_word(1, "hello", "en", card)
        row = db.get_saved_word(1, user_id=1)
        word_id = row["id"]

        from bot import callback_router

        # A regular-review grade on an unexposed card is a harmless wrong_state:
        # the router still reaches the handler, but no telemetry/advance occurs.
        update = self._make_update(f"srs:3:1:{word_id}")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        self.assertEqual(self._events(), [])
        self.assertTrue(update.callback_query.answer.await_count >= 1)

        # Expose the card, then a regular review persists a grade + event.
        self.assertTrue(db.grade_first_exposure(word_id, 3, 1).ok)
        update = self._make_update(f"srs:3:1:{word_id}")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        events = self._events()
        self.assertEqual(len(events), 1, "Expected exactly one review event")
        self.assertEqual(events[-1]["grade"], 3)
        self.assertEqual(events[-1]["activity_type"], "srs_review")

    def test_invalid_grade_value_rejected(self):
        from bot import callback_router

        update = self._make_update("srs:99:1:100")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.answer.call_args
        self.assertIn("دیگر معتبر نیست", call_args[0][0])

    def test_wrong_part_count_rejected(self):
        from bot import callback_router

        update = self._make_update("srs:1:1")
        ctx = self._make_context()
        asyncio.run(callback_router(update, ctx))
        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.answer.call_args
        self.assertIn("نامعتبر", call_args[0][0])

    def _events(self):
        with db.get_conn() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT grade, activity_type, outcome FROM review_events ORDER BY id"
                ).fetchall()
            ]


class SavedWordSessionStateTest(unittest.TestCase):
    """Verify saved_words works without any daily persistence tables."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_new_saved_word_has_first_exposure_state(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "test",
            "fa_meaning": "تست",
            "fa_explanation": "تست.",
            "examples": ["Test!"],
            "example_translations": ["تست!"],
        }
        self.assertTrue(db.add_saved_word(1, "test", "en", card))
        row = db.get_saved_word(1, user_id=1)
        self.assertEqual(row["first_exposure_done"], 0)
        self.assertEqual(row["stability"], 0.0)
        self.assertEqual(row["difficulty"], 5.0)
        with db.get_conn() as conn:
            columns = {
                col["name"]
                for col in conn.execute("PRAGMA table_info(saved_words)").fetchall()
            }
        self.assertNotIn("interval_idx", columns)

    def test_multiple_saved_words_are_tier2_only(self):
        db.create_user_if_needed(1, "learner")
        for word in ("alpha", "beta"):
            card = {
                "word": word,
                "fa_meaning": "م",
                "fa_explanation": "ت",
                "examples": [f"{word} A!", f"{word} B!"],
                "example_translations": ["م", "ب"],
            }
            self.assertTrue(db.add_saved_word(1, word, "en", card))
        fe = db.get_pre_first_exposure_words(1)
        words = sorted(r["word"] for r in fe)
        self.assertEqual(words, ["alpha", "beta"])
        for row in fe:
            self.assertEqual(row["first_exposure_done"], 0)
            self.assertEqual(row["lang"], "en")
            self.assertIsNotNone(row["added_at"])
            self.assertEqual(row["entry_source"], "manual")
        self.assertEqual(db.due_words_for_user(1), [])

    def test_first_exposure_word_is_not_due_tier1(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "gamma",
            "fa_meaning": "م",
            "fa_explanation": "ت",
            "examples": ["G A!", "G B!"],
            "example_translations": ["م", "ب"],
        }
        db.add_saved_word(1, "gamma", "en", card)
        fe_words = [r["word"] for r in db.get_pre_first_exposure_words(1)]
        self.assertEqual(fe_words, ["gamma"])
        due = db.due_words_for_user(1)
        self.assertEqual(len(due), 0, "First-exposure words must not appear as due Tier 1")

    def test_duplicate_saved_word_preserves_existing_content(self):
        db.create_user_if_needed(1, "learner")
        original = {
            "word": "delta",
            "fa_meaning": "م",
            "fa_explanation": "original",
            "examples": ["D A!", "D B!"],
            "example_translations": ["م", "ب"],
        }
        replacement = dict(original, fa_explanation="replacement")
        self.assertTrue(db.add_saved_word(1, "delta", "en", original))
        self.assertFalse(db.add_saved_word(1, "delta", "en", replacement))
        with db.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) c FROM saved_words WHERE user_id=1 AND word='delta'"
            ).fetchone()["c"]
        self.assertEqual(count, 1)
        row = db.get_saved_word(1, user_id=1)
        self.assertEqual(
            json.loads(row["card_data"])["fa_explanation"],
            "original",
        )

    def test_init_db_is_idempotent_with_saved_words(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "persist",
            "fa_meaning": "م",
            "fa_explanation": "ت",
            "examples": ["P!"],
            "example_translations": ["پ!"],
        }
        db.add_saved_word(1, "persist", "en", card)
        db.init_db()
        row = db.get_saved_word(1, user_id=1)
        self.assertEqual(row["word"], "persist")
        with db.get_conn() as conn:
            tables = {
                item["name"]
                for item in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertTrue(
            {"daily_cards", "daily_progress", "daily_card_sessions"}.isdisjoint(
                tables
            )
        )


class QueryAddEntrySourceTest(unittest.TestCase):
    """entry_source: 'Add to review' flow writes entry_source='manual'."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_query_add_writes_entry_source_manual(self):
        from handlers.srs_handler import _handle_query_add

        result_data = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
        }
        token = db.create_query_result(1, "hello", "hello", "en", result_data)

        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query.answer = AsyncMock()
        ctx = MagicMock()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        ctx.user_data = {}

        asyncio.run(_handle_query_add(update, ctx, token))
        self.assertEqual(ctx.bot.edit_message_reply_markup.call_args.kwargs["chat_id"], update.effective_chat.id)
        self.assertEqual(ctx.bot.edit_message_reply_markup.call_args.kwargs["message_id"], update.effective_message.message_id)

        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT entry_source FROM saved_words WHERE user_id=1 AND word='hello'"
            ).fetchone()
        self.assertIsNotNone(row, "Add to review must create a saved_words row")
        self.assertEqual(row["entry_source"], "manual")

    def test_query_add_entry_source_default_via_add_saved_word(self):
        db.add_saved_word(1, "world", "en", {"word": "world"})
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT entry_source FROM saved_words WHERE user_id=1 AND word='world'"
            ).fetchone()
        self.assertEqual(row["entry_source"], "manual")


class LaterSessionAndTelemetryTest(unittest.TestCase):
    """Phase-05 integration: exact-due later-session and telemetry separation."""

    def setUp(self):
        import bot

        self.offline_patcher = patch.object(bot, "_telegram_offline", False)
        self.offline_patcher.start()
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")

    def tearDown(self):
        self.offline_patcher.stop()
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_due_card(self, word, next_review_at):
        card = {
            "word": word,
            "fa_meaning": "م",
            "fa_explanation": "ت",
            "examples": ["A!"],
            "example_translations": ["م!"],
        }
        db.add_saved_word(1, word, "en", card)
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE saved_words SET first_exposure_done=1, "
                "last_review_at=?, next_review_at=?, stability=2.0, "
                "difficulty=5.0, review_status='idle' WHERE id=? AND user_id=?",
                ("2026-01-01T00:00:00+00:00", next_review_at, row["id"], 1),
            )
            conn.commit()
        return row["id"]

    def test_card_absent_before_exact_due_then_present_after(self):
        """Rule 7/12: exact-timestamp due — same-day card appears only after due."""
        import datetime as dt

        now = dt.datetime(2026, 1, 5, 12, 0, 0, tzinfo=dt.timezone.utc)
        word_id = self._make_due_card(
            "later", "2026-01-05T16:00:00+00:00",
        )
        with patch("services.db.words._utc_now", return_value=now), patch(
            "services.db.words._today", return_value=dt.date(2026, 1, 5)
        ):
            due_now = [r["word"] for r in db.due_words_for_user(1)]
            self.assertNotIn("later", due_now, "must not appear before exact due")
        later = dt.datetime(2026, 1, 5, 16, 0, 0, tzinfo=dt.timezone.utc)
        with patch("services.db.words._utc_now", return_value=later), patch(
            "services.db.words._today", return_value=dt.date(2026, 1, 5)
        ):
            due_later = [r["word"] for r in db.due_words_for_user(1)]
            self.assertIn("later", due_later, "must appear in a later session after due")

    def test_telemetry_failure_rolls_back_atomically(self):
        """F1 (supersedes old Rule 10): grade + event + streak share one atomic
        transaction per tap, so a telemetry failure rolls the schedule back
        (all-or-nothing, safe to retry) instead of committing a partial grade.
        Replaces test_telemetry_failure_keeps_schedule_committed, whose
        swallow-and-commit expectation the F1 owner lock retired."""
        from handlers.srs_handler import _handle_srs_review

        word_id = self._make_due_card("tel", "2026-01-01T00:00:00+00:00")
        with db.get_conn() as conn:
            before = conn.execute(
                "SELECT last_review_at, next_review_at, stability "
                "FROM saved_words WHERE id=?", (word_id,)
            ).fetchone()
            self.assertIsNotNone(before["next_review_at"])

        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query = query
        ctx = MagicMock()
        ctx.user_data = {}

        with patch(
            "services.db.words._utc_now",
            return_value=__import__("datetime").datetime(2026, 1, 1, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc),
        ):
            with patch(
                "services.db.words.insert_review_event",
                side_effect=RuntimeError("analytics down"),
            ):
                # Must NOT raise: the handler catches the atomic failure and
                # shows the retry toast instead of advancing.
                asyncio.run(_handle_srs_review(update, 3, "1", str(word_id), ctx))

        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT last_review_at, next_review_at, stability, review_status "
                "FROM saved_words WHERE id=?", (word_id,)
            ).fetchone()
        self.assertEqual(row["last_review_at"], before["last_review_at"])
        self.assertEqual(row["next_review_at"], before["next_review_at"])
        self.assertEqual(row["stability"], before["stability"])
        with db.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) c FROM review_events WHERE word_id=?", (word_id,)
            ).fetchone()["c"]
        self.assertEqual(count, 0, "failed tap wrote no event and rolled back")
        self.assertFalse(db.is_word_graded(1, word_id, "srs_review"))
        # The tap was answered (error toast), never silently dropped.
        self.assertTrue(query.answer.await_count >= 1)


if __name__ == "__main__":
    unittest.main()
