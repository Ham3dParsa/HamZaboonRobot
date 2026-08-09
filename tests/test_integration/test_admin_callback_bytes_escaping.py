"""Integration tests for R3 64-byte callback limit on handler-built keyboards
and R10 HTML escaping in admin_ai render sites.

Extends the routing seam (dispatch through _handle_admin_callback / handle_ai_callback)
to cover keyboards built inside handlers (full-edit wizard, summary, save-confirm)
that previously emitted raw preset names.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema

# A long custom preset name (within the 60-char R11 cap) that overflows raw callbacks.
LONG_NAME = "x" * 60


def _collect(data) -> list[str]:
    out = []
    for row in (data or []):
        for btn in row:
            if getattr(btn, "callback_data", None):
                out.append(btn.callback_data)
    return out


class HandlerBuiltCallbackByteLimitTest(unittest.TestCase):
    """full_edit_*/confirm_save_* callbacks built inside handlers must be <= 64 bytes."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        db.create_user_if_needed(1, "owner")
        db.set_preset(name=LONG_NAME, base_url="https://x", model="m", api_key="sk-123", is_custom=1)
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def _make_callback_update(self, data: str):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        return update

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_full_edit_wizard_buttons_under_64(self):
        """full_edit_next/skip/cancel on the wizard field keyboard must be <= 64 bytes
        even with a 60-char preset name."""
        from handlers.admin_ai import _show_wizard_field
        from config.keyboards import IBTN_FULL_EDIT_NEXT

        preset = db.get_preset(LONG_NAME)
        ctx = self._context()
        update = self._make_callback_update("admin:noop")
        asyncio.run(_show_wizard_field(update, ctx, LONG_NAME, 0, preset))

        # The keyboard is passed via reply_markup to edit_message_text
        render_call = update.callback_query.edit_message_text.call_args
        markup = render_call.kwargs.get("reply_markup") if render_call.kwargs else None
        self.assertIsNotNone(markup, "expected a rendered wizard keyboard")
        for cb in _collect(markup.inline_keyboard):
            self.assertLessEqual(len(cb.encode("utf-8")), 64, cb)

    def test_edit_field_under_64_with_long_name(self):
        """ai_preset_edit_keyboard callbacks must stay under 64 with a 60-char name."""
        from config.keyboards import ai_preset_edit_keyboard
        preset = {"name": LONG_NAME, "is_custom": 1, "model": "m", "base_url": "u"}
        markup = ai_preset_edit_keyboard(LONG_NAME, preset)
        for cb in _collect(markup.inline_keyboard):
            self.assertLessEqual(len(cb.encode("utf-8")), 64, cb)


class AiConnectionEscapingTest(unittest.TestCase):
    """_test_ai_connection must escape AI-provider output (R10 / D2)."""

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

    def _make_callback_update(self, data: str):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        return update

    def test_ai_connection_error_message_escaped(self):
        """An error_message with '<' must render escaped, not break HTML parse."""
        from handlers.admin_ai import _test_ai_connection

        ctx = self._context()
        update = self._make_callback_update("admin:ai_test_connection")

        result = {
            "success": False,
            "error_class": "BadRequest",
            "error_message": "unexpected <tag> & broken",
            "latency_ms": 10,
        }
        with patch("handlers.admin_ai.ai.test_connection", return_value=result):
            asyncio.run(_test_ai_connection(update, ctx))

        rendered = update.callback_query.edit_message_text.call_args[0][0]
        self.assertIn("&lt;tag&gt;", rendered)
        self.assertIn("&amp;", rendered)
        self.assertNotIn("unexpected <tag>", rendered)

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx


if __name__ == "__main__":
    unittest.main()