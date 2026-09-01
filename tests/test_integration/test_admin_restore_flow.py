import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.admin import auto_backup_job, cmd_backup, handle_restore_doc
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

    async def test_foreign_backup_reports_error_without_replacing_live_db(self):
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
        self.assertIn("فایل پشتیبان معتبر نیست", rendered)
        with open(self.live_path, "rb") as live_file:
            self.assertEqual(live_file.read(), original)
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    async def test_backup_sends_memory_snapshot(self):
        update = MagicMock()
        update.effective_user.id = 1
        update.message = MagicMock()
        context = MagicMock()
        context.bot.send_document = AsyncMock()

        with patch("handlers.admin.is_owner", return_value=True):
            await cmd_backup(update, context)

        document = context.bot.send_document.await_args.kwargs["document"]
        self.assertIsInstance(document, io.BytesIO)
        self.assertTrue(document.getvalue().startswith(b"SQLite format 3\x00"))

    async def test_auto_backup_runs_all_file_work_in_worker(self):
        context = MagicMock()
        context.bot.send_document = AsyncMock()
        original_to_thread = __import__("asyncio").to_thread

        async def run_in_worker(func, *args):
            return await original_to_thread(func, *args)

        worker = AsyncMock(side_effect=run_in_worker)

        with (
            patch("handlers.admin.DB_PATH", self.live_path),
            patch("handlers.admin.asyncio.to_thread", worker),
            patch("services.archive.asyncio.to_thread", worker),
        ):
            await auto_backup_job(context)

        # _create_auto_backup + export + build_backup_caption all run via to_thread (no blocking on event loop)
        self.assertGreaterEqual(worker.await_count, 2)
        called_funcs = [c.args[0].__name__ if hasattr(c.args[0], "__name__") else str(c.args[0]) for c in worker.await_args_list]
        self.assertTrue(any("build_backup_caption" in n for n in called_funcs), f"build_backup_caption not run in worker: {called_funcs}")

    async def test_auto_backup_skips_when_no_target(self):
        from services.archive import do_backup

        context = MagicMock()
        context.bot.send_document = AsyncMock()
        with patch("services.archive.resolved_archive_chat_id", return_value=None):
            result = await do_backup(context.bot, 0)
            self.assertIsNone(result)
            context.bot.send_document.assert_not_called()
        # auto_backup_job early-return when archive None and OWNER_ID==0
        context2 = MagicMock()
        context2.bot.send_document = AsyncMock()
        with (
            patch("services.archive.resolved_archive_chat_id", return_value=None),
            patch("handlers.admin.db.get_bool_setting", return_value=True),
            patch("config.OWNER_ID", 0),
        ):
            # need to ensure handlers.admin sees OWNER_ID==0 via imported alias _OID
            import handlers.admin as admin_mod
            orig_oid = admin_mod.__dict__.get("_OID", None)
            # auto_backup_job imports OWNER_ID inside function, so patching config.OWNER_ID suffices
            await admin_mod.auto_backup_job(context2)
            context2.bot.send_document.assert_not_called()

    def test_backup_restore_wiring(self):
        from services.routing import ROUTES
        from pathlib import Path

        registered = {p for (p, _, _) in ROUTES}
        self.assertIn("admin", registered)
        text = Path("handlers/admin.py").read_text(encoding="utf-8")
        self.assertIn("backup_restore", text)
        self.assertNotIn('action == "backup"', text)
        self.assertNotIn('action == "restore"', text)


if __name__ == "__main__":
    unittest.main()
