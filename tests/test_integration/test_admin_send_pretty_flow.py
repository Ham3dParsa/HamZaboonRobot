"""Integration tests for RT-ADMIN: migrate 11 reply_text sites onto send_pretty seam."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminSendPrettyFlowTest(unittest.TestCase):
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

    def _make_update(self, text: str = "hello"):
        msg = MagicMock()
        msg.text = text
        msg.reply_text = AsyncMock()
        msg.reply_document = AsyncMock()
        update = MagicMock()
        update.message = msg
        update.effective_message = msg
        update.effective_user = MagicMock()
        update.effective_user.id = 999
        update.effective_chat = MagicMock()
        update.effective_chat.id = 999
        update.callback_query = None
        return update

    def _make_ctx(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_open_admin_panel_uses_say_plain(self):
        from handlers.admin import open_admin_panel

        update = self._make_update()
        ctx = self._make_ctx()
        # owner check -> mock is_owner True
        with patch("handlers.admin.is_owner", return_value=True):
            with patch("handlers.admin.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(open_admin_panel(update, ctx))
                mock_say.assert_called_once()
                args, kwargs = mock_say.call_args
                # args: update, context, text
                self.assertEqual(args[0], update)
                self.assertEqual(args[1], ctx)
                self.assertIn("پنل مدیریت", args[2])
                from services.send_pretty import RawFormat

                self.assertEqual(kwargs.get("raw"), RawFormat.PLAIN)
                self.assertEqual(kwargs.get("mode"), "send")
                self.assertIn("keyboard", kwargs)

    def test_access_denied_uses_say(self):
        from handlers.admin_backup import cmd_backup

        update = self._make_update()
        ctx = self._make_ctx()
        with patch("handlers.admin_backup.is_owner", return_value=False):
            with patch("handlers.admin_backup.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(cmd_backup(update, ctx))
                mock_say.assert_called_once()
                args, kwargs = mock_say.call_args
                self.assertIn("فقط مالک", args[2])
                from services.send_pretty import RawFormat

                self.assertEqual(kwargs.get("raw"), RawFormat.PLAIN)
                self.assertEqual(kwargs.get("mode"), "send")

    def test_backup_error_uses_say_plain_dynamic(self):
        from handlers.admin_backup import cmd_backup

        update = self._make_update()
        ctx = self._make_ctx()
        with patch("handlers.admin_backup.is_owner", return_value=True):
            with patch("handlers.admin_backup.db.export_db_bytes", side_effect=RuntimeError("boom")):
                with patch("handlers.admin_backup.say", new=AsyncMock(return_value="sent")) as mock_say:
                    asyncio.run(cmd_backup(update, ctx))
                    mock_say.assert_called_once()
                    args, kwargs = mock_say.call_args
                    self.assertIn("خطا در تهیه پشتیبان", args[2])
                    self.assertIn("boom", args[2])
                    from services.send_pretty import RawFormat

                    self.assertEqual(kwargs.get("raw"), RawFormat.PLAIN)
                    self.assertEqual(kwargs.get("mode"), "send")

    def test_restore_error_uses_say_plain(self):
        from handlers.admin_backup import handle_restore_doc

        update = self._make_update()
        # simulate large file error path
        doc = MagicMock()
        doc.file_size = 999999999
        doc.get_file = AsyncMock()
        update.effective_message.document = doc
        update.message = update.effective_message
        ctx = self._make_ctx()
        ctx.user_data["awaiting"] = "admin_restore"
        with patch("handlers.admin_backup.is_owner", return_value=True):
            with patch("handlers.admin_backup.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(handle_restore_doc(update, ctx))
                mock_say.assert_called_once()
                args, kwargs = mock_say.call_args
                self.assertIn("خطا در بازگردانی", args[2])
                from services.send_pretty import RawFormat

                self.assertEqual(kwargs.get("raw"), RawFormat.PLAIN)
                self.assertEqual(kwargs.get("mode"), "send")

    def test_cmd_restore_uses_say_with_keyboard(self):
        from handlers.admin_backup import cmd_restore

        update = self._make_update()
        ctx = self._make_ctx()
        with patch("handlers.admin_backup.is_owner", return_value=True):
            with patch("handlers.admin_backup.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(cmd_restore(update, ctx))
                mock_say.assert_called_once()
                args, kwargs = mock_say.call_args
                self.assertIn("فایل دیتابیس", args[2])
                from services.send_pretty import RawFormat

                self.assertEqual(kwargs.get("raw"), RawFormat.PLAIN)
                self.assertEqual(kwargs.get("mode"), "send")
                self.assertIn("keyboard", kwargs)

    def test_maintenance_msg_prompt_uses_say(self):
        # Also covers effective_message migration at line 265
        from handlers.admin import _handle_admin_callback

        # Build a callback-like update for maintenance:edit
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999
        update.effective_chat = MagicMock()
        update.effective_chat.id = 999
        update.callback_query = MagicMock()
        update.callback_query.data = "admin:maintenance:edit"
        update.callback_query.answer = AsyncMock()
        update.message = MagicMock()
        update.effective_message = MagicMock()
        ctx = self._make_ctx()
        with patch("handlers.admin.is_owner", return_value=True):
            with patch("handlers.admin.notify_callback", new=AsyncMock()):
                with patch("handlers.admin.say", new=AsyncMock(return_value="sent")) as mock_say:
                    asyncio.run(_handle_admin_callback(update, ctx, "maintenance:edit"))
                    mock_say.assert_called_once()
                    args, kwargs = mock_say.call_args
                    self.assertIn("متن پیام حالت تعمیر", args[2])
                    from services.send_pretty import RawFormat

                    self.assertEqual(kwargs.get("raw"), RawFormat.PLAIN)
                    self.assertEqual(kwargs.get("mode"), "send")
                    self.assertIn("keyboard", kwargs)

    def test_wiring_no_direct_reply_text(self):
        text = Path("handlers/admin.py").read_text(encoding="utf-8")
        self.assertNotIn("update.message.reply_text", text)
        self.assertNotIn("update.effective_message.reply_text", text)
        self.assertNotIn("context.bot.send_message", text)

    def test_raw_plain_count(self):
        text = Path("handlers/admin.py").read_text(encoding="utf-8")
        text += Path("handlers/admin_backup.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("raw=RawFormat.PLAIN"), 11)
        # also ensure at least 11 say calls with mode send
        self.assertGreaterEqual(text.count('mode="send"'), 11)


if __name__ == "__main__":
    unittest.main()
