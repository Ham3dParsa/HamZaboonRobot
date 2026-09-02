"""R1-R4 hierarchical back tests for fix/admin-back-close."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminBackHierarchyTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new
        db_schema.DB_PATH = new
        db.init_db()
        try:
            db.create_user_if_needed(42, "alice", "Alice")
        except TypeError:
            db.create_user_if_needed(42, "alice")
            db.update_user_full_name(42, "Alice")
        try:
            db.create_user_if_needed(7, "bob", "Bob")
        except TypeError:
            db.create_user_if_needed(7, "bob")
            db.update_user_full_name(7, "Bob")
        self.p1 = patch("handlers.admin.is_owner", return_value=True)
        self.p1.start()
        self.addCleanup(self.p1.stop)
        self.p2 = patch("handlers.admin_users.is_owner", return_value=True)
        self.p2.start()
        self.addCleanup(self.p2.stop)

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _cb(self, data="admin:back"):
        q = MagicMock()
        q.data = data
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        msg.edit_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user.id = 1
        upd.effective_chat.id = 1
        upd.callback_query = q
        upd.effective_message = msg
        upd.message = msg
        q.message = msg
        return upd

    def _ctx(self, data=None):
        ctx = MagicMock()
        ctx.user_data = data if data is not None else {}
        ctx.bot = AsyncMock()
        ctx.bot.send_message = AsyncMock()
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        return ctx

    def test_r1_back_from_pending_dm_goes_to_profile(self):
        from handlers.admin import _handle_admin_callback

        ctx = self._ctx({"pending_dm": {"user_id": 42, "text": "hi", "html": "hi"}})
        upd = self._cb()
        with patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
             patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
            asyncio.run(_handle_admin_callback(upd, ctx, "back"))
            mock_show.assert_called_once()
            args, _ = mock_show.call_args
            # _show_profile(update, context, user_id)
            self.assertEqual(args[2], 42)
            self.assertNotIn("pending_dm", ctx.user_data)
            self.assertNotIn("awaiting", ctx.user_data)

    def test_r1_back_from_pending_plan_goes_to_profile(self):
        from handlers.admin import _handle_admin_callback

        ctx = self._ctx({"pending_plan": {"user_id": 7, "new_plan": "gold", "old_plan": "free"}})
        upd = self._cb()
        with patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
             patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
            asyncio.run(_handle_admin_callback(upd, ctx, "back"))
            mock_show.assert_called_once()
            self.assertEqual(mock_show.call_args[0][2], 7)

    def test_r1_back_from_pending_block_goes_to_profile(self):
        from handlers.admin import _handle_admin_callback

        ctx = self._ctx({"pending_block": {"user_id": 42}})
        upd = self._cb()
        with patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
             patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
            asyncio.run(_handle_admin_callback(upd, ctx, "back"))
            mock_show.assert_called_once()
            self.assertEqual(mock_show.call_args[0][2], 42)

    def test_r2_back_from_awaiting_message_goes_to_profile(self):
        from handlers.admin import _handle_admin_callback

        ctx = self._ctx({"awaiting": "admin_user_message:42"})
        upd = self._cb()
        with patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
             patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
            asyncio.run(_handle_admin_callback(upd, ctx, "back"))
            mock_show.assert_called_once()
            self.assertEqual(mock_show.call_args[0][2], 42)
            self.assertNotIn("awaiting", ctx.user_data)

    def test_r2_back_from_awaiting_set_plan_goes_to_profile(self):
        from handlers.admin import _handle_admin_callback

        ctx = self._ctx({"awaiting": "admin_user_set_plan:7"})
        upd = self._cb()
        with patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
             patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
            asyncio.run(_handle_admin_callback(upd, ctx, "back"))
            mock_show.assert_called_once()
            self.assertEqual(mock_show.call_args[0][2], 7)

    def test_r3_back_from_search_goes_to_root(self):
        from handlers.admin import _handle_admin_callback
        from config.keyboards.constants import BTN_ADMIN_USER_MANAGE

        ctx = self._ctx({"awaiting": "admin_user_search"})
        upd = self._cb()
        with patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
             patch("handlers.admin._edit_or_send", new=AsyncMock()) as mock_edit, \
             patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
            asyncio.run(_handle_admin_callback(upd, ctx, "back"))
            mock_show.assert_not_called()
            mock_edit.assert_called_once()
            args, kwargs = mock_edit.call_args
            text_arg = args[2] if len(args) > 2 else kwargs.get("text", "")
            self.assertEqual(text_arg, BTN_ADMIN_USER_MANAGE)

    def test_r4_last_id_fallback_when_pending_no_id(self):
        from handlers.admin import _handle_admin_callback

        # pending without user_id should fallback to admin_last_user_id
        ctx = self._ctx({"pending_dm": {"text": "hi"}, "admin_last_user_id": 42})
        upd = self._cb()
        with patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
             patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
            asyncio.run(_handle_admin_callback(upd, ctx, "back"))
            mock_show.assert_called_once()
            self.assertEqual(mock_show.call_args[0][2], 42)

    def test_r4_no_last_id_goes_to_root(self):
        from handlers.admin import _handle_admin_callback
        from config.keyboards.constants import BTN_ADMIN_USER_MANAGE

        ctx = self._ctx({"pending_dm": {"text": "hi"}})
        upd = self._cb()
        with patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
             patch("handlers.admin._edit_or_send", new=AsyncMock()) as mock_edit, \
             patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
            asyncio.run(_handle_admin_callback(upd, ctx, "back"))
            mock_show.assert_not_called()
            mock_edit.assert_called_once()
            args, kwargs = mock_edit.call_args
            text_arg = args[2] if len(args) > 2 else kwargs.get("text", "")
            self.assertEqual(text_arg, BTN_ADMIN_USER_MANAGE)

    def test_r4_profile_sets_last_id(self):
        from handlers.admin_users import _show_profile, _send_profile_message

        ctx = self._ctx()
        upd = self._cb("admin:user:profile:42")
        # patch say to avoid telegram
        with patch("handlers.admin_users.say", new=AsyncMock()):
            asyncio.run(_show_profile(upd, ctx, 42))
            self.assertEqual(ctx.user_data.get("admin_last_user_id"), 42)
        ctx2 = self._ctx()
        upd2 = self._cb()
        upd2.effective_user.id = 1
        upd2.effective_chat.id = 1
        # _send_profile_message also sets
        with patch("handlers.admin_users.say", new=AsyncMock()):
            asyncio.run(_send_profile_message(upd2, ctx2, 7))
            self.assertEqual(ctx2.user_data.get("admin_last_user_id"), 7)


if __name__ == "__main__":
    unittest.main()
