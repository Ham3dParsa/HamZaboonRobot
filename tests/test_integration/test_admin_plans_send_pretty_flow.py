"""Integration tests for RT-PLANS: admin_plans reply_text -> send_pretty.

Verifies all 6 outbound sites route through services.send_pretty.say
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


class AdminPlansSendPrettyFlowTest(unittest.TestCase):
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

    def test_wizard_input_plan_not_found_uses_say(self):
        from handlers.admin_plans import _handle_plan_wizard_input

        update = self._make_message_update()
        ctx = self._make_context()
        with patch("handlers.admin_plans.db.get_plan", return_value=None):
            with patch("handlers.admin_plans.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(_handle_plan_wizard_input(update, ctx, "gold", 0, "123"))
                mock_say.assert_called_once()
                args, kwargs = mock_say.call_args
                self.assertIn("پلن یافت نشد", args[2])
                from services.send_pretty import RawFormat

                self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
                self.assertEqual(kwargs["mode"], "send")
                self.assertNotIn("keyboard", kwargs)

    def test_wizard_input_expired_uses_say(self):
        from handlers.admin_plans import _handle_plan_wizard_input

        update = self._make_message_update()
        ctx = self._make_context()
        ctx.user_data["plan_full_edit"] = {"plan": "other", "field_idx": 0, "values": {}}
        with patch("handlers.admin_plans.db.get_plan", return_value={"name": "gold"}):
            with patch("handlers.admin_plans.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(_handle_plan_wizard_input(update, ctx, "gold", 0, "123"))
                mock_say.assert_called_once()
                args, kwargs = mock_say.call_args
                self.assertIn("ویزارد منقضی شده", args[2])
                from services.send_pretty import RawFormat

                self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
                self.assertEqual(kwargs["mode"], "send")

    def test_wizard_input_invalid_format_with_keyboard(self):
        from handlers.admin_plans import _handle_plan_wizard_input

        update = self._make_message_update()
        ctx = self._make_context()
        ctx.user_data["plan_full_edit"] = {"plan": "gold", "field_idx": 0, "values": {}}
        ctx.user_data["awaiting"] = "admin_plan_full_edit:gold:0"
        # Use a field that will fail validation; mock validate_value to return None
        with patch("handlers.admin_plans.db.get_plan", return_value={"name": "gold", "price": 1000}):
            with patch("handlers.admin_plans.plan_fields.validate_value", return_value=None):
                with patch("handlers.admin_plans.say", new=AsyncMock(return_value="sent")) as mock_say:
                    asyncio.run(_handle_plan_wizard_input(update, ctx, "gold", 0, "bad_value"))
                    mock_say.assert_called_once()
                    args, kwargs = mock_say.call_args
                    self.assertIn("فرمت نامعتبر", args[2])
                    from services.send_pretty import RawFormat

                    self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
                    self.assertEqual(kwargs["mode"], "send")
                    self.assertIn("keyboard", kwargs)
                    self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:gold:0")

    def test_plans_text_invalid_format_uses_say(self):
        from handlers.admin_plans import _handle_plans_text_input

        update = self._make_message_update("badformat")
        ctx = self._make_context()
        with patch("handlers.admin_plans.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_plans_text_input(update, ctx, "badformat"))
            mock_say.assert_called_once()
            args, kwargs = mock_say.call_args
            self.assertIn("فرمت نامعتبر", args[2])
            from services.send_pretty import RawFormat

            self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
            self.assertEqual(kwargs["mode"], "send")
            self.assertEqual(ctx.user_data["awaiting"], "admin_set_plan")

    def test_plans_text_user_not_found_uses_say(self):
        from handlers.admin_plans import _handle_plans_text_input

        update = self._make_message_update("unknown_user gold")
        ctx = self._make_context()
        with patch("handlers.admin_plans.db.find_user", return_value=None):
            with patch("handlers.admin_plans.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(_handle_plans_text_input(update, ctx, "unknown_user gold"))
                mock_say.assert_called_once()
                args, kwargs = mock_say.call_args
                self.assertIn("کاربر پیدا نشد", args[2])
                from services.send_pretty import RawFormat

                self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
                self.assertEqual(kwargs["mode"], "send")
                self.assertEqual(ctx.user_data["awaiting"], "admin_set_plan")

    def test_plans_text_success_uses_say(self):
        from handlers.admin_plans import _handle_plans_text_input

        update = self._make_message_update("1 gold")
        ctx = self._make_context()
        target = {"user_id": 1, "plan": "free"}
        with patch("handlers.admin_plans.db.find_user", return_value=target):
            with patch("handlers.admin_plans.db.get_plan", side_effect=lambda n: {"display_name": n} if n in ("free", "gold") else None):
                with patch("handlers.admin_plans.db.set_plan") as mock_set:
                    with patch("handlers.admin_plans.say", new=AsyncMock(return_value="sent")) as mock_say:
                        asyncio.run(_handle_plans_text_input(update, ctx, "1 gold"))
                        mock_say.assert_called_once()
                        args, kwargs = mock_say.call_args
                        self.assertIn("پلن کاربر", args[2])
                        from services.send_pretty import RawFormat

                        self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
                        self.assertEqual(kwargs["mode"], "send")
                        mock_set.assert_called_once_with(1, "gold")
                        self.assertNotIn("awaiting", ctx.user_data)

    def test_wiring_no_direct_reply_text(self):
        text = Path("handlers/admin_plans.py").read_text(encoding="utf-8")
        self.assertNotIn("update.message.reply_text", text)
        self.assertNotIn("update.effective_message.reply_text", text)
        self.assertNotIn("update.effective_message", text)
        self.assertNotIn("context.bot.send_message", text)
        self.assertGreaterEqual(text.count("raw=RawFormat.PLAIN"), 6)

    def test_wiring_say_import(self):
        text = Path("handlers/admin_plans.py").read_text(encoding="utf-8")
        self.assertIn("from services.send_pretty import RawFormat, say", text)


if __name__ == "__main__":
    unittest.main()
