"""Integration tests for admin awaiting polish — review fixes PR 516.

Covers:
- bot.py text-cancel admin path clears all pending_* + full_edit/plan_full_edit/preset_edits
  and routes to admin panel (not generic _exit_awaiting_flow).
- admin:back when awaiting admin_user_search / pending_dm -> user-management (BTN_ADMIN_USER_MANAGE)
- prompt capture: _store_awaiting_msg fallback uses effective_message, not callback_query.message
- _clear_awaiting_prompt BadRequest swallowed, other logged
- robust ai_preset_edit parsing (split with maxsplit 2)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminAwaitingTextCancelTest(unittest.TestCase):
    """bot.text_router admin text-cancel must clear all stale pending keys."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new
        db_schema.DB_PATH = new
        db.init_db()
        db.create_user_if_needed(1, "owner")
        self.owner_patch = patch("bot.is_owner", return_value=True)
        self.owner_patch.start()
        self.addCleanup(self.owner_patch.stop)
        # also patch handlers.admin.is_owner for back path
        self.owner_patch2 = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patch2.start()
        self.addCleanup(self.owner_patch2.stop)

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _make_text_update(self, text: str, user_id: int = 1):
        msg = MagicMock()
        msg.text = text
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.message = msg
        update.effective_message = msg
        update.effective_user = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat = MagicMock()
        update.effective_chat.id = user_id
        update.callback_query = None
        return update

    def test_text_cancel_clears_all_admin_pending(self):
        from bot import text_router

        ctx = MagicMock()
        ctx.user_data = {
            "awaiting": "admin_broadcast",
            "_awaiting_pending": True,
            "_awaiting_msg": {"chat_id": 1, "message_id": 99},
            "pending_dm": {"user_id": 42, "text": "x", "html": "x"},
            "pending_plan": {"user_id": 42, "new_plan": "silver"},
            "pending_block": {"user_id": 42},
            "pending_broadcast": {"text": "hi", "html": "hi", "count": 1},
            "full_edit": {"preset": "p", "field_idx": 0, "values": {}},
            "plan_full_edit": {"plan": "silver", "field_idx": 0, "values": {}},
            "preset_edits": {"custom_gpt": {"model": "x"}},
        }
        ctx.bot = AsyncMock()
        update = self._make_text_update("لغو", user_id=1)
        # mock helpers to avoid actual Telegram calls
        with patch("bot.exit_admin_awaiting_cancel", wraps=None) as mock_exit:
            # use real exit_admin_awaiting_cancel but mock its inner send
            from services.utils.helpers import exit_admin_awaiting_cancel
            # patch the inner _edit_or_send and _clear_awaiting_prompt
            with patch("services.utils.helpers._edit_or_send", new=AsyncMock()) as mock_send, \
                 patch("services.utils.helpers._clear_awaiting_prompt", new=AsyncMock()) as mock_clear:
                async def fake_exit(u, c):
                    # mimic real helper but using mocked inner functions
                    from services.utils.helpers import clear_admin_pending_state
                    clear_admin_pending_state(c)
                    await mock_clear(c)
                    await mock_send(u, c, "لغو شد.", reply_markup=MagicMock())
                with patch("bot.exit_admin_awaiting_cancel", side_effect=fake_exit):
                    asyncio.run(text_router(update, ctx))
                # after cancel all pending keys must be gone
                for k in ("pending_dm", "pending_plan", "pending_block", "pending_broadcast",
                          "full_edit", "plan_full_edit", "preset_edits", "_awaiting_pending", "awaiting"):
                    self.assertNotIn(k, ctx.user_data, f"{k} should be cleared")
                mock_clear.assert_called_once()
                mock_send.assert_called_once()

    def test_text_cancel_routes_to_admin_panel_not_generic(self):
        """Ensure the admin cancel path uses admin panel (via exit_admin_awaiting_cancel)."""
        from bot import text_router

        ctx = MagicMock()
        ctx.user_data = {"awaiting": "admin_user_search", "_awaiting_pending": True}
        ctx.bot = AsyncMock()
        update = self._make_text_update("cancel", user_id=1)
        with patch("bot.exit_admin_awaiting_cancel", new=AsyncMock()) as mock_admin_cancel, \
             patch("bot._exit_awaiting_flow", new=AsyncMock()) as mock_generic:
            asyncio.run(text_router(update, ctx))
            mock_admin_cancel.assert_called_once()
            mock_generic.assert_not_called()

    def test_back_user_management_routing(self):
        """admin:back hierarchical: preview/typing -> profile, search -> root."""
        from handlers.admin import _handle_admin_callback
        from config.keyboards.constants import BTN_ADMIN_USER_MANAGE

        # R3: search -> root
        ctx = MagicMock()
        ctx.user_data = {"awaiting": "admin_user_search", "_awaiting_pending": True}
        ctx.bot = AsyncMock()
        q = MagicMock()
        q.data = "admin:back"
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        msg = MagicMock()
        msg.edit_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = q
        update.effective_message = msg
        q.message = msg
        with patch("handlers.admin._edit_or_send", new=AsyncMock()) as mock_edit, \
             patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
             patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
            asyncio.run(_handle_admin_callback(update, ctx, "back"))
            mock_edit.assert_called_once()
            args, kwargs = mock_edit.call_args
            text_arg = args[2] if len(args) > 2 else kwargs.get("text", "")
            self.assertEqual(text_arg, BTN_ADMIN_USER_MANAGE)
            mock_show.assert_not_called()
            self.assertNotIn("awaiting", ctx.user_data)

        # R1/R2: pending and awaiting typing -> profile
        for awaiting_val, pending, expected_uid in [
            ("admin_user_set_plan:42", {}, 42),
            ("admin_user_message:42", {}, 42),
            ("", {"pending_dm": {"user_id": 42, "text": "hi"}}, 42),
            ("", {"pending_plan": {"user_id": 42, "new_plan": "gold"}}, 42),
            ("", {"pending_block": {"user_id": 42}}, 42),
        ]:
            with self.subTest(awaiting=awaiting_val, pending=pending):
                ctx = MagicMock()
                ctx.user_data = {"awaiting": awaiting_val} if awaiting_val else {}
                ctx.user_data.update(pending)
                ctx.user_data["_awaiting_pending"] = True
                ctx.bot = AsyncMock()
                q = MagicMock()
                q.data = "admin:back"
                q.answer = AsyncMock()
                q.edit_message_text = AsyncMock()
                msg = MagicMock()
                msg.edit_text = AsyncMock()
                update = MagicMock()
                update.effective_user.id = 1
                update.effective_chat.id = 1
                update.callback_query = q
                update.effective_message = msg
                q.message = msg
                with patch("handlers.admin._edit_or_send", new=AsyncMock()) as mock_edit, \
                     patch("handlers.admin._clear_awaiting_prompt", new=AsyncMock()), \
                     patch("handlers.admin_users._show_profile", new=AsyncMock()) as mock_show:
                    asyncio.run(_handle_admin_callback(update, ctx, "back"))
                    mock_show.assert_called_once()
                    self.assertEqual(mock_show.call_args[0][2], expected_uid)
                    mock_edit.assert_not_called()
                    self.assertNotIn("pending_dm", ctx.user_data)
                    self.assertNotIn("pending_plan", ctx.user_data)
                    self.assertNotIn("pending_block", ctx.user_data)
                    self.assertNotIn("awaiting", ctx.user_data)


