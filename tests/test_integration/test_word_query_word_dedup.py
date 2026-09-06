"""Word-based dedup + alias + cap tests (Kilo warning fix)."""
import asyncio
import os
import tempfile
import unittest

os.environ["HAMZABAN_TEST_MODE"] = "1"
import services.db as db
from services.db import schema as db_schema
from services.word_query import ask


async def _fake_generate_shrub(**kwargs):
    return {"word": "shrub", "fa_meaning": "بوته", "phonetic": "/ʃrʌb/"}


class WordDedupIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        db.create_user_if_needed(1, username="t")
        with db.transaction() as conn:
            conn.execute(
                "UPDATE users SET target_lang=?, goal=?, level=?, onboarded=1, plan=? WHERE user_id=?",
                ("en", "general", "beginner", "free", 1),
            )

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def test_word_dedup_returns_duplicate_and_refunded(self):
        card = {"word": "shrub", "fa_meaning": "x"}
        tok1 = db.create_query_result(1, "بوته", "shrub", "en", card)
        before = db.get_user(1)["words_asked_today"] or 0
        result = asyncio.run(ask(1, "درختچه", generate_card=_fake_generate_shrub))
        self.assertEqual(result.kind, "duplicate")
        self.assertEqual(result.token, tok1)
        after = db.get_user(1)["words_asked_today"] or 0
        self.assertEqual(after, before)

    def test_alias_enables_pre_ai_hit(self):
        card = {"word": "shrub", "fa_meaning": "x"}
        db.create_query_result(1, "بوته", "shrub", "en", card)
        asyncio.run(ask(1, "درختچه", generate_card=_fake_generate_shrub))

        async def should_not_be_called(**kwargs):
            raise AssertionError("AI should not be called for alias hit")

        result = asyncio.run(ask(1, "درختچه", generate_card=should_not_be_called))
        self.assertEqual(result.kind, "duplicate")

    def test_lru_cap_evicts_oldest(self):
        for i in range(101):
            db.create_query_result(1, f"phrase{i}", f"word{i}", "en", {"word": f"word{i}"})
        with db.get_conn() as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) as c FROM query_results WHERE user_id=1 AND lang='en' AND expires_at>?", (db._utc_now().isoformat(),)
            ).fetchone()["c"]
        self.assertEqual(cnt, 100)
        self.assertIsNone(db.find_unexpired_query(1, "phrase0", "en"))
        self.assertIsNotNone(db.find_unexpired_query(1, "phrase100", "en"))

    def test_skip_duplicate_bypasses_word_dedup(self):
        card = {"word": "shrub", "fa_meaning": "x"}
        db.create_query_result(1, "بوته", "shrub", "en", card)
        result = asyncio.run(ask(1, "درختچه", generate_card=_fake_generate_shrub, skip_duplicate=True))
        self.assertEqual(result.kind, "ok")
