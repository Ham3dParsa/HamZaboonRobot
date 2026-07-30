import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from telegram.error import Forbidden


class DbBlockedUserTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_set_user_blocked_updates_flag(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "conversation")
        db.set_user_level(1, "beginner")
        user = dict(db.get_user(1))
        self.assertEqual(user.get("bot_blocked"), 0)

        db.set_user_blocked(1)
        user = dict(db.get_user(1))
        self.assertEqual(user.get("bot_blocked"), 1)

    def test_reset_user_blocked_clears_flag(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_blocked(1)
        db.reset_user_blocked(1)
        user = dict(db.get_user(1))
        self.assertEqual(user.get("bot_blocked"), 0)

    def test_all_active_users_skips_blocked(self):
        db.create_user_if_needed(1, "user_a")
        db.create_user_if_needed(2, "user_b")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1")
            conn.execute("UPDATE users SET bot_blocked=1 WHERE user_id=2")
            conn.commit()

        active = db.all_active_users()
        ids = {u["user_id"] for u in active}
        self.assertIn(1, ids)
        self.assertNotIn(2, ids)

    def test_all_active_users_returns_all_when_none_blocked(self):
        db.create_user_if_needed(1, "user_a")
        db.create_user_if_needed(2, "user_b")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1")
            conn.commit()

        active = db.all_active_users()
        self.assertEqual(len(active), 2)

    def test_migration_adds_bot_blocked_column(self):
        with db.get_conn() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        self.assertIn("bot_blocked", cols)

    def test_bot_blocked_defaults_to_zero(self):
        db.create_user_if_needed(99, "fresh_user")
        user = dict(db.get_user(99))
        self.assertEqual(user.get("bot_blocked"), 0)


class BotBlockedFlagOnForbiddenTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def test_send_with_retry_sets_blocked_and_raises_forbidden(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "conversation")
        db.set_user_level(1, "beginner")

        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=Forbidden("bot was blocked by the user"))

        from services.utils.helpers import _send_with_retry

        import asyncio
        with self.assertRaises(Forbidden):
            asyncio.run(_send_with_retry(bot, 1, "test"))

        user = dict(db.get_user(1))
        self.assertEqual(user.get("bot_blocked"), 1)

    def test_all_active_users_excludes_blocked_from_generation_pool(self):
        db.create_user_if_needed(1, "user_a")
        db.create_user_if_needed(2, "user_b")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1, target_lang='en', goal='conversation', level='beginner'")
            conn.execute("UPDATE users SET bot_blocked=1 WHERE user_id=2")
            conn.commit()

        active = db.all_active_users()
        ids = {u["user_id"] for u in active}
        self.assertIn(1, ids)
        self.assertNotIn(2, ids)
