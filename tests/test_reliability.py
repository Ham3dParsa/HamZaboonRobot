import datetime as dt
import json
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.ai import ai
from handlers import admin
import bot
from services import db
from services.db import schema as db_schema
from services.utils import formatting
from services.utils import helpers
from services.ai import llm_services
from telegram.error import BadRequest, NetworkError, TimedOut


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
        text = admin._llm_cost_report_text(
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

        text = admin._llm_cost_report_text(
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
        for grade in (1, 2, 3, 4):
            self.assertTrue(
                db.grade_word_review(word_id, grade, 1),
                f"grade_word_review should return True for grade={grade}",
            )

    def test_surgical_card_patches_update_only_requested_fields(self):
        db.create_user_if_needed(1, "learner")
        card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Hello one.", "Hello two."],
            "example_translations": ["قدیمی اول.", "قدیمی دوم."],
        }
        db.add_daily_card(1, "2026-07-12", 0, card)
        self.assertTrue(
            db.update_daily_card_fields(
                1,
                "2026-07-12",
                0,
                {"example_translations": ["جدید اول.", "جدید دوم."]},
            )
        )
        updated = db.get_daily_cards(1, "2026-07-12")[0]
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
        daily_card = {
            "word": "hello",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Example one.", "Example two."],
            "example_translations": ["مثال اول.", "مثال دوم."],
        }
        db.add_daily_card(1, "2026-07-12", 0, daily_card)
        query_token = db.create_query_result(1, "hello", "hello", "en", daily_card)
        db.add_saved_word(1, "hello", "en", daily_card)

        daily_before = db.get_daily_cards(1, "2026-07-12")[0]
        query_before = json.loads(db.get_query_result(query_token, user_id=1)["result_json"])
        saved_before = json.loads(db.get_saved_word(1, user_id=1)["card_data"])

        formatting.format_card(daily_before, presentation="brief")
        formatting.format_card(daily_before, presentation="detailed", translations_prepared=True)
        formatting.format_card(query_before, presentation="brief")
        formatting.format_card(saved_before, presentation="detailed")

        self.assertEqual(db.get_daily_cards(1, "2026-07-12")[0], daily_before)
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

    def test_recent_daily_words_excludes_current_date(self):
        db.create_user_if_needed(1, "learner")
        db.add_daily_card(1, "2026-07-12", 0, {"word": "today"})
        db.add_daily_card(1, "2026-07-11", 0, {"word": "recent"})
        self.assertEqual(
            db.get_recent_daily_words(1, exclude_date="2026-07-12"),
            ["recent"],
        )

    def test_recent_daily_words_filters_by_language(self):
        db.create_user_if_needed(2, "learner")
        db.ensure_daily_card_session(2, "2026-07-10", "en", "general", "beginner")
        db.ensure_daily_card_session(2, "2026-07-11", "de", "general", "beginner")
        db.add_daily_card(2, "2026-07-10", 0, {"word": "hello"})
        db.add_daily_card(2, "2026-07-10", 1, {"word": "world"})
        db.add_daily_card(2, "2026-07-11", 0, {"word": "hallo"})
        db.add_daily_card(2, "2026-07-11", 1, {"word": "welt"})
        en_words = db.get_recent_daily_words(2, "en")
        de_words = db.get_recent_daily_words(2, "de")
        self.assertIn("hello", en_words)
        self.assertIn("world", en_words)
        self.assertNotIn("hallo", en_words)
        self.assertIn("hallo", de_words)
        self.assertIn("welt", de_words)
        self.assertNotIn("hello", de_words)

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





class CallbackAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_callback_answer_is_ignored(self):
        class FakeQuery:
            async def answer(self, *args, **kwargs):
                raise BadRequest("Query is too old and response timeout expired")

        await helpers._answer_callback_safely(FakeQuery(), "done")

    async def test_unrelated_callback_answer_error_is_reraised(self):
        class FakeQuery:
            async def answer(self, *args, **kwargs):
                raise BadRequest("message is not modified")

        with self.assertRaises(BadRequest):
            await helpers._answer_callback_safely(FakeQuery(), "done")


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
