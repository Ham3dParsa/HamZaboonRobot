"""R7: admin:close must delete message and clear pending, keyboards contain IBTN_CLOSE."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest

from services import db
from services.db import schema as db_schema

from config.keyboards.constants import IBTN_CLOSE


class AdminCloseHandlerTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        db.create_user_if_needed(1, "owner")
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def _make_callback_update(self, data: str = "admin:close", user_id: int = 1, chat_id: int = 1, msg_id: int = 10):
        msg = MagicMock()
        msg.message_id = msg_id
        chat = MagicMock()
        chat.id = chat_id
        msg.chat = chat
        query = MagicMock()
        query.data = data
        query.message = msg
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat = MagicMock()
        update.effective_chat.id = chat_id
        update.callback_query = query
        return update

    def _make_context(self, awaiting_msg=None):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        ctx.bot.delete_message = AsyncMock()
        if awaiting_msg is not None:
            ctx.user_data["_awaiting_msg"] = awaiting_msg
        return ctx

    def test_close_clears_pending_and_deletes(self):
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context(awaiting_msg={"chat_id": 1, "message_id": 99})
        ctx.user_data["awaiting"] = "admin_broadcast"
        ctx.user_data["pending_broadcast"] = {"text": "hi"}
        ctx.user_data["preset_edits"] = {"p": {"model": "x"}}
        ctx.user_data["full_edit"] = {"preset": "p"}
        ctx.user_data["plan_full_edit"] = {"plan": "bronze"}

        update = self._make_callback_update()

        with patch("handlers.admin._delete_with_retry", new_callable=AsyncMock) as mock_del:
            with patch("handlers.admin._clear_awaiting_prompt", new_callable=AsyncMock) as mock_clear:
                # let clear pop the awaiting_msg like real helper does
                async def fake_clear(c):
                    c.user_data.pop("_awaiting_msg", None)
                mock_clear.side_effect = fake_clear
                asyncio.run(_handle_admin_callback(update, ctx, "close"))

                self.assertNotIn("awaiting", ctx.user_data)
                self.assertNotIn("pending_broadcast", ctx.user_data)
                self.assertNotIn("preset_edits", ctx.user_data)
                self.assertNotIn("full_edit", ctx.user_data)
                self.assertNotIn("plan_full_edit", ctx.user_data)
                # delete attempted for callback message and awaiting prompt
                self.assertTrue(mock_del.called)
                # notify with بسته شد. via notify_callback -> query.answer
                query = update.callback_query
                self.assertTrue(query.answer.called)
                # ensure notify used correct text (at least one answer call)
                answered_texts = [str(c.args[0]) if c.args else "" for c in query.answer.call_args_list]
                self.assertTrue(query.answer.called)
                self.assertTrue(
                    any("بسته شد" in t for t in answered_texts),
                    f"close notify text missing: {answered_texts}",
                )

    def test_close_swallows_badrequest(self):
        from handlers.admin import _handle_admin_callback

        ctx = self._make_context()
        update = self._make_callback_update()

        with patch("handlers.admin._delete_with_retry", new_callable=AsyncMock) as mock_del:
            mock_del.side_effect = BadRequest("message to delete not found")
            with patch("handlers.admin._clear_awaiting_prompt", new_callable=AsyncMock):
                # should not raise
                asyncio.run(_handle_admin_callback(update, ctx, "close"))
                self.assertTrue(mock_del.called)


class AdminKeyboardsCloseButtonTest(unittest.TestCase):
    def test_admin_keyboards_contain_close(self):
        from config.keyboards.admin import (
            admin_cost_keyboard,
            admin_panel_keyboard,
            ai_fallback_keyboard,
            ai_preset_edit_keyboard,
            ai_preset_view_keyboard,
            ai_presets_list_keyboard,
            ai_settings_keyboard,
            backup_restore_keyboard,
            broadcast_preview_keyboard,
            dm_preview_keyboard,
            fallback_chain_keyboard,
            llm_cost_dashboard_keyboard,
            llm_cost_kind_keyboard,
            llm_cost_plan_keyboard,
            llm_cost_pricing_keyboard,
            llm_cost_status_keyboard,
            llm_legend_back_keyboard,
            log_level_keyboard,
            maintenance_keyboard,
            plan_manager_keyboard,
            plan_view_keyboard,
            plan_wizard_keyboard,
            plan_wizard_summary_keyboard,
            stats_back_keyboard,
            stats_menu_keyboard,
            tts_cache_keyboard,
            user_activity_keyboard,
            user_block_confirm_keyboard,
            user_management_keyboard,
            user_plan_confirm_keyboard,
            user_profile_keyboard,
            user_reset_confirm_keyboard,
        )
        from config.keyboards.common import admin_awaiting_inline_keyboard, display_toggles_keyboard

        keyboards = [
            admin_panel_keyboard(),
            plan_manager_keyboard([]),
            plan_view_keyboard("free", False),
            plan_wizard_keyboard("free"),
            plan_wizard_summary_keyboard("free"),
            tts_cache_keyboard(""),
            backup_restore_keyboard(),
            maintenance_keyboard(False),
            stats_menu_keyboard(),
            stats_back_keyboard(),
            user_management_keyboard(),
            user_profile_keyboard(123, False),
            user_reset_confirm_keyboard(123),
            user_block_confirm_keyboard(123),
            user_plan_confirm_keyboard(123, "gold"),
            dm_preview_keyboard(123),
            broadcast_preview_keyboard(),
            user_activity_keyboard("on"),
            log_level_keyboard("INFO"),
            admin_cost_keyboard(),
            llm_cost_dashboard_keyboard(),
            llm_legend_back_keyboard(),
            llm_cost_plan_keyboard(),
            llm_cost_kind_keyboard(),
            llm_cost_status_keyboard(),
            llm_cost_pricing_keyboard(),
            ai_settings_keyboard(),
            ai_presets_list_keyboard([], "x"),
            ai_preset_view_keyboard({"name": "x"}, "y"),
            ai_preset_edit_keyboard("x", {"name": "x"}),
            ai_fallback_keyboard("a", "b", "a"),
            fallback_chain_keyboard([]),
            admin_awaiting_inline_keyboard(),
            display_toggles_keyboard({}),
        ]

        for idx, kb in enumerate(keyboards):
            with self.subTest(idx=idx):
                found = any(
                    btn.text == IBTN_CLOSE and btn.callback_data == "admin:close"
                    for row in kb.inline_keyboard
                    for btn in row
                )
                self.assertTrue(found, f"keyboard missing IBTN_CLOSE admin:close: {kb.inline_keyboard}")

    def test_show_settings_contains_close(self):
        # verify handlers/admin inline keyboards include close via code inspection
        import pathlib
        text = (pathlib.Path(__file__).resolve().parents[2] / "handlers" / "admin.py").read_text(encoding="utf-8")
        self.assertIn('IBTN_CLOSE', text)
        self.assertIn('admin:close', text)


if __name__ == "__main__":
    unittest.main()
