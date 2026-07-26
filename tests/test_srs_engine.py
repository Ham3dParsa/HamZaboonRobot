import unittest
import os
import tempfile
from unittest.mock import patch
from services import db
from services.srs_engine import generate_v3_session


class GenerateV3SessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db.init_db()
        db.create_user_if_needed(1, "test_user")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        self.tempdir.cleanup()

    async def test_tier1_due_words_are_selected_first(self):
        db.add_saved_word(1, "due_word", "en", {
            "word": "due_word",
            "fa_meaning": "معنی",
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
            "fa_meaning": "معنی",
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
                    "fa_meaning": "معنی",
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
            "fa_meaning": "معنی",
        })
        db.add_saved_word(1, "due_first", "en", {
            "word": "due_first",
            "fa_meaning": "معنی",
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
