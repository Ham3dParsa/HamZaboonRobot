"""Integration tests for admin awaiting-state cleanup (R8/R9) and show_settings (R4/R7).

Dispatches real callbacks through ``_handle_admin_callback`` and asserts
``context.user_data`` state is properly cleaned up.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminAwaitingCleanupTest(unittest.TestCase):
    """admin:back must clear awaiting; admin:cancel must clear all state."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        db.create_user_if_needed(1, "owner")
        db.set_preset(name="custom_gpt", base_url="https://x", model="m", is_custom=1)
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
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

    def test_back_clears_awaiting(self):
        """Pressing back while awaiting=ai_fallback_rank:custom_gpt clears awaiting."""
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "ai_fallback_rank:custom_gpt"

        update = self._make_callback_update("admin:back")
        asyncio.run(_handle_admin_callback(update, ctx, "back"))

        self.assertNotIn("awaiting", ctx.user_data)

    def test_cancel_clears_all_state(self):
        """Pressing cancel clears awaiting, preset_edits, and full_edit."""
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        ctx.user_data["awaiting"] = "ai_preset_edit:custom_gpt:model"
        ctx.user_data["preset_edits"] = {"custom_gpt": {"model": "gpt-4"}}
        ctx.user_data["full_edit"] = {"preset": "custom_gpt", "field_idx": 0, "values": {}}

        update = self._make_callback_update("admin:cancel")
        asyncio.run(_handle_admin_callback(update, ctx, "cancel"))

        self.assertNotIn("awaiting", ctx.user_data)
        self.assertNotIn("preset_edits", ctx.user_data)
        self.assertNotIn("full_edit", ctx.user_data)


class ShowSettingsMaskingTest(unittest.TestCase):
    """show_settings branch must mask short API keys and use HTML parse mode."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        db.create_user_if_needed(1, "owner")
        db.set_preset(name="custom_gpt", base_url="https://x", model="m", api_key="sk-123", is_custom=1)
        db.set_setting("ai_primary_preset", "custom_gpt")
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def test_short_key_always_masked(self):
        """A short API key (<=12 chars) shows as ***."""
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        update = self._make_callback_update("admin:show_settings")

        asyncio.run(_handle_admin_callback(update, ctx, "show_settings"))

        rendered = update.callback_query.edit_message_text.call_args[0][0]
        self.assertIn("***", rendered)
        self.assertNotIn("sk-123", rendered)

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


if __name__ == "__main__":
    unittest.main()