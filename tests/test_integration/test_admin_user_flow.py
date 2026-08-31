"""Integration tests for admin user-management flow (issue #stats-users, Phase 4).

Scratch-DB isolated; owner-gated via handlers.admin.is_owner.
Covers admin:user menu, search/resolve, block/unblock, set-plan,
reset progress (confirm/cancel), direct message, and non-owner reject.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.flows import text_router
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

    def _cb(self, data: str, user_id: int = 1):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        msg = MagicMock()
        msg.reply_document = AsyncMock()
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_user.username = "owner"
        update.effective_chat.id = user_id
        update.callback_query = query
        update.effective_message = msg
        update.message = msg
        query.message = msg
        return update

    def _ctx(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        ctx.bot.send_message = AsyncMock()
        return ctx

    def _make_text_update(self, text: str, user_id: int = 1):
        msg = MagicMock()
        msg.text = text
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.message = msg
        update.effective_message = msg
        update.effective_user = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat = MagicMock()
        update.effective_chat.id = user_id
        update.callback_query = None
        return update

    def test_user_menu_opens(self):
        from handlers.admin import _handle_admin_callback

        update = self._cb("admin:user")
        ctx = self._ctx()
        asyncio.run(_handle_admin_callback(update, ctx, "user"))
        update.callback_query.edit_message_text.assert_called_once()
        args, kwargs = update.callback_query.edit_message_text.call_args
        text = args[0] if args else kwargs.get("text", "")
        self.assertIn("\u0645\u062f\u06cc\u0631\u06cc\u062a \u06a9\u0627\u0631\u0628\u0631", text)

    def test_search_resolves(self):
        # search resolves via text_router with admin_user_search
        update = self._make_text_update("42")
        ctx = self._ctx()
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say:
            asyncio.run(text_router(update, ctx, "admin_user_search", "42"))
            mock_say.assert_called()
            # profile card contains Persian header and user id
            found = False
            for call in mock_say.call_args_list:
                args = call[0]
                txt = args[2] if len(args) > 2 else ""
                if "\u067e\u0631\u0648\u0641\u0627\u06cc\u0644" in txt and ("42" in txt or "۴۲" in txt):
                    found = True
            self.assertTrue(found, "profile card not sent via say")

        # also resolves @username variant
        update2 = self._make_text_update("@alice")
        ctx2 = self._ctx()
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say2:
            asyncio.run(text_router(update2, ctx2, "admin_user_search", "@alice"))
            mock_say2.assert_called()

    def test_search_not_found_keeps_awaiting(self):
        update = self._make_text_update("9999")
        ctx = self._ctx()
        ctx.user_data["awaiting"] = "admin_user_search"
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say:
            asyncio.run(text_router(update, ctx, "admin_user_search", "9999"))
            mock_say.assert_called()
            # awaiting should be re-armed
            self.assertEqual(ctx.user_data.get("awaiting"), "admin_user_search")

    def test_block_and_unblock(self):
        from handlers.admin import _handle_admin_callback

        # block
        update = self._cb("admin:user:block:42")
        ctx = self._ctx()
        asyncio.run(_handle_admin_callback(update, ctx, "user:block:42"))
        row = db.get_user(42)
        self.assertEqual(row["bot_blocked"], 1)

        # unblock
        update2 = self._cb("admin:user:unblock:42")
        ctx2 = self._ctx()
        asyncio.run(_handle_admin_callback(update2, ctx2, "user:unblock:42"))
        row2 = db.get_user(42)
        self.assertEqual(row2["bot_blocked"], 0)

    def test_set_plan_flow(self):
        # via text_router admin_user_set_plan:42
        update = self._make_text_update("gold")
        ctx = self._ctx()
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say:
            asyncio.run(text_router(update, ctx, "admin_user_set_plan:42", "gold"))
            self.assertEqual(db.get_user(42)["plan"], "gold")
            mock_say.assert_called()
            # verify success message mentions plan change
            texts = [c[0][2] for c in mock_say.call_args_list if len(c[0]) > 2]
            combined = " ".join(texts)
            self.assertIn("gold", combined)

        # invalid plan keeps awaiting
        ctx2 = self._ctx()
        update2 = self._make_text_update("invalid_plan")
        with patch("handlers.admin_users.say", new=AsyncMock()):
            asyncio.run(text_router(update2, ctx2, "admin_user_set_plan:42", "invalid_plan"))
            self.assertEqual(ctx2.user_data.get("awaiting"), "admin_user_set_plan:42")

    def test_reset_progress_deletes(self):
        # seed learning data for bob
        db.add_saved_word(7, "hello", "en", {"word": "hello"})
        # create a review event directly via API if available
        try:
            from services.db import record_review_event
            # need word id
            with db.transaction() as conn:
                wid = conn.execute("SELECT id FROM saved_words WHERE user_id=7").fetchone()
                if wid:
                    record_review_event(7, wid["id"], "again")
        except Exception:
            pass
        # add streak to verify reset
        with db.transaction() as conn:
            conn.execute("UPDATE users SET streak=5 WHERE user_id=7")

        from handlers.admin import _handle_admin_callback

        # confirm reset
        update = self._cb("admin:user:reset_confirm:7")
        ctx = self._ctx()
        asyncio.run(_handle_admin_callback(update, ctx, "user:reset_confirm:7"))
        stats = db.get_user_learning_stats(7)
        self.assertEqual(stats["saved_words"], 0)
        self.assertEqual(stats["review_events"], 0)
        row = db.get_user(7)
        self.assertEqual(row["streak"], 0)

    def test_reset_cancel_keeps(self):
        db.add_saved_word(7, "world", "en", {"word": "world"})
        with db.transaction() as conn:
            conn.execute("UPDATE users SET streak=3 WHERE user_id=7")

        from handlers.admin import _handle_admin_callback

        update = self._cb("admin:user:reset_cancel:7")
        ctx = self._ctx()
        asyncio.run(_handle_admin_callback(update, ctx, "user:reset_cancel:7"))
        stats = db.get_user_learning_stats(7)
        self.assertGreaterEqual(stats["saved_words"], 1)
        row = db.get_user(7)
        self.assertEqual(row["streak"], 3)

    def test_message_flow(self):
        update = self._make_text_update("\u0633\u0644\u0627\u0645 \u0627\u0632 \u0645\u062f\u06cc\u0631")
        ctx = self._ctx()
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say:
            asyncio.run(text_router(update, ctx, "admin_user_message:42", "\u0633\u0644\u0627\u0645 \u0627\u0632 \u0645\u062f\u06cc\u0631"))
            ctx.bot.send_message.assert_called_once()
            call_kwargs = ctx.bot.send_message.call_args[1]
            self.assertEqual(call_kwargs.get("chat_id"), 42)
            self.assertIn("\u0633\u0644\u0627\u0645", call_kwargs.get("text", ""))
            mock_say.assert_called()
            texts = [c[0][2] for c in mock_say.call_args_list if len(c[0]) > 2]
            self.assertTrue(any("\u067e\u06cc\u0627\u0645 \u0627\u0631\u0633\u0627\u0644 \u0634\u062f" in t for t in texts))

    def test_message_flow_failure_keeps_awaiting(self):
        update = self._make_text_update("hello")
        ctx = self._ctx()
        ctx.bot.send_message = AsyncMock(side_effect=Exception("blocked"))
        ctx.user_data["awaiting"] = "admin_user_message:42"
        with patch("handlers.admin_users.say", new=AsyncMock()):
            asyncio.run(text_router(update, ctx, "admin_user_message:42", "hello"))
            # awaiting re-armed on failure
            self.assertEqual(ctx.user_data.get("awaiting"), "admin_user_message:42")

    def test_non_owner_rejected(self):
        from handlers.admin import _handle_admin_callback

        with patch("handlers.admin.is_owner", return_value=False):
            update = self._cb("admin:user", user_id=9999)
            ctx = self._ctx()
            asyncio.run(_handle_admin_callback(update, ctx, "user"))
            update.callback_query.answer.assert_called()
            args = update.callback_query.answer.call_args[0]
            self.assertIn("\u0641\u0642\u0637 \u0645\u0627\u0644\u06a9 \u0631\u0628\u0627\u062a", args[0])


if __name__ == "__main__":
    unittest.main()
