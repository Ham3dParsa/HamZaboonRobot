import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from services import db
from telegram.error import Forbidden


class BlockedUserSrsFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        self.tempdir.cleanup()

    def test_send_with_retry_sets_blocked_flag_on_forbidden(self):
        db.create_user_if_needed(1, "learner")
        user = dict(db.get_user(1))
        self.assertEqual(user.get("bot_blocked"), 0)

        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=Forbidden("bot was blocked by the user"))

        from services.utils.helpers import _send_with_retry

        with self.assertRaises(Forbidden):
            import asyncio
            asyncio.run(_send_with_retry(bot, 1, "test message"))

        user = dict(db.get_user(1))
        self.assertEqual(user.get("bot_blocked"), 1)

    def test_all_active_users_excludes_blocked(self):
        db.create_user_if_needed(1, "user_one")
        db.create_user_if_needed(2, "user_two")

        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1")
            conn.execute("UPDATE users SET bot_blocked=1 WHERE user_id=2")
            conn.commit()

        active = db.all_active_users()
        user_ids = [u["user_id"] for u in active]
        self.assertIn(1, user_ids)
        self.assertNotIn(2, user_ids)

    def test_reset_user_blocked_clears_flag(self):
        db.create_user_if_needed(1, "learner")
        db.set_user_blocked(1)
        self.assertEqual(dict(db.get_user(1)).get("bot_blocked"), 1)
        db.reset_user_blocked(1)
        self.assertEqual(dict(db.get_user(1)).get("bot_blocked"), 0)
