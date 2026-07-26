import unittest
import os
import tempfile
from unittest.mock import patch
from services import db
from services.srs_engine import generate_v3_session


def _empty_ai_call(*args, **kwargs):
    return []


class GenerateV3SessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db.init_db()
        db.create_user_if_needed(1, "test_user")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        self._ai_patcher = patch(
            "services.srs_engine._call_ai_limited",
            side_effect=_empty_ai_call,
        )
        self._ai_patcher.start()

    def tearDown(self):
        self._ai_patcher.stop()
        db.DB_PATH = self.previous_db_path
        self.tempdir.cleanup()

    async def test_tier1_due_words_are_selected_first(self):
        db.add_saved_word(1, "due_word", "en", {
            "word": "due_word",
            "fa_meaning": "\u0645\u0639\u0646\u06cc",
        })
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE saved_words SET interval_idx=0, next_review='2020-01-01'"
            )
            conn.commit()
        session = await generate_v3_session(1, "en", "general", "beginner", "free")
        self.assertGreater(len(session["nodes"]), 0)
        self.assertEqual(session["nodes"][0].source_tier, 1)
        self.assertEqual(session["nodes"][0].card_data["word"], "due_word")

    async def test_tier2_backlog_used_when_no_due_words(self):
        db.add_saved_word(1, "backlog_word", "en", {
            "word": "backlog_word",
            "fa_meaning": "\u0645\u0639\u0646\u06cc",
        })
        session = await generate_v3_session(1, "en", "general", "beginner", "free")
        self.assertGreater(len(session["nodes"]), 0)
        self.assertEqual(session["nodes"][0].source_tier, 2)
        self.assertEqual(session["nodes"][0].card_data["word"], "backlog_word")

    async def test_empty_session_when_no_content(self):
        session = await generate_v3_session(1, "en", "general", "beginner", "free")
        self.assertEqual(len(session["nodes"]), 0)
        self.assertEqual(session["slot_count"], 0)

    async def test_session_respects_plan_size(self):
        for plan, expected_size in [("free", 5), ("silver", 6), ("gold", 7)]:
            db.create_user_if_needed(2, "plan_user")
            db.set_plan(2, plan)
            db.set_user_lang_goal(2, "en", "general")
            db.set_user_level(2, "beginner")
            for i in range(expected_size + 2):
                db.add_saved_word(2, f"word_{i}", "en", {
                    "word": f"word_{i}",
                    "fa_meaning": "\u0645\u0639\u0646\u06cc",
                })
                with db.get_conn() as conn:
                    conn.execute(
                        "UPDATE saved_words SET interval_idx=0, next_review='2020-01-01' "
                        "WHERE word=?", (f"word_{i}",)
                    )
                    conn.commit()
            session = await generate_v3_session(2, "en", "general", "beginner", plan)
            self.assertLessEqual(len(session["nodes"]), expected_size)

    async def test_tier1_before_tier2_priority(self):
        db.add_saved_word(1, "backlog_first", "en", {
            "word": "backlog_first",
            "fa_meaning": "\u0645\u0639\u0646\u06cc",
        })
        db.add_saved_word(1, "due_first", "en", {
            "word": "due_first",
            "fa_meaning": "\u0645\u0639\u0646\u06cc",
        })
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE saved_words SET interval_idx=0, next_review='2020-01-01' "
                "WHERE word='due_first'"
            )
            conn.commit()
        session = await generate_v3_session(1, "en", "general", "beginner", "free")
        self.assertGreater(len(session["nodes"]), 1)
        self.assertEqual(session["nodes"][0].source_tier, 1)
        self.assertEqual(session["nodes"][1].source_tier, 2)

    async def test_tier3_ai_generated_fills_remaining_slots(self):
        db.add_saved_word(1, "saved_word", "en", {
            "word": "saved_word",
            "fa_meaning": "\u0645\u0639\u0646\u06cc",
        })
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE saved_words SET interval_idx=0, next_review='2020-01-01' "
                "WHERE word='saved_word'"
            )
            conn.commit()
        fake_cards = [
            {"word": "ai_word1", "fa_meaning": "\u0645\u0639\u0646\u06cc 1", "translation": "\u062a\u0631\u062c\u0645\u0647 1", "example": "\u0645\u062b\u0627\u0644 1"},
            {"word": "ai_word2", "fa_meaning": "\u0645\u0639\u0646\u06cc 2", "translation": "\u062a\u0631\u062c\u0645\u0647 2", "example": "\u0645\u062b\u0627\u0644 2"},
        ]

        def _fake_ai_call(*args, **kwargs):
            return fake_cards

        self._ai_patcher.stop()
        with patch("services.srs_engine._call_ai_limited", side_effect=_fake_ai_call):
            with patch("services.srs_engine.ai.validate_card", side_effect=lambda d: d):
                session = await generate_v3_session(1, "en", "general", "beginner", "free")

        self.assertEqual(len(session["nodes"]), 1 + len(fake_cards))
        self.assertEqual(session["nodes"][0].source_tier, 1)
        self.assertEqual(session["nodes"][0].card_data["word"], "saved_word")
        self.assertEqual(session["nodes"][1].source_tier, 3)
        self.assertEqual(session["nodes"][1].card_data["word"], "ai_word1")
        self.assertEqual(session["nodes"][2].source_tier, 3)
        self.assertEqual(session["nodes"][2].card_data["word"], "ai_word2")
