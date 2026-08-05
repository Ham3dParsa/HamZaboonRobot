"""Integration tests for the admin plan-manager flow (db-driven-plan-spec, Phase D).

Covers: plan list callback -> view -> full-edit wizard (next/skip/save),
activate/deactivate toggle, and `admin_set_plan` DB-backed validation.
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


class PlanManagerFlowTest(unittest.TestCase):
    """Admin plan-manager callbacks routed through _handle_admin_callback."""

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

    # ------------------------------------------------------------------
    # Update / context factories
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Callback routing
    # ------------------------------------------------------------------
    def test_plan_list_callback_renders_keyboard(self):
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update("admin:plans")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans"))
        self.assertTrue(update.callback_query.answer.called)
        self.assertTrue(update.callback_query.edit_message_text.called)

    def test_plan_view_callback_shows_plan_detail(self):
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update("admin:plans:view:silver")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:view:silver"))
        update.callback_query.edit_message_text.assert_called_once()

    def test_plan_view_non_owner_rejected(self):
        from handlers.admin import _handle_admin_callback

        with patch("handlers.admin.is_owner", return_value=False):
            update = self._make_callback_update("admin:plans", user_id=1234)
            ctx = self._make_context()
            asyncio.run(_handle_admin_callback(update, ctx, "plans"))
        answer = update.callback_query.answer.call_args
        self.assertIn("فقط مالک ربات", answer[0][0])

    # ------------------------------------------------------------------
    # Wizard flow
    # ------------------------------------------------------------------
    def test_plan_wizard_edit_starts_and_advances(self):
        from handlers.admin import _handle_admin_callback, _handle_plan_wizard_input

        update = self._make_callback_update("admin:plans:edit:silver")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:edit:silver"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:silver:0")

        msg = MagicMock()
        msg.reply_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user.id = 1
        upd.message = msg
        upd.callback_query = None
        asyncio.run(_handle_plan_wizard_input(upd, ctx, "silver", 0, "نقره‌ای ویژه"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:silver:1")

    def test_plan_wizard_text_input_dispatches_through_awaiting(self):
        """Text entered during the wizard must be routed through the real
        awaiting dispatch in _handle_admin_text_input (regression for the
        broken admin_plan_full_edit: parse)."""
        from handlers.admin import _handle_admin_callback, _handle_admin_text_input

        update = self._make_callback_update("admin:plans:edit:silver")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:edit:silver"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:silver:0")

        msg = MagicMock()
        msg.reply_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user.id = 1
        upd.message = msg
        upd.callback_query = None
        asyncio.run(
            _handle_admin_text_input(upd, ctx, "admin_plan_full_edit:silver:0", "نقره‌ای ویژه")
        )
        # The dispatch must advance the wizard, not swallow the message.
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:silver:1")
        self.assertEqual(ctx.user_data["plan_full_edit"]["values"]["display_name"], "نقره‌ای ویژه")

    def test_plan_wizard_save_persists_changes(self):
        from handlers.admin import _handle_admin_callback, _handle_plan_wizard_save

        update = self._make_callback_update("admin:plans:edit:gold")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:edit:gold"))

        plan = db.get_plan("gold")
        ctx.user_data["plan_full_edit"] = {
            "plan": "gold",
            "field_idx": 2,
            "values": {
                "display_name": "طلایی",
                "price": 12,
                "query_quota": 123,
                "max_sessions": plan["max_sessions"],
                "cards_per_session": plan["cards_per_session"],
            },
        }
        ctx.user_data["awaiting"] = "admin_plan_full_edit:gold:4"

        update = self._make_callback_update("admin:plans:full_edit_save:gold")
        asyncio.run(_handle_plan_wizard_save(update, ctx, "gold"))

        saved = db.get_plan("gold")
        self.assertEqual(saved["query_quota"], 123)

    def test_plan_wizard_invalid_field_keeps_awaiting(self):
        from handlers.admin import _handle_admin_callback, _handle_plan_wizard_input

        update = self._make_callback_update("admin:plans:edit:free")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:edit:free"))

        msg = MagicMock()
        msg.reply_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user.id = 1
        upd.message = msg
        upd.callback_query = None
        asyncio.run(_handle_plan_wizard_input(upd, ctx, "free", 1, "abc"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:free:1")
        msg.reply_text.assert_called_once()

    def test_plan_set_active_toggles(self):
        from handlers.admin import _handle_admin_callback

        self.assertTrue(db.get_plan("bronze")["is_active"])
        update = self._make_callback_update("admin:plans:set_active:bronze")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:set_active:bronze"))
        self.assertFalse(db.get_plan("bronze")["is_active"])

    # ------------------------------------------------------------------
    # admin_set_plan DB-backed validation
    # ------------------------------------------------------------------
    def test_admin_set_plan_accepts_any_db_plan(self):
        from handlers.admin import _handle_admin_text_input

        db.set_user_lang_goal(1, "en", "general")

        msg = MagicMock()
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.message = msg
        ctx = self._make_context()

        asyncio.run(_handle_admin_text_input(update, ctx, "admin_set_plan", "1 emerald"))
        self.assertEqual(db.get_user(1)["plan"], "emerald")
        msg.reply_text.assert_called()


if __name__ == "__main__":
    unittest.main()