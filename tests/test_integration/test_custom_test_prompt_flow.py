"""Integration tests for the custom-test wizard typed-prompt flow.

Regression for BUG-2: the wizard's typed system prompt was written to a dead
``custom_test_prompt`` key instead of ``custom_test_state["prompt"]``, so
``_run_custom_test`` always used the default. These tests drive the real
wizard (prompt text -> lang/goal/level/target callbacks) and assert the typed
prompt reaches ``ai.custom_test_card`` via ``user_prompt``.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class CustomTestPromptFlowTest(unittest.TestCase):
    """Custom-test wizard routed through _handle_admin_callback/_handle_admin_text_input."""

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
            "gapgpt",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
            is_custom=0,
        )
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_text_update(self, text: str, user_id: int = 1):
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.message = msg
        update.callback_query = None
        return update

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

    def _run_full_wizard(self, ctx, typed_prompt: str):
        """Drive prompt text + lang/goal/level/target callbacks to _run_custom_test."""
        from handlers.admin import _handle_admin_callback, _handle_admin_text_input

        # Step 1: start wizard -> awaiting ai_custom_test_prompt
        start = self._make_callback_update("admin:ai_custom_test")
        asyncio.run(_handle_admin_callback(start, ctx, "ai_custom_test"))
        self.assertEqual(ctx.user_data["awaiting"], "ai_custom_test_prompt")

        # Step 2: type the prompt (BUG-2 target)
        text_upd = self._make_text_update(typed_prompt)
        asyncio.run(_handle_admin_text_input(text_upd, ctx, "ai_custom_test_prompt", typed_prompt))
        self.assertNotIn("awaiting", ctx.user_data)

        # Step 3-6: lang/goal/level/target callbacks
        for data, action in (
            ("admin:ai_custom_test:lang:en", "ai_custom_test:lang:en"),
            ("admin:ai_custom_test:goal:general", "ai_custom_test:goal:general"),
            ("admin:ai_custom_test:level:beginner", "ai_custom_test:level:beginner"),
            ("admin:ai_custom_test:target:current", "ai_custom_test:target:current"),
        ):
            cb = self._make_callback_update(data)
            asyncio.run(_handle_admin_callback(cb, ctx, action))

    def test_typed_prompt_reaches_custom_test_card(self):
        """The typed prompt must be passed to ai.custom_test_card as user_prompt."""
        from handlers import admin_ai

        ctx = self._make_context()
        with patch.object(admin_ai.ai, "custom_test_card", return_value={"word": "casa"}) as mock_card, \
             patch("handlers.admin_ai.prompts.daily_batch_system_prompt", return_value="SYS"):
            self._run_full_wizard(ctx, "کارت واژگان سطح پیشرفته بساز")

        self.assertTrue(mock_card.called)
        kw = mock_card.call_args.kwargs or {}
        user_prompt = kw.get("user_prompt") if kw else mock_card.call_args[0][1]
        self.assertEqual(user_prompt, "کارت واژگان سطح پیشرفته بساز")

    def test_default_prompt_when_not_typed(self):
        """When the owner supplies no prompt, the default must still apply."""
        from handlers import admin_ai
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        # Wizard progressed past the prompt step WITHOUT recording a prompt,
        # so custom_test_state has no "prompt" key.
        ctx.user_data["custom_test_state"] = {"step": "lang"}

        with patch.object(admin_ai.ai, "custom_test_card", return_value={"word": "casa"}) as mock_card, \
             patch("handlers.admin_ai.prompts.daily_batch_system_prompt", return_value="SYS"):
            for data, action in (
                ("admin:ai_custom_test:lang:en", "ai_custom_test:lang:en"),
                ("admin:ai_custom_test:goal:general", "ai_custom_test:goal:general"),
                ("admin:ai_custom_test:level:beginner", "ai_custom_test:level:beginner"),
                ("admin:ai_custom_test:target:current", "ai_custom_test:target:current"),
            ):
                cb = self._make_callback_update(data)
                asyncio.run(_handle_admin_callback(cb, ctx, action))

        self.assertTrue(mock_card.called)
        kw = mock_card.call_args.kwargs or {}
        user_prompt = kw.get("user_prompt") if kw else mock_card.call_args[0][1]
        self.assertEqual(user_prompt, "یک کارت واژگان بساز")


if __name__ == "__main__":
    unittest.main()
