"""Integration tests for RT-BN1 broadcast concurrency + re-entry guard (updated for preview flow)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import bot
from handlers import admin as admin_module
from config import BROADCAST_MAX_CONCURRENCY

from services import db
from services.db import schema as db_schema

REPORT_FMT = "پیام برای {n} کاربر ارسال شد."
REFUSAL_MSG = "یک ارسال همگانی در حال انجام است؛ کمی بعد دوباره تلاش کن."


class AdminBroadcastConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        db.create_user_if_needed(1, "owner")
        self.maintenance_patch = patch("bot._maintenance_blocked", new=AsyncMock(return_value=False))
        self.maintenance_patch.start()
        self.addCleanup(self.maintenance_patch.stop)
        self.offline_patch = patch.object(bot, "_telegram_offline", False)
        self.offline_patch.start()
        self.addCleanup(self.offline_patch.stop)

    def tearDown(self):
        admin_module._BROADCAST_RUNNING = False
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def _make_text_update(self, text: str, user_id: int = 1):
        upd = MagicMock()
        upd.effective_user.id = user_id
        upd.effective_chat.id = user_id
        upd.callback_query = None
        msg = MagicMock()
        msg.text = text
        msg.text_html = text
        msg.reply_text = AsyncMock()
        upd.message = msg
        upd.effective_message = msg
        return upd

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def _make_callback_update(self, data: str, user_id: int = 1):
        q = MagicMock()
        q.data = data
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        q.message = msg
        upd = MagicMock()
        upd.effective_user.id = user_id
        upd.effective_chat.id = user_id
        upd.callback_query = q
        upd.effective_message = msg
        return upd

    def test_broadcast_fans_out_within_cap_and_counts_successes(self):
        from bot import text_router
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "admin_broadcast"
        update = self._make_text_update("hello all")
        users = [{"user_id": i} for i in range(2, 52)]
        state = {"in_flight": 0, "max_in_flight": 0, "calls": []}

        async def _tracking_send(bot_ref, chat_id, text, *args, **kwargs):
            state["in_flight"] += 1
            state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
            state["calls"].append(chat_id)
            await asyncio.sleep(0.005)
            state["in_flight"] -= 1
            return MagicMock()

        with patch("services.db.all_active_users", return_value=users), patch(
            "handlers.admin._send_with_retry", new=AsyncMock(side_effect=_tracking_send)
        ) as send, patch("bot.is_owner", return_value=True), patch("handlers.admin.is_owner", return_value=True):
            asyncio.run(text_router(update, ctx))
            # preview created, no sends yet
            self.assertIn("pending_broadcast", ctx.user_data)
            self.assertEqual(len(state["calls"]), 0)
            # confirm
            cb = self._make_callback_update("admin:broadcast_confirm")
            asyncio.run(_handle_admin_callback(cb, ctx, "broadcast_confirm"))

        self.assertEqual(len(state["calls"]), 50, "every active user attempted")
        self.assertLessEqual(state["max_in_flight"], BROADCAST_MAX_CONCURRENCY)
        self.assertGreaterEqual(state["max_in_flight"], 1)
        self.assertEqual(send.await_count, 50)
        self.assertFalse(admin_module._BROADCAST_RUNNING)

    def test_broadcast_guard_reset_even_when_final_reply_fails(self):
        from bot import text_router
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "admin_broadcast"
        update = self._make_text_update("hello all")
        users = [{"user_id": i} for i in range(2, 6)]
        with patch("services.db.all_active_users", return_value=users), patch(
            "handlers.admin._send_with_retry", new_callable=AsyncMock
        ), patch("bot.is_owner", return_value=True), patch("handlers.admin.is_owner", return_value=True):
            asyncio.run(text_router(update, ctx))
            cb = self._make_callback_update("admin:broadcast_confirm")
            # make final say fail via patch
            with patch("handlers.admin.send_pretty.say", new=AsyncMock(side_effect=RuntimeError("reply failed"))):
                with self.assertRaises(RuntimeError):
                    asyncio.run(_handle_admin_callback(cb, ctx, "broadcast_confirm"))
        self.assertFalse(admin_module._BROADCAST_RUNNING)

    def test_second_broadcast_while_running_is_refused(self):
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "admin_broadcast"
        update = self._make_text_update("second message")
        with patch("handlers.admin._send_with_retry", new_callable=AsyncMock) as send, patch("bot.is_owner", return_value=True), patch.object(admin_module, "_BROADCAST_RUNNING", True):
            asyncio.run(text_router(update, ctx))
        send.assert_not_awaited()
        update.message.reply_text.assert_called_once()
        self.assertIn("در حال انجام است", update.message.reply_text.call_args[0][0])
        self.assertIsNone(ctx.user_data.get("awaiting"))
