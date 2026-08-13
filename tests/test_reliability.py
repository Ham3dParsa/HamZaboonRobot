import asyncio
import datetime as dt
import json
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.ai import ai
from handlers.admin_cost import _llm_cost_report_text
import bot
from services import db
from services.db import schema as db_schema
from services.utils import formatting
from services.utils import helpers
from services.utils import callback_notifications
from services.ai import llm_services
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut


_NOW_ISO = "2026-01-01T00:00:00+00:00"
_NOW_ISO_EARLY = "2025-12-25T00:00:00+00:00"


class ReliabilityPersistenceTests(unittest.TestCase):
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

    def test_word_query_reservation_is_atomic_and_bounded(self):
        db.create_user_if_needed(1, "learner")
        self.assertTrue(db.reserve_word_query(1, 1))
        self.assertFalse(db.reserve_word_query(1, 1))
        db.release_word_query(1)
        self.assertTrue(db.reserve_word_query(1, 1))

    def test_grammar_tip_reservation_is_atomic_and_bounded(self):
        db.create_user_if_needed(1, "learner")
        self.assertTrue(db.reserve_grammar_tip(1, 1))
        self.assertFalse(db.reserve_grammar_tip(1, 1))
        db.release_grammar_tip(1)
        self.assertTrue(db.reserve_grammar_tip(1, 1))

    def test_ai_requests_record_cost_metrics_and_failure_modes(self):
        db.set_llm_cost_profile(
            input_cost_usd_per_million=1.0,
            output_cost_usd_per_million=2.0,
            usd_to_toman_rate=50000,
        )
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
            ),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"title": "Adjectives"}')
                )
            ],
        )
        with (
            patch.object(ai, "_client", return_value=client),
            patch.object(ai, "_model", return_value="test-model"),
            self.assertLogs("services.ai.ai", level="INFO") as logs,
        ):
            result = ai.ask_json(
                "system",
                request_kind="grammar_tip",
                user_id=1,
                plan="gold",
            )

        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["temperature"], ai.AI_TEMPERATURE)
        self.assertEqual(kwargs["max_tokens"], ai.AI_MAX_OUTPUT_TOKENS)
        self.assertEqual(result["title"], "Adjectives")
        self.assertIn("30 tok", logs.output[0])
        row = db.recent_llm_requests(limit=1)[0]
        self.assertEqual(row["user_id"], 1)
        self.assertEqual(row["plan"], "gold")
        self.assertEqual(row["request_kind"], "grammar_tip")
        self.assertEqual(row["outcome"], "success")
        self.assertAlmostEqual(row["cost_usd"], 0.00005, places=8)
        self.assertAlmostEqual(row["cost_toman"], 2.5, places=8)

        client.chat.completions.create.return_value = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=7,
                completion_tokens=11,
                total_tokens=18,
            ),
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="not json"))
            ],
        )
        with (
            patch.object(ai, "_client", return_value=client),
            patch.object(ai, "_model", return_value="test-model"),
        ):
            with self.assertRaises(Exception):
                ai.ask_json("system", request_kind="grammar_tip", user_id=2, plan="silver")
        row = db.recent_llm_requests(limit=1)[0]
        self.assertEqual(row["user_id"], 2)
        self.assertEqual(row["outcome"], "failure_billed")

        client.chat.completions.create.side_effect = RuntimeError("boom")
        with (
            patch.object(ai, "_client", return_value=client),
            patch.object(ai, "_model", return_value="test-model"),
        ):
            with self.assertRaises(RuntimeError):
                ai.ask_json("system", request_kind="grammar_tip", user_id=3, plan="free")
        row = db.recent_llm_requests(limit=1)[0]
        self.assertEqual(row["user_id"], 3)
        self.assertEqual(row["outcome"], "failure_zero_cost")

    def test_llm_cost_dashboard_reports_filters_and_projection(self):
        db.set_llm_cost_profile(
            input_cost_usd_per_million=1.0,
            output_cost_usd_per_million=2.0,
            usd_to_toman_rate=50000,
        )
        db.add_llm_request(
            user_id=1,
            plan="gold",
            request_kind="grammar_tip",
            model="test-model",
            outcome="success",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            input_cost_usd_per_million=1.0,
            output_cost_usd_per_million=2.0,
            usd_to_toman_rate=50000,
            latency_ms=123,
        )
        text = _llm_cost_report_text(
            {
                "range": "mtd",
                "detail": True,
                "plan": "gold",
                "user_id": 1,
                "request_kind": "grammar_tip",
                "model": "test-model",
                "outcome": "success",
            }
        )
        self.assertIn("📊 LLM Cost Dashboard", text)
        self.assertIn("plan=gold", text)
        self.assertIn("user=1", text)
        self.assertIn("🧾 Recent Requests", text)
        self.assertIn("📈 Month-end Projection", text)
        self.assertIn("Success rate: 100.0%", text)

    def test_llm_dashboard_breakdowns_include_failure_rate(self):
        db.add_llm_request(
            user_id=1,
            plan="silver",
            request_kind="daily_batch",
            model="test-model",
            outcome="failure_billed",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            input_cost_usd_per_million=1.0,
            output_cost_usd_per_million=2.0,
            usd_to_toman_rate=50000,
            latency_ms=456,
        )

        rows = db.breakdown_llm_requests("plan")

        self.assertEqual(rows[0]["bucket"], "silver")
        self.assertEqual(rows[0]["billed_failure_count"], 1)
        self.assertEqual(rows[0]["request_count"], 1)

        text = _llm_cost_report_text(
            {
                "range": "all",
                "detail": False,
                "plan": None,
                "user_id": None,
                "request_kind": None,
                "model": None,
                "outcome": None,
            }
        )
        self.assertIn("⚠️ Attention required", text)
        self.assertIn("Billed failure rate: 100.0%", text)
        self.assertIn("billed fail", text)

    def test_saved_word_insert_is_idempotent(self):
        db.create_user_if_needed(1, "learner")
        self.assertTrue(db.add_saved_word(1, "  Hello   ", "en"))
        self.assertFalse(db.add_saved_word(1, "hello", "en"))
        self.assertEqual(len(db.due_words_for_user(1)), 0)

    def test_saved_word_can_store_complete_card_and_pending_review_state(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "یک سلام ساده.",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
        }
        self.assertTrue(db.add_saved_word(1, "hello", "en", card))
        row = db.get_saved_word(1, user_id=1)
        self.assertIn("سلام", row["card_data"])
        self.assertEqual(row["first_exposure_done"], 0)

        # Once first exposure completes, it becomes a due Tier 1 word.
        with db.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE saved_words SET first_exposure_done=1 WHERE id=? AND user_id=?",
                (row["id"], 1),
            )
            conn.commit()
        with patch("services.db.words._today", return_value=dt.date.fromisoformat(row["next_review"])):
            due = db.due_words_for_user(1)
            self.assertEqual(len(due), 1)

    def test_grade_word_review_accepts_all_grades(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "world",
            "fa_meaning": "جهان",
            "fa_explanation": "دنیا.",
            "examples": ["Hello world!"],
            "example_translations": ["سلام دنیا!"],
        }
        self.assertTrue(db.add_saved_word(1, "world", "en", card))
        row = db.get_saved_word(1, user_id=1)
        word_id = row["id"]
        fixed_now = dt.datetime(2026, 8, 13, 10, 0, 0).replace(tzinfo=dt.timezone.utc)
        for grade in (1, 2, 3, 4):
            with db.get_conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE saved_words SET first_exposure_done=1, "
                    "last_review_at=?, stability=?, difficulty=? "
                    "WHERE id=? AND user_id=?",
                    (
                        "2026-08-01T10:00:00+00:00",
                        5.0,
                        5.0,
                        word_id,
                        1,
                    ),
                )
                conn.commit()
            with patch("services.db.words._utc_now", return_value=fixed_now):
                result = db.grade_word_review(word_id, grade, 1)
            self.assertTrue(result.ok, f"grade {grade} should succeed")
            self.assertIsNotNone(result.next_review_at, f"grade {grade} schedules a due")
            self.assertIsNotNone(result.interval_seconds, f"grade {grade} reports interval")
            persisted = db.get_saved_word(word_id, user_id=1)
            self.assertGreater(persisted["stability"], 0.0, f"grade {grade} persists stability")
            self.assertIsNotNone(persisted["next_review_at"], f"grade {grade} persists next_review_at")

    def test_surgical_card_patches_update_only_requested_fields(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Hello one.", "Hello two."],
            "example_translations": ["قدیمی اول.", "قدیمی دوم."],
        }
        self.assertTrue(db.add_saved_word(1, "hello", "en", card))
        row = db.get_saved_word(1, user_id=1)
        self.assertTrue(
            db.update_saved_word_fields(
                row["id"],
                1,
                {"example_translations": ["جدید اول.", "جدید دوم."]},
            )
        )
        updated = json.loads(db.get_saved_word(row["id"], user_id=1)["card_data"])
        self.assertEqual(updated["word"], "hello")
        self.assertEqual(updated["examples"], card["examples"])
        self.assertEqual(
            updated["example_translations"],
            ["جدید اول.", "جدید دوم."],
        )

    def test_valid_cached_card_skips_ai_and_invalid_card_uses_one_minimal_patch(self):
        valid = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Hello one.", "Hello two."],
            "example_translations": ["اول.", "دوم."],
        }
        with patch.object(llm_services, "_call_ai_limited") as repair_call:
            self.assertEqual(
                llm_services._prepare_cached_card(
                    valid,
                    lang="en",
                    user_id=1,
                    plan="free",
                    source="daily",
                    persist_patch=MagicMock(return_value=True),
                )["word"],
                "hello",
            )
            repair_call.assert_not_called()

        legacy = dict(valid)
        legacy["example_translations"] = ["اول."]
        persisted = MagicMock(return_value=True)
        with patch.object(
            llm_services,
            "_call_ai_limited",
            return_value={
                "examples": ["Hello one.", "Hello two."],
                "example_translations": ["اول.", "دوم."],
            },
        ) as repair_call:
            repaired = llm_services._prepare_cached_card(
                legacy,
                lang="en",
                user_id=1,
                plan="free",
                source="daily",
                persist_patch=persisted,
            )
        self.assertEqual(repaired["example_translations"], ["اول.", "دوم."])
        repair_call.assert_called_once()
        persisted.assert_called_once_with(
            {
                "examples": ["Hello one.", "Hello two."],
                "example_translations": ["اول.", "دوم."],
            }
        )

    def test_rendering_keeps_persisted_card_payloads_unchanged(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Example one.", "Example two."],
            "example_translations": ["مثال اول.", "مثال دوم."],
        }
        query_token = db.create_query_result(1, "hello", "hello", "en", card)
        db.add_saved_word(1, "hello", "en", card)

        query_before = json.loads(db.get_query_result(query_token, user_id=1)["result_json"])
        saved_before = json.loads(db.get_saved_word(1, user_id=1)["card_data"])

        formatting.format_card(query_before, presentation="brief")
        formatting.format_card(saved_before, presentation="detailed")

        self.assertEqual(
            json.loads(db.get_query_result(query_token, user_id=1)["result_json"]),
            query_before,
        )
        self.assertEqual(
            json.loads(db.get_saved_word(1, user_id=1)["card_data"]),
            saved_before,
        )

    def test_saved_word_migration_preserves_legacy_rows(self):
        os.remove(db.DB_PATH)
        with db.get_conn() as conn:
            conn.execute(
                "CREATE TABLE saved_words ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, word TEXT, "
                "lang TEXT, interval_idx INTEGER DEFAULT 0, next_review TEXT, added_at TEXT)"
            )
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, interval_idx, next_review) "
                "VALUES(1, ' Hello ', 'en', 0, '2026-07-13')"
            )
            conn.commit()
        db.init_db()

        row = db.get_saved_word(1, user_id=1)
        self.assertEqual(row["normalized_word"], "hello")
        self.assertEqual(row["review_status"], "idle")
        self.assertIsNone(row["card_data"])
        self.assertIsNone(row["review_requested_at"])

    def test_user_presentation_preference_migrates_from_legacy_schema(self):
        os.remove(db.DB_PATH)
        with db.get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    target_lang TEXT,
                    goal TEXT,
                    level TEXT NOT NULL DEFAULT 'beginner',
                    plan TEXT DEFAULT 'free',
                    streak INTEGER DEFAULT 0,
                    last_active_date TEXT,
                    words_asked_today INTEGER DEFAULT 0,
                    words_asked_date TEXT,
                    grammar_tips_asked_today INTEGER DEFAULT 0,
                    grammar_tips_asked_date TEXT,
                    optional_daily_limit INTEGER,
                    preferred_delivery_minute INTEGER,
                    active_window_start_minute INTEGER,
                    active_window_end_minute INTEGER,
                    onboarded INTEGER DEFAULT 0,
                    created_at TEXT
                )
                """
            )
            conn.commit()
        db.init_db()
        with db.get_conn() as conn:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
        self.assertIn("presentation_preference", columns)
        db.create_user_if_needed(1, "learner")
        db.set_plan(1, "silver")
        db.set_presentation_preference(1, "brief")
        self.assertEqual(db.get_user(1)["presentation_preference"], "brief")

    def test_recent_grammar_tip_titles_are_language_scoped(self):
        db.create_user_if_needed(1, "learner")
        db.add_grammar_tip(1, "Adjectives", "en", "general", "beginner", {"title": "Adjectives"})
        db.add_grammar_tip(1, "Artikel", "de", "general", "beginner", {"title": "Artikel"})
        self.assertEqual(db.recent_grammar_tip_titles(1, "en"), ["Adjectives"])

    def test_touch_streak_is_idempotent_within_a_day(self):
        db.create_user_if_needed(1, "learner")
        self.assertEqual(db.touch_streak(1), 1)
        self.assertEqual(db.touch_streak(1), 1)

    def test_multiple_saved_words_are_readable_first_exposure_cards(self):
        db.create_user_if_needed(1, "learner")
        cards = [
            {
                "word": f"word-{index}",
                "fa_meaning": "معنی",
                "fa_explanation": "توضیح",
                "examples": [f"Example {index}."],
                "example_translations": [f"مثال {index}."],
            }
            for index in range(6)
        ]

        for card in cards:
            self.assertTrue(db.add_saved_word(1, card["word"], "en", card))

        stored = [json.loads(row["card_data"]) for row in db.get_pre_first_exposure_words(1)]
        self.assertEqual(len(stored), 6)
        self.assertEqual([card["word"] for card in stored], [f"word-{i}" for i in range(6)])


class Phase4DueSelectionAndPriorityTests(unittest.TestCase):
    """Phase 04 — exact-timestamp due selection and DSR priority ordering."""

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

    def _make_due(self, word, **overrides):
        """Insert a due Tier-1 card (first_exposure_done=1) with overridable fields."""
        db.add_saved_word(1, word, "en")
        with db.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()
            w_id = row["id"]
            fields = {
                "first_exposure_done": 1,
                "last_review_at": "2026-01-01T00:00:00+00:00",
                "next_review_at": "2026-01-01T00:00:00+00:00",
                "stability": 1.0,
                "difficulty": 5.0,
            }
            fields.update(overrides)
            assignments = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE saved_words SET {assignments} WHERE id=? AND user_id=?",
                (*fields.values(), w_id, 1),
            )
            conn.commit()
        return w_id

    def test_future_exact_timestamp_excluded(self):
        with patch("services.db.words._utc_now", return_value=dt.datetime(
            2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc
        )):
            self._make_due("future", next_review_at="2026-01-01T12:00:01+00:00")
            self.assertEqual(db.due_words_for_user(1), [])

    def test_boundary_exact_timestamp_included(self):
        with patch("services.db.words._utc_now", return_value=dt.datetime(
            2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc
        )):
            self._make_due("boundary", next_review_at="2026-01-01T12:00:00+00:00")
            due = db.due_words_for_user(1)
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0]["word"], "boundary")

    def test_legacy_date_fallback_when_timestamp_null(self):
        with patch("services.db.words._utc_now", return_value=dt.datetime(
            2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc
        )), patch("services.db.words._today", return_value=dt.date(2026, 1, 1)):
            self._make_due("legacy", next_review_at=None, next_review="2026-01-01")
            due = db.due_words_for_user(1)
            self.assertEqual([r["word"] for r in due], ["legacy"])

    def test_legacy_future_date_excluded(self):
        with patch("services.db.words._utc_now", return_value=dt.datetime(
            2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc
        )), patch("services.db.words._today", return_value=dt.date(2026, 1, 1)):
            self._make_due("legacy-future", next_review_at=None, next_review="2026-01-02")
            self.assertEqual(db.due_words_for_user(1), [])

    def test_first_exposure_and_retry_filters_preserved(self):
        with patch("services.db.words._utc_now", return_value=dt.datetime(
            2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc
        )), patch("services.db.words._today", return_value=dt.date(2026, 1, 1)):
            not_exposed = self._make_due("not-exposed", first_exposure_done=0)
            retry = self._make_due("retry", retry_at="2026-01-01T11:00:00+00:00")
            pending = self._make_due(
                "pending", review_status="pending", review_requested_at="2026-01-01T10:00:00+00:00"
            )
            due = db.due_words_for_user(1)
            words = {r["word"] for r in due}
            self.assertNotIn("not-exposed", words)
            self.assertNotIn("retry", words)
            self.assertNotIn("pending", words)

    def test_lower_retrievability_prioritized(self):
        now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
        base = (now - dt.timedelta(days=3)).isoformat()
        with patch("services.db.words._utc_now", return_value=now), patch(
            "services.db.words._today", return_value=dt.date(2026, 1, 1)
        ):
            # Same elapsed, same difficulty, different stability -> lower R first.
            self._make_due(
                "low-stab", last_review_at=base, stability=1.0, difficulty=5.0,
                next_review_at="2026-01-01T11:00:00+00:00",
            )
            self._make_due(
                "high-stab", last_review_at=base, stability=10.0, difficulty=5.0,
                next_review_at="2026-01-01T11:00:00+00:00",
            )
            due = db.due_words_for_user(1)
            self.assertEqual(due[0]["word"], "low-stab")

    def test_higher_difficulty_tiebreaker(self):
        now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
        base = (now - dt.timedelta(days=3)).isoformat()
        with patch("services.db.words._utc_now", return_value=now), patch(
            "services.db.words._today", return_value=dt.date(2026, 1, 1)
        ):
            self._make_due(
                "easy", last_review_at=base, stability=5.0, difficulty=2.0,
                next_review_at="2026-01-01T11:00:00+00:00",
            )
            self._make_due(
                "hard", last_review_at=base, stability=5.0, difficulty=8.0,
                next_review_at="2026-01-01T11:00:00+00:00",
            )
            due = db.due_words_for_user(1)
            self.assertEqual(due[0]["word"], "hard")

    def test_older_due_instant_prioritized(self):
        now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
        base = (now - dt.timedelta(days=3)).isoformat()
        with patch("services.db.words._utc_now", return_value=now), patch(
            "services.db.words._today", return_value=dt.date(2026, 1, 1)
        ):
            self._make_due(
                "newer-due", last_review_at=base, stability=5.0, difficulty=5.0,
                next_review_at="2026-01-01T11:00:00+00:00",
            )
            self._make_due(
                "older-due", last_review_at=base, stability=5.0, difficulty=5.0,
                next_review_at="2026-01-01T10:00:00+00:00",
            )
            due = db.due_words_for_user(1)
            self.assertEqual(due[0]["word"], "older-due")

    def test_lower_id_final_tiebreaker(self):
        now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
        base = (now - dt.timedelta(days=3)).isoformat()
        with patch("services.db.words._utc_now", return_value=now), patch(
            "services.db.words._today", return_value=dt.date(2026, 1, 1)
        ):
            first = self._make_due(
                "first-id", last_review_at=base, stability=5.0, difficulty=5.0,
                next_review_at="2026-01-01T11:00:00+00:00",
            )
            self._make_due(
                "second-id", last_review_at=base, stability=5.0, difficulty=5.0,
                next_review_at="2026-01-01T11:00:00+00:00",
            )
            due = db.due_words_for_user(1)
            self.assertEqual([r["id"] for r in due], [first, first + 1])

    def test_zero_stability_does_not_crash(self):
        now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
        base = (now - dt.timedelta(days=3)).isoformat()
        with patch("services.db.words._utc_now", return_value=now), patch(
            "services.db.words._today", return_value=dt.date(2026, 1, 1)
        ):
            self._make_due(
                "zero-stab", last_review_at=base, stability=0.0, difficulty=5.0,
                next_review_at="2026-01-01T11:00:00+00:00",
            )
            due = db.due_words_for_user(1)
            self.assertEqual(len(due), 1)

    def test_fractional_elapsed_uses_hours_not_day_truncation(self):
        # Same-day due (elapsed < 1 day) must compute a real R: among two
        # same-day cards with equal stability/difficulty, the one that has
        # been exposed longer (lower R) must sort first. A day-truncated
        # elapsed (0 or full-day) would tie them and fall to the id tiebreak,
        # failing this assertion.
        now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
        with patch("services.db.words._utc_now", return_value=now), patch(
            "services.db.words._today", return_value=dt.date(2026, 1, 1)
        ):
            self._make_due(
                "same-day-short", last_review_at="2026-01-01T11:00:00+00:00",
                stability=5.0, difficulty=5.0,
                next_review_at="2026-01-01T11:30:00+00:00",
            )
            self._make_due(
                "same-day-long", last_review_at="2026-01-01T06:00:00+00:00",
                stability=5.0, difficulty=5.0,
                next_review_at="2026-01-01T11:30:00+00:00",
            )
            due = db.due_words_for_user(1)
            # longer elapsed -> lower R -> higher priority -> first
            self.assertEqual(due[0]["word"], "same-day-long")
            self.assertEqual({r["word"] for r in due}, {"same-day-short", "same-day-long"})

    def test_tier2_manual_words_before_legacy_auto(self):
        now = _NOW_ISO  # defined below
        with db.get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO saved_words (user_id, word, lang, normalized_word, "
                "entry_source, first_exposure_done, added_at) "
                "VALUES (1,'auto-late','en','auto-late','legacy_daily',0,?)",
                (now,),
            )
            conn.execute(
                "INSERT INTO saved_words (user_id, word, lang, normalized_word, "
                "entry_source, first_exposure_done, added_at) "
                "VALUES (1,'auto-early','en','auto-early','legacy_daily',0,?)",
                (_NOW_ISO_EARLY,),
            )
            conn.execute(
                "INSERT INTO saved_words (user_id, word, lang, normalized_word, "
                "entry_source, first_exposure_done, added_at) "
                "VALUES (1,'manual-late','en','manual-late','manual',0,?)",
                (now,),
            )
            conn.execute(
                "INSERT INTO saved_words (user_id, word, lang, normalized_word, "
                "entry_source, first_exposure_done, added_at) "
                "VALUES (1,'manual-early','en','manual-early','manual',0,?)",
                (_NOW_ISO_EARLY,),
            )
            conn.commit()
        # manual group first (added_at ASC), then legacy AUTO group (added_at ASC)
        words = [r["word"] for r in db.get_pre_first_exposure_words(1)]
        self.assertEqual(words, ["manual-early", "manual-late", "auto-early", "auto-late"])


class CallbackAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_callback_answer_is_ignored(self):
        class FakeQuery:
            async def answer(self, *args, **kwargs):
                raise BadRequest("Query is too old and response timeout expired")

        await callback_notifications.notify_callback(FakeQuery(), "done")

    async def test_unrelated_callback_answer_error_is_reraised(self):
        class FakeQuery:
            async def answer(self, *args, **kwargs):
                raise BadRequest("message is not modified")

        with self.assertRaises(BadRequest):
            await callback_notifications.notify_callback(FakeQuery(), "done")


class NetworkResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_with_retry_succeeds_on_third_attempt(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        query.edit_message_text.side_effect = [
            TimedOut("timeout"),
            TimedOut("timeout"),
            "success",
        ]
        result = await helpers._edit_with_retry(query, "hello")
        self.assertEqual(result, "success")
        self.assertEqual(query.edit_message_text.call_count, 3)

    async def test_edit_with_retry_re_raises_bad_request(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock(
            side_effect=BadRequest("message is not modified")
        )
        with self.assertRaises(BadRequest):
            await helpers._edit_with_retry(query, "hello")
        self.assertEqual(query.edit_message_text.call_count, 1)

    async def test_delete_with_retry_succeeds_on_retry(self):
        bot_mock = MagicMock()
        bot_mock.delete_message = AsyncMock()
        bot_mock.delete_message.side_effect = [
            TimedOut("timeout"),
            TimedOut("timeout"),
            True,
        ]
        result = await helpers._delete_with_retry(bot_mock, 123, 456)
        self.assertTrue(result)
        self.assertEqual(bot_mock.delete_message.call_count, 3)

    async def test_delete_with_retry_re_raises_bad_request(self):
        bot_mock = MagicMock()
        bot_mock.delete_message = AsyncMock(
            side_effect=BadRequest("message can't be deleted")
        )
        with self.assertRaises(BadRequest):
            await helpers._delete_with_retry(bot_mock, 123, 456)
        self.assertEqual(bot_mock.delete_message.call_count, 1)

    async def test_telegram_offline_set_after_single_failure_with_threshold_one(self):
        bot._telegram_offline = False
        bot._consecutive_health_failures = 0
        context = MagicMock()
        context.bot.get_me = AsyncMock()
        context.bot.get_me.side_effect = TimedOut("timeout")
        await bot.connection_health_job(context)
        self.assertTrue(bot._telegram_offline)
        self.assertEqual(bot._consecutive_health_failures, 1)

    async def test_telegram_offline_resets_on_health_success(self):
        bot._telegram_offline = True
        bot._consecutive_health_failures = 5
        context = MagicMock()
        context.bot.get_me = AsyncMock(return_value=True)
        await bot.connection_health_job(context)
        self.assertFalse(bot._telegram_offline)
        self.assertEqual(bot._consecutive_health_failures, 0)

    async def test_reset_telegram_cb_resets_globals(self):
        bot._telegram_offline = True
        bot._consecutive_health_failures = 3
        helpers._reset_telegram_cb()
        self.assertFalse(bot._telegram_offline)
        self.assertEqual(bot._consecutive_health_failures, 0)

    async def test_send_with_retry_calls_reset_on_success(self):
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(return_value="ok")
        with patch.object(helpers, "_reset_telegram_cb") as reset_mock:
            result = await helpers._send_with_retry(bot_mock, 123, "hello")
        self.assertEqual(result, "ok")
        reset_mock.assert_called_once()

    async def test_edit_with_retry_calls_reset_on_success(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock(return_value="ok")
        with patch.object(helpers, "_reset_telegram_cb") as reset_mock:
            result = await helpers._edit_with_retry(query, "hello")
        self.assertEqual(result, "ok")
        reset_mock.assert_called_once()

    async def test_delete_with_retry_calls_reset_on_success(self):
        bot_mock = MagicMock()
        bot_mock.delete_message = AsyncMock(return_value=True)
        with patch.object(helpers, "_reset_telegram_cb") as reset_mock:
            result = await helpers._delete_with_retry(bot_mock, 123, 456)
        self.assertTrue(result)
        reset_mock.assert_called_once()

    async def test_send_voice_with_retry_calls_reset_on_success(self):
        bot_mock = MagicMock()
        bot_mock.send_voice = AsyncMock(return_value="ok")
        with patch.object(helpers, "_reset_telegram_cb") as reset_mock:
            result = await helpers._send_voice_with_retry(bot_mock, 123, b"audio")
        self.assertEqual(result, "ok")
        reset_mock.assert_called_once()

    async def test_reset_not_called_on_send_failure(self):
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(side_effect=BadRequest("bad"))
        with patch.object(helpers, "_reset_telegram_cb") as reset_mock:
            with self.assertRaises(BadRequest):
                await helpers._send_with_retry(bot_mock, 123, "hello")
        reset_mock.assert_not_called()

    async def test_send_with_retry_does_not_retry_on_timeout(self):
        """A send timeout is ambiguous (may already be delivered): never re-send."""
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(side_effect=TimedOut("timeout"))
        with self.assertRaises(TimedOut):
            await helpers._send_with_retry(bot_mock, 123, "hello")
        self.assertEqual(bot_mock.send_message.call_count, 1)

    async def test_send_with_retry_does_not_retry_on_network_error(self):
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(side_effect=NetworkError("down"))
        with self.assertRaises(NetworkError):
            await helpers._send_with_retry(bot_mock, 123, "hello")
        self.assertEqual(bot_mock.send_message.call_count, 1)

    async def test_send_with_retry_retries_on_retry_after(self):
        """RetryAfter means Telegram explicitly rejected it: retrying is safe."""
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(side_effect=[RetryAfter(1), "ok"])
        with patch.object(asyncio, "sleep", new=AsyncMock()):
            result = await helpers._send_with_retry(bot_mock, 123, "hello")
        self.assertEqual(result, "ok")
        self.assertEqual(bot_mock.send_message.call_count, 2)

    async def test_send_voice_with_retry_does_not_retry_on_timeout(self):
        bot_mock = MagicMock()
        bot_mock.send_voice = AsyncMock(side_effect=TimedOut("timeout"))
        with self.assertRaises(TimedOut):
            await helpers._send_voice_with_retry(bot_mock, 123, b"audio")
        self.assertEqual(bot_mock.send_voice.call_count, 1)

    async def test_send_voice_with_retry_retries_on_retry_after(self):
        bot_mock = MagicMock()
        bot_mock.send_voice = AsyncMock(side_effect=[RetryAfter(1), "ok"])
        with patch.object(asyncio, "sleep", new=AsyncMock()):
            result = await helpers._send_voice_with_retry(bot_mock, 123, b"audio")
        self.assertEqual(result, "ok")
        self.assertEqual(bot_mock.send_voice.call_count, 2)

    async def test_offline_notice_sent_once_per_window_per_user(self):
        """An offline user must receive the notice once per offline window."""
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value="ok")
        with patch.object(bot, "_offline_notice_sent", set()):
            await bot._send_offline_notice(context, 123)
            await bot._send_offline_notice(context, 123)
            await bot._send_offline_notice(context, 456)
        self.assertEqual(context.bot.send_message.call_count, 2)

    async def test_offline_notice_resends_after_window_cleared(self):
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value="ok")
        sent = set()
        with patch.object(bot, "_offline_notice_sent", sent):
            await bot._send_offline_notice(context, 123)
        sent.clear()
        await bot._send_offline_notice(context, 123)
        self.assertEqual(context.bot.send_message.call_count, 2)

    async def test_offline_notice_does_not_reset_offline_flag(self):
        """A successful offline notice must not flip the global flag mid-window."""
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value="ok")
        with patch.object(bot, "_offline_notice_sent", set()), \
                patch.object(bot, "_telegram_offline", True):
            await bot._send_offline_notice(context, 123)
            self.assertTrue(bot._telegram_offline)



class UserLockThreadSafetyTests(unittest.TestCase):
    """Finding #2: _get_user_lock must return same Lock for same user_id under concurrent access."""

    def test_get_user_lock_returns_same_object(self):
        lock1 = bot._get_user_lock(42)
        lock2 = bot._get_user_lock(42)
        self.assertIs(lock1, lock2)

    def test_get_user_lock_returns_different_for_different_users(self):
        lock_a = bot._get_user_lock(100)
        lock_b = bot._get_user_lock(200)
        self.assertIsNot(lock_a, lock_b)

    def test_concurrent_get_user_lock_returns_same_object(self):
        results = []

        def fetch():
            results.append(bot._get_user_lock(42))

        threads = [threading.Thread(target=fetch) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 10)
        for lock in results:
            self.assertIs(lock, results[0])


class BeginImmediateConcurrencyTests(unittest.TestCase):
    """Finding C1: BEGIN IMMEDIATE prevents database is locked under concurrent writes."""

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

    def test_concurrent_increment_consecutive_failures_is_serialized(self):
        NUM_THREADS = 10
        errors = []

        def increment():
            try:
                db.increment_consecutive_failures()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=increment) for _ in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(db.get_setting("ai_consecutive_failures", "0"), str(NUM_THREADS))

    def test_concurrent_set_setting_is_serialized(self):
        NUM_THREADS = 10
        errors = []

        def writer():
            try:
                db.set_setting("concurrent_test", "42")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
