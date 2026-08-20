"""Integration tests for RT-BN1 broadcast concurrency + re-entry guard.

``handlers.admin._handle_admin_broadcast`` fans out to all active users. The
audit (BN1) found the send loop was fully sequential (one user at a time). RT-BN1
parallelizes it with ``asyncio.gather`` bounded by a broadcast-local
``asyncio.Semaphore(BROADCAST_MAX_CONCURRENCY)``, keeps per-user failure isolation
(log + skip, count successes), refuses a second concurrent broadcast via the
``_BROADCAST_RUNNING`` flag, and routes the final report through the ``say`` seam.

Integration tests drive the real ``bot.text_router`` end-to-end (simulating an
admin text message that lands on the ``admin_broadcast`` flow).
"""

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
    """Broadcast fan-out respects the concurrency cap and counts successes."""

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
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.callback_query = None
        update.message.text = text
        update.message.reply_text = AsyncMock()
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_broadcast_fans_out_within_cap_and_counts_successes(self):
        """50 users: sends run concurrently (max in-flight <= cap), all attempted,
        success count reported, guard reset after."""
        from bot import text_router

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
        ) as send, patch("bot.is_owner", return_value=True):
            asyncio.run(text_router(update, ctx))

        self.assertEqual(len(state["calls"]), 50, "every active user attempted")
        self.assertLessEqual(state["max_in_flight"], BROADCAST_MAX_CONCURRENCY,
                             "in-flight sends must not exceed the cap")
        self.assertGreaterEqual(state["max_in_flight"], 2,
                                "sends actually ran concurrently (not sequential)")
        self.assertEqual(send.await_count, 50)
        update.message.reply_text.assert_called_once_with(REPORT_FMT.format(n=50))
        self.assertIsNone(ctx.user_data.get("awaiting"))
        self.assertFalse(admin_module._BROADCAST_RUNNING, "guard reset after broadcast")

    def test_broadcast_guard_reset_even_when_final_reply_fails(self):
        """If the final report fails, the guard is still released (no permanent lockout)."""
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "admin_broadcast"
        update = self._make_text_update("hello all")
        update.message.reply_text = AsyncMock(side_effect=RuntimeError("reply failed"))
        users = [{"user_id": i} for i in range(2, 6)]

        with patch("services.db.all_active_users", return_value=users), patch(
            "handlers.admin._send_with_retry", new_callable=AsyncMock
        ), patch("bot.is_owner", return_value=True):
            with self.assertRaises(RuntimeError):
                asyncio.run(text_router(update, ctx))

        self.assertFalse(admin_module._BROADCAST_RUNNING, "guard released on report failure")

    def test_second_broadcast_while_running_is_refused(self):
        """A second broadcast while one is in-flight is politely refused and not sent."""
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "admin_broadcast"
        update = self._make_text_update("second message")
        users = [{"user_id": 2}]

        with patch("services.db.all_active_users", return_value=users), patch(
            "handlers.admin._send_with_retry", new_callable=AsyncMock
        ) as send, patch("bot.is_owner", return_value=True), patch.object(
            admin_module, "_BROADCAST_RUNNING", True
        ):
            asyncio.run(text_router(update, ctx))

        send.assert_not_awaited()
        update.message.reply_text.assert_called_once_with(REFUSAL_MSG)
        self.assertIsNone(ctx.user_data.get("awaiting"), "refusal consumes the awaiting flow")