import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ai
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
            self.assertLogs("hamzaban.ai", level="INFO") as logs,
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
        self.assertIn("total_tokens=30", logs.output[0])
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
        text = bot._llm_cost_report_text(
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

        text = bot._llm_cost_report_text(
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

        with patch.object(db, "_today", return_value=dt.date.fromisoformat(row["next_review"])):
            due = db.due_words_for_user(1)
            self.assertEqual(len(due), 1)
            db.mark_word_review_pending(due[0]["id"])
            self.assertEqual(db.due_words_for_user(1), [])
            self.assertTrue(db.defer_word_review(due[0]["id"]))
            self.assertFalse(db.defer_word_review(due[0]["id"]))
            self.assertEqual(db.due_words_for_user(1), [])
            db.mark_word_review_pending(due[0]["id"])
            self.assertTrue(db.advance_word_review(due[0]["id"]))
            self.assertFalse(db.advance_word_review(due[0]["id"]))
            self.assertEqual(db.due_words_for_user(1), [])

    def test_saved_word_migration_preserves_legacy_rows(self):
        os.remove(db.DB_PATH)
        with sqlite3.connect(db.DB_PATH) as conn:
            conn.execute(
                "CREATE TABLE saved_words ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, word TEXT, "
                "lang TEXT, interval_idx INTEGER DEFAULT 0, next_review TEXT, added_at TEXT)"
            )
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, interval_idx, next_review) "
                "VALUES(1, ' Hello ', 'en', 0, '2026-07-13')"
            )
        db.init_db()

        row = db.get_saved_word(1, user_id=1)
        self.assertEqual(row["normalized_word"], "hello")
        self.assertEqual(row["review_status"], "idle")
        self.assertIsNone(row["card_data"])
        self.assertIsNone(row["review_requested_at"])

    def test_recent_daily_words_excludes_current_date(self):
        db.create_user_if_needed(1, "learner")
        db.add_daily_card(1, "2026-07-12", 0, {"word": "today"})
        db.add_daily_card(1, "2026-07-11", 0, {"word": "recent"})
        self.assertEqual(
            db.get_recent_daily_words(1, exclude_date="2026-07-12"),
            ["recent"],
        )

    def test_recent_grammar_tip_titles_are_language_scoped(self):
        db.create_user_if_needed(1, "learner")
        db.add_grammar_tip(1, "Adjectives", "en", "general", "beginner", {"title": "Adjectives"})
        db.add_grammar_tip(1, "Artikel", "de", "general", "beginner", {"title": "Artikel"})
        self.assertEqual(db.recent_grammar_tip_titles(1, "en"), ["Adjectives"])

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

        def fake_generate_daily_batch(
            lang,
            goal,
            level,
            card_count,
            used_words,
            user_id=None,
            plan=None,
        ):
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

    def test_six_card_batch_is_persisted_as_six_readable_cards(self):
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

        for index, card in enumerate(cards):
            db.add_daily_card(1, "2026-07-12", index, card)

        stored = db.get_daily_cards(1, "2026-07-12")
        self.assertEqual(len(stored), 6)
        self.assertEqual([card["word"] for card in stored], [f"word-{i}" for i in range(6)])

    def test_daily_batch_retry_removes_prompt_avoid_list_after_avoid_collisions(self):
        diagnostics = {
            "accepted": 0,
            "validation_rejected": 0,
            "duplicates_against_avoid": 6,
            "duplicates_within_batch": 0,
        }
        prompts_seen: list[str] = []
        calls = 0

        def fake_ask_batch(system_prompt, **kwargs):
            nonlocal calls
            calls += 1
            prompts_seen.append(system_prompt)
            if calls == 1:
                raise ai.BatchValidationError(
                    "No valid cards remained after batch validation",
                    diagnostics,
                )
            return [
                {
                    "word": "new-word",
                    "translation": "translation",
                }
            ]

        with patch.object(bot, "_ask_batch_limited", side_effect=fake_ask_batch):
            cards = bot._generate_daily_batch(
                "en",
                "general",
                "beginner",
                1,
                ["known-word"],
            )

        self.assertEqual(cards[0]["word"], "new-word")
        self.assertIn("known-word", prompts_seen[0])
        self.assertNotIn("known-word", prompts_seen[1])

    def test_daily_cards_lock_to_the_first_session_snapshot_of_the_day(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        row = db.get_user(1)
        card_date = dt.date(2026, 7, 12).isoformat()
        calls: list[tuple[str, str, str, int]] = []

        def fake_generate_daily_batch(
            lang,
            goal,
            level,
            card_count,
            used_words,
            user_id=None,
            plan=None,
        ):
            calls.append((lang, goal, level, card_count))
            return [
                {
                    "word": f"{lang}-{goal}-{level}-{index}",
                    "translation": f"translation-{index}",
                    "romanization": "",
                    "grammar_tip": "",
                }
                for index in range(card_count)
            ]

        with patch.object(bot, "_generate_daily_batch", side_effect=fake_generate_daily_batch):
            bot._ensure_next_daily_card(1, row, card_date, 12)
            db.set_daily_progress(1, card_date, 6)
            db.set_user_lang_goal(1, "es", "toeic")
            db.set_user_level(1, "advanced")
            bot._ensure_next_daily_card(1, db.get_user(1), card_date, 12)

        self.assertEqual(calls[0][:3], ("en", "general", "beginner"))
        self.assertEqual(calls[1][:3], ("en", "general", "beginner"))
        self.assertEqual(db.get_daily_card_session(1, card_date)["target_lang"], "en")
        self.assertEqual(db.count_daily_cards(1, card_date), 12)


if __name__ == "__main__":
    unittest.main()
