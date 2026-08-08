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

    def test_plan_wizard_back_button_returns_to_previous_field(self):
        """Pressing back in the wizard must move to the previous field while
        keeping already-collected values, so the owner can re-enter one field
        without losing the rest."""
        from handlers.admin import _handle_admin_callback, _handle_plan_wizard_input

        update = self._make_callback_update("admin:plans:edit:emerald")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:edit:emerald"))

        # Enter display_name -> advances to field 1 (price).
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user.id = 1
        upd.message = msg
        upd.callback_query = None
        asyncio.run(_handle_plan_wizard_input(upd, ctx, "emerald", 0, "زمرد"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:emerald:1")
        self.assertEqual(ctx.user_data["plan_full_edit"]["values"]["display_name"], "زمرد")

        # Enter price -> field 2 (query_quota).
        upd_2 = MagicMock()
        upd_2.effective_user.id = 1
        upd_2.message = MagicMock()
        upd_2.message.reply_text = AsyncMock()
        upd_2.callback_query = None
        asyncio.run(_handle_plan_wizard_input(upd_2, ctx, "emerald", 1, "20"))

        # Back to price field.
        back_update = self._make_callback_update("admin:plans:full_edit_back:emerald")
        asyncio.run(_handle_admin_callback(back_update, ctx, "plans:full_edit_back:emerald"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:emerald:1")
        # Re-entered display_name value must survive the back navigation.
        self.assertEqual(ctx.user_data["plan_full_edit"]["values"]["display_name"], "زمرد")

    def test_plan_wizard_field_renders_groups_hints_and_pending(self):
        """The wizard field message must show the group header/hints (R4/F3),
        the current DB value, and (after typing) the pending value (F5)."""
        from handlers.admin import _handle_admin_callback, _handle_plan_wizard_input

        update = self._make_callback_update("admin:plans:edit:silver")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:edit:silver"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:silver:0")

        # Display group header + hint must be defined.
        from handlers.admin_plans import PLAN_WIZARD_GROUP_HEADERS, PLAN_WIZARD_FIELD_HINTS
        header0, hint0 = PLAN_WIZARD_GROUP_HEADERS[0]
        self.assertTrue(header0 and hint0, "display group header/hint defined")
        # Field hint for the clarified query-quota label must be defined.
        self.assertIn("query_quota", PLAN_WIZARD_FIELD_HINTS)

        # Type a display_name and a price, then go back to display_name.
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user.id = 1
        upd.message = msg
        upd.callback_query = None
        asyncio.run(_handle_plan_wizard_input(upd, ctx, "silver", 0, "نقره‌ای"))
        asyncio.run(_handle_plan_wizard_input(upd, ctx, "silver", 1, "5"))

        back_update = self._make_callback_update("admin:plans:full_edit_back:silver")
        asyncio.run(_handle_admin_callback(back_update, ctx, "plans:full_edit_back:silver"))

        # _show_plan_wizard_field renders into _edit_or_send -> the callback
        # update's edit_message_text mock. Back lands on price (field 1), so
        # assert the pending price + the DB value both appear.
        edit_kwargs = back_update.callback_query.edit_message_text.call_args
        rendered = edit_kwargs.kwargs.get("text") or edit_kwargs[0][0]
        self.assertIn("مقدار در انتظار", rendered)
        self.assertIn("<code>5</code>", rendered)
        self.assertIn("مقدار فعلی (DB)", rendered)
        self.assertIn(f"<code>{db.get_plan('silver')['price']}</code>", rendered)

    def test_plan_wizard_keyboard_has_back_not_next(self):
        from config.keyboards import plan_wizard_keyboard

        kbd = plan_wizard_keyboard("silver")
        callbacks = []
        for row in kbd.inline_keyboard:
            for btn in row:
                callbacks.append(btn.callback_data)
        self.assertIn("admin:plans:full_edit_back:silver", callbacks)
        self.assertIn("admin:plans:full_edit_skip:silver", callbacks)
        self.assertNotIn("admin:plans:full_edit_next:silver", callbacks)

    def test_plan_wizard_back_at_first_field_is_noop(self):
        """Back at the first wizard field must not move before the start and
        must keep awaiting on field 0."""
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update("admin:plans:edit:free")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:edit:free"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:free:0")

        back_update = self._make_callback_update("admin:plans:full_edit_back:free")
        asyncio.run(_handle_admin_callback(back_update, ctx, "plans:full_edit_back:free"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:free:0")

    def test_plan_wizard_skip_leaves_db_value_unchanged(self):
        """Skip advances to the next field without recording a value for the
        skipped field, so the DB value stays as-is."""
        from handlers.admin import _handle_admin_callback, _handle_plan_wizard_input

        update = self._make_callback_update("admin:plans:edit:bronze")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:edit:bronze"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:bronze:0")

        # Enter a display name, then skip price (field 1).
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        upd = MagicMock()
        upd.effective_user.id = 1
        upd.message = msg
        upd.callback_query = None
        asyncio.run(_handle_plan_wizard_input(upd, ctx, "bronze", 0, "برنز"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:bronze:1")

        skip_update = self._make_callback_update("admin:plans:full_edit_skip:bronze")
        asyncio.run(_handle_admin_callback(skip_update, ctx, "plans:full_edit_skip:bronze"))
        self.assertEqual(ctx.user_data["awaiting"], "admin_plan_full_edit:bronze:2")
        self.assertNotIn("price", ctx.user_data["plan_full_edit"]["values"])
        # DB untouched.
        self.assertEqual(db.get_plan("bronze")["price"], 0)

    def test_plan_wizard_skip_after_typing_discards_pending_value(self):
        """If the owner types a value, navigates away, goes back, then skips,
        the typed value must be discarded so the DB value is used on save."""
        from handlers.admin import _handle_admin_callback, _handle_plan_wizard_input

        update = self._make_callback_update("admin:plans:edit:emerald")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "plans:edit:emerald"))

        def _type(field_idx, value):
            upd = MagicMock()
            upd.effective_user.id = 1
            upd.message = MagicMock()
            upd.message.reply_text = AsyncMock()
            upd.callback_query = None
            asyncio.run(_handle_plan_wizard_input(upd, ctx, "emerald", field_idx, value))

        _type(0, "زمرد")
        _type(1, "20")
        self.assertIn("price", ctx.user_data["plan_full_edit"]["values"])

        # Back to price, then skip it: pending price must be discarded.
        back_update = self._make_callback_update("admin:plans:full_edit_back:emerald")
        asyncio.run(_handle_admin_callback(back_update, ctx, "plans:full_edit_back:emerald"))
        skip_update = self._make_callback_update("admin:plans:full_edit_skip:emerald")
        asyncio.run(_handle_admin_callback(skip_update, ctx, "plans:full_edit_skip:emerald"))

        self.assertNotIn("price", ctx.user_data["plan_full_edit"]["values"])
        # display_name typed earlier must survive the skip.
        self.assertEqual(ctx.user_data["plan_full_edit"]["values"]["display_name"], "زمرد")

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