class AwaitingPromptCaptureTest(unittest.TestCase):
    """_store_awaiting_msg must not store button message when msg is None on callback updates."""

    def test_fallback_uses_effective_message_not_callback_query(self):
        """Callback update with msg=None must store nothing (PTB alias guard)."""
        from services.utils.helpers import _store_awaiting_msg

        ctx = MagicMock()
        ctx.user_data = {}
        # msg is None (say() returned None/bool)
        msg = None
        # In PTB effective_message aliases callback_query.message on callback updates
        cb_msg = MagicMock()
        cb_msg.message_id = 999
        cb_chat = MagicMock()
        cb_chat.id = 111
        cb_msg.chat = cb_chat
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.message = cb_msg
        # realistic alias: effective_message is the same object as callback_query.message
        update.effective_message = cb_msg
        update.effective_chat = MagicMock()
        update.effective_chat.id = 111

        _store_awaiting_msg(ctx, update, msg)
        # helpers.py:410 returns early for None/bool msg on callback updates
        # to avoid storing the button message_id; awaiting stays via user_data["awaiting"]
        self.assertNotIn("_awaiting_msg", ctx.user_data)

    def test_fallback_uses_effective_message_when_no_callback(self):
        """Non-callback update with msg=None should fallback to effective_message."""
        from services.utils.helpers import _store_awaiting_msg

        ctx = MagicMock()
        ctx.user_data = {}
        msg = None
        em = MagicMock()
        em.message_id = 555
        em_chat = MagicMock()
        em_chat.id = 111
        em.chat = em_chat
        update = MagicMock()
        update.callback_query = None
        update.effective_message = em
        update.effective_chat = MagicMock()
        update.effective_chat.id = 111

        _store_awaiting_msg(ctx, update, msg)
        self.assertIn("_awaiting_msg", ctx.user_data)
        self.assertEqual(ctx.user_data["_awaiting_msg"]["message_id"], 555)
        self.assertEqual(ctx.user_data["_awaiting_msg"]["chat_id"], 111)

    def test_store_uses_msg_when_available(self):
        from services.utils.helpers import _store_awaiting_msg

        ctx = MagicMock()
        ctx.user_data = {}
        real_msg = MagicMock()
        real_msg.message_id = 123
        real_chat = MagicMock()
        real_chat.id = 456
        real_msg.chat = real_chat
        update = MagicMock()
        update.callback_query = None
        update.effective_message = None
        update.effective_chat = MagicMock()
        update.effective_chat.id = 456

        _store_awaiting_msg(ctx, update, real_msg)
        self.assertEqual(ctx.user_data["_awaiting_msg"]["message_id"], 123)
        self.assertEqual(ctx.user_data["_awaiting_msg"]["chat_id"], 456)

    def test_clear_prompt_badrequest_swallowed_and_logged(self):
        from services.utils.helpers import _clear_awaiting_prompt
        from telegram.error import BadRequest

        ctx = MagicMock()
        ctx.user_data = {"_awaiting_msg": {"chat_id": 1, "message_id": 99}}
        ctx.bot = AsyncMock()

        # BadRequest should be swallowed
        with patch("services.utils.helpers._edit_markup_with_retry", new=AsyncMock(side_effect=BadRequest("oops"))):
            asyncio.run(_clear_awaiting_prompt(ctx))
            self.assertNotIn("_awaiting_msg", ctx.user_data)

        # Other exception should be logged, not swallowed silently
        ctx.user_data = {"_awaiting_msg": {"chat_id": 1, "message_id": 99}}
        with patch("services.utils.helpers._edit_markup_with_retry", new=AsyncMock(side_effect=RuntimeError("boom"))), \
             patch("services.utils.helpers.logger") as mock_logger:
            asyncio.run(_clear_awaiting_prompt(ctx))
            mock_logger.exception.assert_called()


