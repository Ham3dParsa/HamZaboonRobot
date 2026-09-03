"""Integration tests for the admin backup seam (phase 02 archive-extract).

Covers routing ``admin:backup_restore*`` callbacks through the real
``_handle_admin_callback`` dispatch into
``handlers.admin_backup.handle_admin_backup_callback``. Uses an isolated
scratch DB; all Telegram I/O mocked.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminBackupFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
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
        msg = MagicMock()
        msg.reply_document = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.callback_query = query
        update.effective_message = msg
        update.message = msg
        query.message = msg
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_backup_menu_routed_to_admin_backup(self):
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update("admin:backup_restore")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "backup_restore"))
        update.callback_query.edit_message_text.assert_called_once()

    def test_trailing_colon_renders_menu(self):
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update("admin:backup_restore:")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "backup_restore:"))
        update.callback_query.edit_message_text.assert_called_once()

    def test_clear_archive_clears_stale_error(self):
        from handlers.admin import _handle_admin_callback

        db.set_setting("archive_chat_id", "-1001234567890")
        db.set_setting("archive_last_error", "stale boom")
        update = self._make_callback_update("admin:backup_restore:clear_archive")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "backup_restore:clear_archive"))
        self.assertEqual(db.get_setting("archive_chat_id", ""), "")
        self.assertEqual(db.get_setting("archive_last_error", ""), "")

    def test_valid_archive_set_clears_stale_error(self):
        from handlers.admin_backup import _handle_admin_archive_chat_id

        db.set_setting("archive_last_error", "stale boom")
        update = MagicMock()
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        update.effective_message = update.message
        ctx = MagicMock()
        ctx.user_data = {"awaiting": "admin_archive_chat_id"}
        ctx.bot = AsyncMock()
        asyncio.run(_handle_admin_archive_chat_id(update, ctx, "admin_archive_chat_id", "-1001234567890"))
        self.assertEqual(db.get_setting("archive_chat_id", ""), "-1001234567890")
        self.assertEqual(db.get_setting("archive_last_error", ""), "")

    def test_archive_set_invalid_persists_error_and_warns(self):
        from handlers.admin_backup import _handle_admin_archive_chat_id

        update = MagicMock()
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        update.effective_message = update.message
        ctx = MagicMock()
        ctx.user_data = {"awaiting": "admin_archive_chat_id"}
        ctx.bot = AsyncMock()
        asyncio.run(_handle_admin_archive_chat_id(update, ctx, "admin_archive_chat_id", "not-a-chat-id"))
        self.assertEqual(ctx.user_data.get("awaiting"), "admin_archive_chat_id")
        self.assertIn("invalid archive_chat_id", db.get_setting("archive_last_error", ""))
        update.message.reply_text.assert_called_once()
        rendered = update.message.reply_text.await_args.args[0]
        self.assertIn("نامعتبر", rendered)

    def test_resolved_archive_chat_id_is_pure(self):
        from services.archive import resolved_archive_chat_id

        db.set_setting("archive_chat_id", "bogus")
        db.set_setting("archive_last_error", "")
        self.assertIsNone(resolved_archive_chat_id())
        # Pure getter: no DB write side-effect on the error key.
        self.assertEqual(db.get_setting("archive_last_error", ""), "")

    def test_test_archive_validates_admin_rights(self):
        from handlers.admin import _handle_admin_callback

        db.set_setting("archive_chat_id", "-1001234567890")
        update = self._make_callback_update("admin:backup_restore:test_archive")
        ctx = self._make_context()
        with patch("services.archive.is_bot_admin", AsyncMock(return_value=False)):
            asyncio.run(_handle_admin_callback(update, ctx, "backup_restore:test_archive"))
        update.callback_query.answer.assert_called()
        texts = " ".join(str(c.args[0]) for c in update.callback_query.answer.await_args_list if c.args)
        self.assertIn("ادمین نیست", texts)

    def test_successful_backup_clears_stale_error(self):
        from services.archive import do_backup

        db.set_setting("archive_last_error", "stale boom")
        ctx_bot = AsyncMock()
        with patch("services.archive._send_media_with_retry", AsyncMock(return_value=None)):
            asyncio.run(do_backup(ctx_bot, 1, dest_chat_id=1))
        self.assertEqual(db.get_setting("archive_last_error", ""), "")

    def test_auto_backup_falls_back_to_owner_without_archive(self):
        import handlers.admin_backup as backup_mod

        db.set_setting("archive_chat_id", "")
        ctx = MagicMock()
        ctx.bot = AsyncMock()
        seen = {}

        async def fake_do_backup(bot, owner_id, dest=None):
            seen["owner_id"] = owner_id
            return owner_id

        with (
            patch("services.archive.do_backup", side_effect=fake_do_backup),
            patch.object(backup_mod, "_create_auto_backup", return_value=None),
            patch("config.OWNER_ID", 12345),
        ):
            asyncio.run(backup_mod.auto_backup_job(ctx))
        self.assertEqual(seen.get("owner_id"), 12345)


if __name__ == "__main__":
    unittest.main()
