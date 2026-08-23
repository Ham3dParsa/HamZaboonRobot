"""Integration tests for RT-COST: admin_cost reply_text -> send_pretty.

Verifies all 4 outbound sites route through services.send_pretty.say
with raw=PLAIN, correct keyboard and mode.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminCostSendPrettyFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_message_update(self, text: str = "hello"):
        msg = MagicMock()
        msg.text = text
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.message = msg
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        update.callback_query = None
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_dashboard_without_callback_uses_say_auto(self):
        from handlers.admin_cost import _show_llm_cost_dashboard

        update = self._make_message_update()
        ctx = self._make_context()
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_show_llm_cost_dashboard(update, ctx))
            mock_say.assert_called_once()
            _, kwargs = mock_say.call_args
            # Explicit checks per contract Rule 2/3/4
            from services.send_pretty import RawFormat

            self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
            self.assertEqual(kwargs["mode"], "auto")
            self.assertIn("keyboard", kwargs)

    def test_user_not_found_uses_say_send(self):
        from handlers.admin_cost import _handle_cost_text_input

        update = self._make_message_update("unknown_user_12345")
        ctx = self._make_context()
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_cost_text_input(update, ctx, "llm_cost_user", "unknown_user_12345"))
            mock_say.assert_called_once()
            args, kwargs = mock_say.call_args
            self.assertIn("User not found", args[2])
            from services.send_pretty import RawFormat

            self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
            self.assertEqual(kwargs["mode"], "send")
            self.assertIn("keyboard", kwargs)
            self.assertEqual(ctx.user_data["awaiting"], "llm_cost_user")

    def test_invalid_price_uses_say_send(self):
        from handlers.admin_cost import _handle_cost_text_input

        update = self._make_message_update("not_a_number")
        ctx = self._make_context()
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_cost_text_input(update, ctx, "llm_price_input", "not_a_number"))
            mock_say.assert_called_once()
            args, kwargs = mock_say.call_args
            self.assertIn("عدد معتبر", args[2])
            from services.send_pretty import RawFormat

            self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
            self.assertEqual(kwargs["mode"], "send")

    def test_pricing_text_success_uses_say_send(self):
        from handlers.admin_cost import _handle_cost_text_input

        update = self._make_message_update("0.12")
        ctx = self._make_context()
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_cost_text_input(update, ctx, "llm_price_input", "0.12"))
            mock_say.assert_called_once()
            args, kwargs = mock_say.call_args
            self.assertIn("LLM pricing defaults", args[2])
            from services.send_pretty import RawFormat

            self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
            self.assertEqual(kwargs["mode"], "send")

    def test_dashboard_with_callback_edits_via_edit_or_send(self):
        """Callback path still edits in place via _edit_or_send (not a second send)."""
        from handlers.admin_cost import _show_llm_cost_dashboard

        query = MagicMock()
        query.data = "admin:llm_costs"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.callback_query = query
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        ctx = self._make_context()
        # _edit_or_send is the seam for the callback branch; say must NOT be called there.
        with patch("handlers.admin_cost._edit_or_send", new=AsyncMock(return_value="edited")) as mock_edit:
            with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(_show_llm_cost_dashboard(update, ctx))
                mock_edit.assert_called_once()
                mock_say.assert_not_called()

    def test_wiring_no_direct_reply_text(self):
        text = Path("handlers/admin_cost.py").read_text(encoding="utf-8")
        self.assertNotIn("update.message.reply_text", text)
        self.assertNotIn("update.effective_message.reply_text", text)
        self.assertNotIn("context.bot.send_message", text)


if __name__ == "__main__":
    unittest.main()
