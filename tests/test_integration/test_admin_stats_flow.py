"""Integration tests for the admin stats flow (Finding #7, task 7.5).

Covers routing admin:stats and admin:stats:* callbacks through the real
_handle_admin_callback dispatch into handlers.admin_stats.handle_admin_stats.
Uses an isolated scratch DB; no production data is touched.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminStatsFlowTest(unittest.TestCase):
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
        ctx.bot = AsyncMock()
        return ctx

    def test_stats_menu_routed_to_admin_stats(self):
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update("admin:stats")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "stats"))
        update.callback_query.edit_message_text.assert_called_once()

    def test_stats_overview_routed_to_admin_stats(self):
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update("admin:stats:overview")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "stats:overview"))
        update.callback_query.edit_message_text.assert_called_once()

    def test_stats_non_owner_rejected_before_dispatch(self):
        from handlers.admin import _handle_admin_callback

        with patch("handlers.admin.is_owner", return_value=False):
            update = self._make_callback_update("admin:stats", user_id=1234)
            ctx = self._make_context()
            asyncio.run(_handle_admin_callback(update, ctx, "stats"))
        answer = update.callback_query.answer.call_args
        self.assertIn("فقط مالک ربات", answer[0][0])


if __name__ == "__main__":
    unittest.main()
