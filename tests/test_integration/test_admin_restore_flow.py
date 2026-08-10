import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.admin import cmd_backup, handle_restore_doc
from services import db
from services.db import schema as db_schema


class AdminRestoreFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.live_path = os.path.join(self.tempdir.name, "live.sqlite")
        db.DB_PATH = self.live_path
        db_schema.DB_PATH = self.live_path
        db.init_db()
        db.set_setting("restore_sentinel", "live")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    async def test_pre_fsrs_backup_reports_error_without_replacing_live_db(self):
        backup_path = os.path.join(self.tempdir.name, "old-backup.sqlite")
        with closing(sqlite3.connect(backup_path)) as conn:
            with conn:
                conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        with open(backup_path, "rb") as backup_file:
            backup = bytearray(backup_file.read())
        with open(self.live_path, "rb") as live_file:
            original = live_file.read()

        telegram_file = MagicMock()
        telegram_file.download_as_bytearray = AsyncMock(return_value=backup)
        document = MagicMock()
        document.get_file = AsyncMock(return_value=telegram_file)
        message = MagicMock()
        message.document = document
        message.reply_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_message = message
        update.message = message
        context = MagicMock()
        context.user_data = {"awaiting": "admin_restore"}

        with (
            patch("handlers.admin.is_owner", return_value=True),
            patch("handlers.admin.DB_PATH", self.live_path),
        ):
            await handle_restore_doc(update, context)

        rendered = message.reply_text.await_args.args[0]
        self.assertIn("خطا در بازگردانی", rendered)
        self.assertIn("نسخه پشتیبان قدیمی", rendered)
        with open(self.live_path, "rb") as live_file:
            self.assertEqual(live_file.read(), original)
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    async def test_backup_sends_memory_snapshot(self):
        message = MagicMock()
        message.reply_document = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.message = message
        context = MagicMock()

        with patch("handlers.admin.is_owner", return_value=True):
            await cmd_backup(update, context)

        document = message.reply_document.await_args.kwargs["document"]
        self.assertIsInstance(document, io.BytesIO)
        self.assertTrue(document.getvalue().startswith(b"SQLite format 3\x00"))


if __name__ == "__main__":
    unittest.main()
