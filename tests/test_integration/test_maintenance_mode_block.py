import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class MaintenanceBlockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.live_path = os.path.join(self.tempdir.name, "live.sqlite")
        db.DB_PATH = self.live_path
        db_schema.DB_PATH = self.live_path
        db.init_db()
        db.set_maintenance_mode(False)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def _update(self, user_id: int, text_mode: bool):
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = 100
        if text_mode:
            update.callback_query = None
        else:
            update.callback_query = MagicMock()
            update.callback_query.answer = AsyncMock()
        return update

    def _context(self):
        context = MagicMock()
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        return context

    async def test_owner_is_never_blocked(self):
        from bot import _maintenance_blocked

        db.set_maintenance_mode(True)
        update = self._update(user_id=1, text_mode=True)
        context = self._context()
        with patch("bot.is_owner", return_value=True):
            blocked = await _maintenance_blocked(update, context, text_mode=True)
        self.assertFalse(blocked)
        context.bot.send_message.assert_not_awaited()

    async def test_blocked_when_maintenance_off_returns_false(self):
        from bot import _maintenance_blocked

        update = self._update(user_id=2, text_mode=True)
        context = self._context()
        with patch("bot.is_owner", return_value=False):
            blocked = await _maintenance_blocked(update, context, text_mode=True)
        self.assertFalse(blocked)
        context.bot.send_message.assert_not_awaited()

    async def test_non_owner_blocked_in_text_mode_sends_canonical_message(self):
        from bot import _maintenance_blocked

        db.set_maintenance_mode(True)
        db.set_maintenance_message("")
        update = self._update(user_id=2, text_mode=True)
        context = self._context()
        with patch("bot.is_owner", return_value=False):
            blocked = await _maintenance_blocked(update, context, text_mode=True)
        self.assertTrue(blocked)
        context.bot.send_message.assert_awaited_once()
        sent = context.bot.send_message.await_args.kwargs.get("text")
        self.assertEqual(sent, db.DEFAULT_MAINTENANCE_MESSAGE)

    async def test_non_owner_blocked_in_text_mode_uses_custom_message(self):
        from bot import _maintenance_blocked

        db.set_maintenance_mode(True)
        db.set_maintenance_message("ربات در حال تعمیر است؛ فردا برمی‌گردیم.")
        update = self._update(user_id=2, text_mode=True)
        context = self._context()
        with patch("bot.is_owner", return_value=False):
            blocked = await _maintenance_blocked(update, context, text_mode=True)
        self.assertTrue(blocked)
        sent = context.bot.send_message.await_args.kwargs.get("text")
        self.assertEqual(sent, "ربات در حال تعمیر است؛ فردا برمی‌گردیم.")

    async def test_non_owner_blocked_in_callback_mode_answers_notice(self):
        from bot import _maintenance_blocked

        db.set_maintenance_mode(True)
        update = self._update(user_id=2, text_mode=False)
        context = self._context()
        with patch("bot.is_owner", return_value=False):
            blocked = await _maintenance_blocked(update, context, text_mode=False)
        self.assertTrue(blocked)
        update.callback_query.answer.assert_awaited_once()
        context.bot.send_message.assert_not_awaited()

    async def test_gated_command_skips_handler_when_maintenance_active(self):
        from bot import _maintenance_gated_command

        db.set_maintenance_mode(True)
        update = self._update(user_id=2, text_mode=True)
        context = self._context()
        handler = AsyncMock()
        with patch("bot.is_owner", return_value=False):
            await _maintenance_gated_command(handler, update, context)
        handler.assert_not_awaited()

    async def test_gated_command_runs_handler_when_maintenance_off(self):
        from bot import _maintenance_gated_command

        db.set_maintenance_mode(False)
        update = self._update(user_id=2, text_mode=True)
        context = self._context()
        handler = AsyncMock()
        with patch("bot.is_owner", return_value=False):
            await _maintenance_gated_command(handler, update, context)
        handler.assert_awaited_once()

    async def test_owner_unset_disables_maintenance_and_warns_when_active(self):
        # R7: when OWNER_ID==0 the kill-switch is intentionally a no-op
        from bot import _maintenance_blocked

        db.set_maintenance_mode(True)
        update = self._update(user_id=2, text_mode=True)
        context = self._context()
        with patch("bot.OWNER_ID", 0), patch("bot.log") as mock_log:
            blocked = await _maintenance_blocked(update, context, text_mode=True)
        self.assertFalse(blocked)
        context.bot.send_message.assert_not_awaited()
        update.callback_query = None  # text_mode already
        mock_log.warning.assert_called_once()
        self.assertIn("OWNER_ID==0", mock_log.warning.call_args[0][0])

    async def test_owner_unset_no_warning_when_inactive(self):
        from bot import _maintenance_blocked

        db.set_maintenance_mode(False)
        update = self._update(user_id=2, text_mode=True)
        context = self._context()
        with patch("bot.OWNER_ID", 0), patch("bot.log") as mock_log:
            blocked = await _maintenance_blocked(update, context, text_mode=True)
        self.assertFalse(blocked)
        mock_log.warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()