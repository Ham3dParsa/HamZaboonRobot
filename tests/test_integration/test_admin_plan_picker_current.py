"""R1: plan picker shows current vs new (text/emoji marker, style unused).

Covers: picker prompt contains the current plan name; the current-plan button
is marked (✅ + «فعلی»); the confirm text contains old→new (از…به); and the
text-only marking guarantee (our builder never sets PTB ``style`` — styled
buttons need Feb-2026+ clients, so text/emoji stays the cross-client choice).
"""

from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminPlanPickerCurrentTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        try:
            db.create_user_if_needed(42, "alice", "Alice Wonder")
        except TypeError:
            db.create_user_if_needed(42, "alice")
        db.set_plan(42, "silver")
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _cb(self, data: str, user_id: int = 1):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        msg = MagicMock()
        msg.reply_document = AsyncMock()
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_user.username = "owner"
        update.effective_chat.id = user_id
        update.callback_query = query
        update.effective_message = msg
        update.message = msg
        query.message = msg
        return update

    def _ctx(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        ctx.bot.send_message = AsyncMock()
        return ctx

    def _open_picker(self):
        """Open the picker for user 42; return (prompt_text, keyboard)."""
        from handlers.admin import _handle_admin_callback

        update = self._cb("admin:user:plan:42")
        ctx = self._ctx()
        with patch("handlers.admin_users._edit_or_send", new=AsyncMock()) as mock_edit:
            asyncio.run(_handle_admin_callback(update, ctx, "user:plan:42"))
            mock_edit.assert_called_once()
            args, kwargs = mock_edit.call_args
            text = args[2] if len(args) > 2 else kwargs.get("text", "")
            return text, kwargs.get("reply_markup")

    def test_prompt_contains_current_plan_name(self):
        text, _kb = self._open_picker()
        self.assertIn("پلن کنونی", text)
        # user 42 is on silver → Persian display name + code both visible
        self.assertIn("نقره‌ای", text)
        self.assertIn("silver", text)
        self.assertIn("42", text)

    def test_current_button_marked_and_callbacks_unchanged(self):
        _text, kb = self._open_picker()
        self.assertIsNotNone(kb)
        by_cb = {b.callback_data: b.text for row in kb.inline_keyboard for b in row}
        current_cb = "admin:user:plan_select:42:silver"
        self.assertIn(current_cb, by_cb)
        # current button carries the text/emoji marker…
        self.assertIn("✅", by_cb[current_cb])
        self.assertIn("فعلی", by_cb[current_cb])
        # …other plan buttons do not…
        for cb, label in by_cb.items():
            if cb.startswith("admin:user:plan_select:42:") and cb != current_cb:
                self.assertNotIn("فعلی", label)
        # …and no callback prefix changed (reuse existing plan_select data)
        for cb in by_cb:
            if "plan_select" in cb:
                self.assertTrue(cb.startswith("admin:user:plan_select:42:"))

    def test_confirm_text_contains_old_to_new(self):
        from handlers.admin_users import handle_admin_user

        cb_select = self._cb("admin:user:plan_select:42:gold")
        ctx = self._ctx()
        with patch("handlers.admin_users._edit_or_send", new=AsyncMock()) as mock_edit:
            asyncio.run(handle_admin_user(cb_select, ctx, "user:plan_select:42:gold"))
            mock_edit.assert_called_once()
            args, kwargs = mock_edit.call_args
            text = args[2] if len(args) > 2 else kwargs.get("text", "")
            self.assertIn("از", text)
            self.assertIn("به", text)
            # old (silver) and new (gold) both shown, display name + code
            self.assertIn("نقره‌ای", text)
            self.assertIn("silver", text)
            self.assertIn("طلایی", text)
            self.assertIn("gold", text)
        # still a preview — no write yet
        self.assertEqual(db.get_user(42)["plan"], "silver")

    def test_long_current_label_stays_within_budget(self):
        """Long display_name: marked current button keeps the FULL marker."""
        from config.keyboards.admin import user_plan_picker_keyboard

        long_name = "طلایی ویژه با قابلیت‌های اضافی و نام خیلی طولانی"
        self.assertGreater(len(long_name), 30)
        kb = user_plan_picker_keyboard(
            42, [{"name": "gold", "display_name": long_name}], current_plan="gold"
        )
        texts = [b.text for row in kb.inline_keyboard for b in row]
        marked = [t for t in texts if t.startswith("✅")]
        self.assertTrue(marked)
        for t in marked:
            self.assertLessEqual(len(t), 31)
            # the full marker must survive — not just the ✅ prefix
            self.assertIn("فعلی", t)

    def test_marking_is_text_only_no_style_used(self):
        """Marking is text/emoji-only: the builder never sets PTB ``style``.

        PTB 22.7+ (pinned line) exposes ``InlineKeyboardButton.style``, so the
        old "no style param" assertion is obsolete — the guarantee we actually
        need is that our buttons carry no style and the marker is in the text.
        """
        from telegram import InlineKeyboardButton
        from config.keyboards.admin import user_plan_picker_keyboard

        # our builder exposes no style param — marking is text-only…
        kb_params = inspect.signature(user_plan_picker_keyboard).parameters
        self.assertNotIn("style", kb_params)
        # …and the marked picker still builds fine, unstyled, on any PTB…
        kb = user_plan_picker_keyboard(
            42, [{"name": "silver", "display_name": "نقره‌ای"}], current_plan="silver"
        )
        buttons = [b for row in kb.inline_keyboard for b in row]
        for b in buttons:
            self.assertIsInstance(b, InlineKeyboardButton)
            self.assertEqual(getattr(b, "style", None), None)
        texts = [b.text for b in buttons]
        self.assertTrue(any("فعلی" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
