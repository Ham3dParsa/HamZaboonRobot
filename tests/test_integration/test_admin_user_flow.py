"""Integration tests for the admin user-management flow (issue #stats-users).

Covers the ``admin:user*`` callback sub-tree and the two awaiting flows
(``admin_user_search`` and ``admin_user_set_plan:``) through the real
``_handle_admin_callback`` dispatch. Uses an isolated scratch DB.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminUserFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(42, "alice")
        db.create_user_if_needed(7, "bob")
        db.set_plan(42, "silver")
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _cb(self, data: str):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        msg = MagicMock()
        msg.reply_document = AsyncMock()
        msg.reply_text = AsyncMock()
        query.message = msg
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        return update

    def _ctx(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def _run(self, data: str, action: str):
        from handlers.admin import _handle_admin_callback

        update = self._cb(data)
        ctx = self._ctx()
        asyncio.run(_handle_admin_callback(update, ctx, action))
        return update, ctx

    def test_user_menu_opens(self):
        update, _ = self._run("admin:user", "user")
        update.callback_query.edit_message_text.assert_called_once()

    def test_search_resolves_profile_via_callback(self):
        update, ctx = self._run("admin:user:search", "user:search")
        # search arms awaiting; simulate the text flow
        self.assertEqual(ctx.user_data["awaiting"], "admin_user_search")
        from handlers.flows import text_router

        msg_update = MagicMock()
        msg_update.effective_user.id = 1
        msg_update.effective_chat.id = 42
        msg_update.message = MagicMock()
        msg_update.message.text = "42"
        msg_update.message.reply_text = AsyncMock()
        msg_update.effective_message = msg_update.message
        msg_ctx = self._ctx()
        asyncio.run(text_router(msg_update, msg_ctx, "admin_user_search", "42"))
        self.assertIsNone(msg_ctx.user_data.get("awaiting"))
        # profile message delivered
        self.assertTrue(
            msg_ctx.bot.send_message.called or msg_update.message.reply_text.called
        )

    def test_block_and_unblock(self):
        self._run("admin:user:block:42", "user:block:42")
        self.assertTrue(db.get_user(42)["bot_blocked"])
        self._run("admin:user:unblock:42", "user:unblock:42")
        self.assertFalse(db.get_user(42)["bot_blocked"])

    def test_set_plan_flow(self):
        from handlers.flows import text_router

        msg_update = MagicMock()
        msg_update.effective_user.id = 1
        msg_update.effective_chat.id = 42
        msg_update.message = MagicMock()
        msg_update.message.text = "gold"
        msg_update.message.reply_text = AsyncMock()
        msg_update.effective_message = msg_update.message
        msg_ctx = self._ctx()
        asyncio.run(
            text_router(msg_update, msg_ctx, "admin_user_set_plan:42", "gold")
        )
        self.assertEqual(db.get_user(42)["plan"], "gold")

    def test_reset_progress_deletes_data(self):
        db.count_review_events_total()  # ensure tables exist
        # seed some progress for user 42
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word) "
                "VALUES (42, 'cat', 'en', 'cat')"
            )
        self._run("admin:user:reset:42", "user:reset:42")
        # confirm step
        self._run("admin:user:reset_confirm:42", "user:reset_confirm:42")
        self.assertEqual(db.get_user_learning_stats(42)["saved_words"], 0)
        self.assertEqual(db.get_user(42)["streak"], 0)

    def test_reset_cancel_keeps_data(self):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word) "
                "VALUES (42, 'dog', 'en', 'dog')"
            )
        self._run("admin:user:reset:42", "user:reset:42")
        self._run("admin:user:reset_cancel:42", "user:reset_cancel:42")
        self.assertEqual(db.get_user_learning_stats(42)["saved_words"], 1)


if __name__ == "__main__":
    unittest.main()