class RobustPresetParsingTest(unittest.TestCase):
    """ai_preset_edit parsing must use split with maxsplit=2."""

    def test_preset_edit_back_parsing(self):
        from handlers.admin import handle_flow_back

        ctx = MagicMock()
        ctx.user_data = {"awaiting": "ai_preset_edit:my_preset:model"}
        ctx.bot = AsyncMock()
        q = MagicMock()
        q.data = "flow:back"
        q.answer = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query = q
        q.message = MagicMock()
        update.effective_message = MagicMock()
        with patch("handlers.admin._edit_ai_preset", new=AsyncMock()) as mock_edit:
            asyncio.run(handle_flow_back(update, ctx))
            mock_edit.assert_called_once()
            args, _ = mock_edit.call_args
            # second arg is preset_name
            self.assertEqual(args[2] if len(args) > 2 else args[1], "my_preset")

    def test_bot_flow_cancel_robust_parsing(self):
        from telegram.error import BadRequest
        import bot as botmod

        ctx = MagicMock()
        ctx.user_data = {
            "awaiting": "ai_preset_edit:my_preset:model",
            "preset_edits": {"my_preset": {"model": "x"}},
            "_awaiting_pending": True,
        }
        ctx.bot = AsyncMock()
        q = MagicMock()
        q.data = "flow:cancel"
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock(side_effect=BadRequest("x"))
        q.message = MagicMock()
        q.message.reply_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = q
        update.effective_message = MagicMock()
        # patch DB calls made by callback_router preamble
        with patch("services.db.reset_user_blocked"), \
             patch("bot._exit_awaiting_flow", new=AsyncMock()) as mock_exit:
            asyncio.run(botmod.callback_router(update, ctx))
            # preset_edits for my_preset should be cleared
            self.assertNotIn("my_preset", ctx.user_data.get("preset_edits", {}))


if __name__ == "__main__":
    unittest.main()
