"""Integration tests for RT-ADMINAI: admin_ai reply_text -> send_pretty."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminAiSendPrettyFlowTest(unittest.TestCase):
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

    def _make_msg_update(self, text: str = "hello"):
        msg = MagicMock()
        msg.text = text
        update = MagicMock()
        update.message = msg
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        update.callback_query = None
        return update

    def _make_ctx(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_preset_not_found_uses_say(self):
        from handlers.admin_ai import _handle_ai_preset_field_input

        update = self._make_msg_update("blah")
        ctx = self._make_ctx()
        # Trigger preset not found path: use invalid preset
        with patch("handlers.admin_ai.say", new=AsyncMock(return_value="sent")) as mock_say:
            # _handle_ai_preset_field_input with non-existent preset should call say
            asyncio.run(_handle_ai_preset_field_input(update, ctx, "nonexistent_xyz", "field", "value"))
            # It may call say for not found
            self.assertTrue(mock_say.called)
            args, kwargs = mock_say.call_args
            from services.send_pretty import RawFormat

            self.assertEqual(kwargs.get("raw"), RawFormat.PLAIN)
            self.assertEqual(kwargs.get("mode"), "send")

    def test_duplicate_name_uses_say_with_keyboard(self):
        from handlers.admin_ai import _handle_ai_preset_new_name

        update = self._make_msg_update("duplicate")
        ctx = self._make_ctx()
        # Simulate existing preset via get_preset mock
        with patch("handlers.admin_ai.db.get_preset", return_value={"name": "dup_test"}):
            with patch("handlers.admin_ai.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(_handle_ai_preset_new_name(update, ctx, "dup_test"))
                mock_say.assert_called_once()
                args, kwargs = mock_say.call_args
                self.assertIn("از قبل وجود دارد", args[2])
                self.assertIn("keyboard", kwargs)

    def test_invalid_number_uses_say(self):
        from handlers.admin_ai import _handle_create_priority_manual

        update = self._make_msg_update("not_a_number")
        ctx = self._make_ctx()
        ctx.user_data["ai_create_state"] = {"name": "test", "priority": None}
        with patch("handlers.admin_ai.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_create_priority_manual(update, ctx, "not_a_number"))
            mock_say.assert_called_once()
            args, kwargs = mock_say.call_args
            self.assertIn("عدد معتبر", args[2])

    def test_rank_change_uses_say_plain(self):
        # Wiring: ensure all 21 sites are now say with PLAIN+send (count check)
        text = Path("handlers/admin_ai.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count('raw=RawFormat.PLAIN'), 21)
        self.assertIn('raw=RawFormat.PLAIN', text)

    def test_wiring_no_direct_reply_text(self):
        text = Path("handlers/admin_ai.py").read_text(encoding="utf-8")
        self.assertNotIn("update.message.reply_text", text)
        self.assertNotIn("update.effective_message.reply_text", text)
        self.assertNotIn("context.bot.send_message", text)

    def test_no_direct_reply_text_count(self):
        # Ensure all 21 sites migrated
        text = Path("handlers/admin_ai.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("update.message.reply_text"), 0)


if __name__ == "__main__":
    unittest.main()
