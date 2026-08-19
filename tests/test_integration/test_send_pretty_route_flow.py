"""Integration tests for the RT-B2 send_pretty transfer.

Verifies that the admin ``send_message`` bypass sites (broadcast prompt and
plan set prompt) now route through the ``send_pretty`` retry/slot seam rather
than calling ``context.bot.*`` directly. The tests patch the seam entry point
(``services.send_pretty._send_with_retry``) and assert it is reached with the
expected chat/text/parse-mode/keyboard — so a revert back to a direct
``context.bot.send_message`` call would leave the seam un-patrolled and fail,
and the real ``_reset_telegram_cb``/circuit-breaker side effects never run
(hermetic). The SRS (seam #6) and study (seam #5) edit paths are covered by
the existing delete-card / study-session flow tests.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class SendPrettyRouteFlowTest(unittest.TestCase):
    """Admin prompt sends routed through the send_pretty seam."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_callback_update(self, data: str, user_id: int = 1):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.callback_query = query
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        return ctx

    def _drive(self, action: str):
        """Drive the admin callback action and return the seam's awaited call."""
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update(f"admin:{action}")
        ctx = self._make_context()
        with patch(
            "services.send_pretty._send_with_retry",
            new=AsyncMock(return_value="sent"),
        ) as seam:
            asyncio.run(_handle_admin_callback(update, ctx, action))
        self.assertEqual(seam.call_count, 1, f"expected one seam send for {action}")
        return ctx, seam.call_args

    def test_broadcast_prompt_routes_through_send_seam(self):
        """admin:broadcast must send its prompt via the seam (never
        ``context.bot.send_message``) and arm the awaiting flow."""
        ctx, (args, kwargs) = self._drive("broadcast")

        self.assertEqual(ctx.user_data["awaiting"], "admin_broadcast")
        self.assertIs(args[0], ctx.bot)
        self.assertEqual(args[1], 1)
        self.assertEqual(args[2], "متن پیام همگانی رو بفرست:")
        self.assertIn("reply_markup", kwargs)
        # The prompt is plain text (no parse mode) — exact prior behavior.
        self.assertNotIn("parse_mode", kwargs)

    def test_set_plan_prompt_routes_through_send_seam(self):
        """admin:set_plan must send its MarkdownV2 prompt via the seam."""
        ctx, (args, kwargs) = self._drive("set_plan")

        self.assertEqual(ctx.user_data["awaiting"], "admin_set_plan")
        self.assertIs(args[0], ctx.bot)
        self.assertIn("فرمت را ارسال کنید", args[2])
        self.assertEqual(kwargs["parse_mode"], "MarkdownV2")
        self.assertIn("reply_markup", kwargs)


if __name__ == "__main__":
    unittest.main()