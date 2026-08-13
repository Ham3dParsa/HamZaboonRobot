"""Integration tests for the AI preset full-edit wizard navigation.

Regression for the dead NEXT/SKIP buttons: the wizard keyboard emits 3-segment
callbacks (``admin:ai_preset:full_edit_next:{name}`` -> stripped
``ai_preset:full_edit_next:{name}`` -> 3 parts), but the dispatcher guard
required ``len(parts) == 4``, so NEXT/SKIP were never invoked. These tests
dispatch through the real ``_handle_admin_callback`` -> ``handle_ai_callback``
path and assert the wizard actually advances.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AiFullEditWizardNavTest(unittest.TestCase):
    """Full-edit NEXT/SKIP callbacks routed through _handle_admin_callback."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_preset(
            "custom_gpt",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
        )
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

    def _start_wizard(self, ctx, preset_name: str = "custom_gpt"):
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update(f"admin:ai_preset:full_edit:{preset_name}")
        asyncio.run(_handle_admin_callback(update, ctx, f"ai_preset:full_edit:{preset_name}"))
        self.assertEqual(ctx.user_data["awaiting"], f"ai_preset_full_edit:{preset_name}:0")

    def test_full_edit_next_advances_wizard(self):
        """The 3-segment NEXT callback must invoke _handle_full_edit_next and
        advance the wizard (awaiting field 0 -> 1)."""
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        self._start_wizard(ctx)

        update = self._make_callback_update("admin:ai_preset:full_edit_next:custom_gpt")
        asyncio.run(_handle_admin_callback(update, ctx, "ai_preset:full_edit_next:custom_gpt"))

        self.assertEqual(ctx.user_data["awaiting"], "ai_preset_full_edit:custom_gpt:1")
        self.assertEqual(ctx.user_data["full_edit"]["field_idx"], 1)
        update.callback_query.edit_message_text.assert_called_once()

    def test_full_edit_skip_advances_wizard(self):
        """The 3-segment SKIP callback must invoke _handle_full_edit_skip and
        advance the wizard."""
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        self._start_wizard(ctx)

        update = self._make_callback_update("admin:ai_preset:full_edit_skip:custom_gpt")
        asyncio.run(_handle_admin_callback(update, ctx, "ai_preset:full_edit_skip:custom_gpt"))

        self.assertEqual(ctx.user_data["awaiting"], "ai_preset_full_edit:custom_gpt:1")
        self.assertEqual(ctx.user_data["full_edit"]["field_idx"], 1)

    def test_full_edit_cancel_still_works(self):
        """CANCEL (already-working 3-segment branch) remains functional."""
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        self._start_wizard(ctx)

        update = self._make_callback_update("admin:ai_preset:full_edit_cancel:custom_gpt")
        asyncio.run(_handle_admin_callback(update, ctx, "ai_preset:full_edit_cancel:custom_gpt"))

        self.assertNotIn("awaiting", ctx.user_data)
        self.assertNotIn("full_edit", ctx.user_data)


if __name__ == "__main__":
    unittest.main()
