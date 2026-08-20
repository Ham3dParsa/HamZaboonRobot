"""Integration tests for early-awaiting-reset rollback (RT-B5).

``bot.text_router`` clears ``context.user_data["awaiting"]`` BEFORE dispatching
to a handler. If the handler raises before re-arming awaiting, the state would
be lost forever. This change wraps dispatch in a rollback guard (B5).

Unit tests exercise ``bot._dispatch_awaiting`` directly (rollback semantics);
integration tests exercise the real ``bot.text_router`` end-to-end.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import bot

from handlers.flows import AWAITING_PENDING_KEY, mark_awaiting_consumed

from services import db
from services.db import schema as db_schema


class EarlyAwaitingResetTest(unittest.TestCase):
    """awaiting survives a handler exception that never re-arms it."""

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
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def _make_text_update(self, text: str, user_id: int = 1):
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.message.text = text
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    # ---- unit tests: _dispatch_awaiting rollback semantics -----------------

    def test_dispatch_exception_before_rearm_restores_awaiting(self):
        """Handler raises without touching awaiting -> previous value restored."""
        from bot import _dispatch_awaiting

        ctx = self._make_context()
        ctx.user_data["awaiting"] = None  # caller pre-clears before dispatch
        update = self._make_text_update("hello")

        with patch("bot._process_ask_word", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                asyncio.run(_dispatch_awaiting(update, ctx, "ask_word", "hello", 1))

        self.assertEqual(ctx.user_data["awaiting"], "ask_word")

    def test_dispatch_exception_after_rearm_keeps_new_value(self):
        """Handler re-arms awaiting then raises -> new value kept, not rolled back."""
        from bot import _dispatch_awaiting

        ctx = self._make_context()
        ctx.user_data["awaiting"] = None  # caller pre-clears before dispatch
        update = self._make_text_update("hello")

        async def throw_after_rearm(update, context, user_id, row, text):
            context.user_data["awaiting"] = "a_new_flow"
            raise RuntimeError("boom")

        with patch("bot._process_ask_word", side_effect=throw_after_rearm):
            with self.assertRaises(RuntimeError):
                asyncio.run(_dispatch_awaiting(update, ctx, "ask_word", "hello", 1))

        self.assertEqual(ctx.user_data["awaiting"], "a_new_flow")

    def test_dispatch_admin_flow_exception_restores_awaiting(self):
        """Admin flow handler raising without re-arming -> awaiting restored."""
        from bot import _dispatch_awaiting

        ctx = self._make_context()
        ctx.user_data["awaiting"] = None  # caller pre-clears before dispatch
        update = self._make_text_update("hi")

        with patch("bot.flows_text_router", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                asyncio.run(_dispatch_awaiting(update, ctx, "admin_broadcast", "hi", 1))

        self.assertEqual(ctx.user_data["awaiting"], "admin_broadcast")

    def test_dispatch_success_leaves_awaiting_unchanged(self):
        """Success path leaves awaiting exactly as the caller pre-set it."""
        from bot import _dispatch_awaiting

        ctx = self._make_context()
        ctx.user_data["awaiting"] = None  # caller pre-clears before dispatch
        update = self._make_text_update("hello")

        with patch("bot._process_ask_word", new_callable=AsyncMock):
            asyncio.run(_dispatch_awaiting(update, ctx, "ask_word", "hello", 1))

        self.assertIsNone(ctx.user_data["awaiting"])

    def test_dispatch_unknown_awaiting_returns_false(self):
        """An unknown/stale awaiting value is not dispatched (caller falls through)."""
        from bot import _dispatch_awaiting

        ctx = self._make_context()
        ctx.user_data["awaiting"] = None
        update = self._make_text_update("hello")

        result = asyncio.run(_dispatch_awaiting(update, ctx, "stale_unknown_flow", "hello", 1))

        self.assertIs(result, False)

    def test_dispatch_exception_after_consumed_no_rollback(self):
        """Handler that consumed the input (cleared marker) then raised -> no rollback."""
        from bot import _dispatch_awaiting

        ctx = self._make_context()
        ctx.user_data["awaiting"] = None  # caller pre-clears before dispatch
        update = self._make_text_update("hello")

        async def consume_then_throw(update, context, user_id, row, text):
            mark_awaiting_consumed(context)
            raise RuntimeError("boom")

        with patch("bot._process_ask_word", side_effect=consume_then_throw):
            with self.assertRaises(RuntimeError):
                asyncio.run(_dispatch_awaiting(update, ctx, "ask_word", "hello", 1))

        self.assertIsNone(ctx.user_data["awaiting"])

    # ---- integration tests: bot.text_router end-to-end ---------------------

    def test_text_router_exception_before_rearm_restores_awaiting(self):
        """Real text_router keeps awaiting when the handler throws first."""
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "ask_word"
        update = self._make_text_update("hello")

        with patch("bot._process_ask_word", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                asyncio.run(text_router(update, ctx))

        self.assertEqual(ctx.user_data["awaiting"], "ask_word")

    def test_text_router_exception_after_rearm_keeps_new_value(self):
        """Real text_router keeps the re-armed value when the handler then throws."""
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "ask_word"
        update = self._make_text_update("hello")

        async def throw_after_rearm(update, context, user_id, row, text):
            context.user_data["awaiting"] = "a_new_flow"
            raise RuntimeError("boom")

        with patch("bot._process_ask_word", side_effect=throw_after_rearm):
            with self.assertRaises(RuntimeError):
                asyncio.run(text_router(update, ctx))

        self.assertEqual(ctx.user_data["awaiting"], "a_new_flow")

    def test_text_router_exception_after_consumed_no_rollback(self):
        """Real text_router does not re-arm a flow whose input was consumed."""
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "ask_word"
        update = self._make_text_update("hello")

        async def consume_then_throw(update, context, user_id, row, text):
            mark_awaiting_consumed(context)
            raise RuntimeError("boom")

        with patch("bot._process_ask_word", side_effect=consume_then_throw):
            with self.assertRaises(RuntimeError):
                asyncio.run(text_router(update, ctx))

        self.assertIsNone(ctx.user_data["awaiting"])

    def test_text_router_set_plan_consumed_no_rollback(self):
        """Real set_plan flow: write succeeds, final reply fails -> no re-arm."""
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "admin_set_plan"
        update = self._make_text_update("1 silver")
        update.message.reply_text = AsyncMock(side_effect=RuntimeError("send failed"))

        with patch("bot.is_owner", return_value=True):
            with self.assertRaises(RuntimeError):
                asyncio.run(text_router(update, ctx))

        self.assertIsNone(ctx.user_data["awaiting"])
        self.assertEqual(db.get_user(1)["plan"], "silver")

    def test_text_router_success_clears_awaiting(self):
        """Real text_router clears awaiting on a successful dispatch."""
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "ask_word"
        update = self._make_text_update("hello")

        with patch("bot._process_ask_word", new_callable=AsyncMock):
            asyncio.run(text_router(update, ctx))

        self.assertIsNone(ctx.user_data["awaiting"])

    def test_text_router_broadcast_consumed_no_rollback(self):
        """Real broadcast flow: messages sent, final reply fails -> no re-arm/re-send."""
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "admin_broadcast"
        update = self._make_text_update("hello all")
        update.message.reply_text = AsyncMock(side_effect=RuntimeError("send failed"))
        users = [{"user_id": 2}, {"user_id": 3}]

        with patch("services.db.all_active_users", return_value=users), patch(
            "handlers.admin._send_with_retry", new_callable=AsyncMock
        ) as send, patch("bot.is_owner", return_value=True):
            with self.assertRaises(RuntimeError):
                asyncio.run(text_router(update, ctx))

        self.assertIsNone(ctx.user_data["awaiting"])
        self.assertEqual(send.await_count, 2)

    def test_text_router_unknown_awaiting_falls_through_to_menu(self):
        """Stale/unknown awaiting falls through to the main-menu reply, no marker left."""
        from bot import text_router

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "stale_unknown_flow"
        update = self._make_text_update("hello")

        with patch("bot.is_owner", return_value=True):
            asyncio.run(text_router(update, ctx))

        ctx.bot.send_message.assert_called()
        self.assertNotIn(AWAITING_PENDING_KEY, ctx.user_data)