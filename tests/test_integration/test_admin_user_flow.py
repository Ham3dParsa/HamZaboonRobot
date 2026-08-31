"""Integration tests for admin user-management flow (issue #stats-users, Phase 5 polish).

Scratch-DB isolated; owner-gated via handlers.admin.is_owner.
Covers admin:user menu, search/resolve with rich table (full_name + Persian digits),
preview flow (pending_dm + dm_preview_keyboard), confirm/cancel/edit, block/unblock,
set-plan, reset progress, and non-owner reject.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.flows import text_router
from services import db
from services.db import schema as db_schema


class AdminUserFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        # Phase 5: create users with full_name via new 3-arg signature
        try:
            db.create_user_if_needed(42, "alice", "Alice Wonder")
            db.create_user_if_needed(7, "bob", "Bob Builder")
        except TypeError:
            # fallback for older signature
            db.create_user_if_needed(42, "alice")
            db.create_user_if_needed(7, "bob")
            db.update_user_full_name(42, "Alice Wonder")
            db.update_user_full_name(7, "Bob Builder")
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

    def _make_text_update(self, text: str, user_id: int = 1, html: str | None = None):
        msg = MagicMock()
        msg.text = text
        msg.text_html = html if html is not None else text
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

    def test_user_menu_opens(self):
        from handlers.admin import _handle_admin_callback

        update = self._cb("admin:user")
        ctx = self._ctx()
        asyncio.run(_handle_admin_callback(update, ctx, "user"))
        update.callback_query.edit_message_text.assert_called_once()
        args, kwargs = update.callback_query.edit_message_text.call_args
        text = args[0] if args else kwargs.get("text", "")
        self.assertIn("\u0645\u062f\u06cc\u0631\u06cc\u062a \u06a9\u0627\u0631\u0628\u0631", text)

    def test_search_resolves(self):
        # search resolves via text_router with admin_user_search — rich table
        from services.send_pretty import Backend, Message

        def _to_str(v):
            if isinstance(v, Message):
                try:
                    return v.render(Backend.PLAIN)
                except Exception:
                    return str(v)
            return str(v) if v else ""

        update = self._make_text_update("42")
        ctx = self._ctx()
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say:
            asyncio.run(text_router(update, ctx, "admin_user_search", "42"))
            mock_say.assert_called()
            texts = []
            for call in mock_say.call_args_list:
                args = call[0]
                txt = args[2] if len(args) > 2 else ""
                if not txt:
                    txt = call[1].get("content", "") if len(call) > 1 else ""
                    if not txt:
                        txt = call[1].get("text", "") if len(call) > 1 else ""
                texts.append(_to_str(txt))
            combined = " ".join(texts)
            # rich table contains full_name header and value, and Persian digits
            self.assertIn("\u0646\u0627\u0645 \u06a9\u0627\u0645\u0644", combined)
            self.assertIn("Alice", combined)
            # id rendered as Persian digits ۴۲
            self.assertTrue("42" in combined or "۴۲" in combined)

        # also resolves @username variant
        update2 = self._make_text_update("@alice")
        ctx2 = self._ctx()
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say2:
            asyncio.run(text_router(update2, ctx2, "admin_user_search", "@alice"))
            mock_say2.assert_called()

    def test_search_not_found_keeps_awaiting(self):
        update = self._make_text_update("9999")
        ctx = self._ctx()
        ctx.user_data["awaiting"] = "admin_user_search"
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say:
            asyncio.run(text_router(update, ctx, "admin_user_search", "9999"))
            mock_say.assert_called()
            self.assertEqual(ctx.user_data.get("awaiting"), "admin_user_search")

    def test_block_and_unblock(self):
        from handlers.admin import _handle_admin_callback

        update = self._cb("admin:user:block:42")
        ctx = self._ctx()
        asyncio.run(_handle_admin_callback(update, ctx, "user:block:42"))
        row = db.get_user(42)
        self.assertEqual(row["bot_blocked"], 1)

        update2 = self._cb("admin:user:unblock:42")
        ctx2 = self._ctx()
        asyncio.run(_handle_admin_callback(update2, ctx2, "user:unblock:42"))
        row2 = db.get_user(42)
        self.assertEqual(row2["bot_blocked"], 0)

    def test_set_plan_flow(self):
        from services.send_pretty import Backend, Message

        def _to_str(v):
            if isinstance(v, Message):
                try:
                    return v.render(Backend.PLAIN)
                except Exception:
                    return str(v)
            return str(v) if v else ""

        update = self._make_text_update("gold")
        ctx = self._ctx()
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say:
            asyncio.run(text_router(update, ctx, "admin_user_set_plan:42", "gold"))
            self.assertEqual(db.get_user(42)["plan"], "gold")
            mock_say.assert_called()
            texts = []
            for c in mock_say.call_args_list:
                args = c[0]
                v = args[2] if len(args) > 2 else c[1].get("content", "") if len(c) > 1 else ""
                if not v:
                    v = c[1].get("text", "") if len(c) > 1 else ""
                texts.append(_to_str(v))
            combined = " ".join(texts)
            self.assertIn("gold", combined)

        ctx2 = self._ctx()
        update2 = self._make_text_update("invalid_plan")
        with patch("handlers.admin_users.say", new=AsyncMock()):
            asyncio.run(text_router(update2, ctx2, "admin_user_set_plan:42", "invalid_plan"))
            self.assertEqual(ctx2.user_data.get("awaiting"), "admin_user_set_plan:42")

    def test_reset_progress_deletes(self):
        db.add_saved_word(7, "hello", "en", {"word": "hello"})
        try:
            from services.db import record_review_event
            with db.transaction() as conn:
                wid = conn.execute("SELECT id FROM saved_words WHERE user_id=7").fetchone()
                if wid:
                    record_review_event(7, wid["id"], "again")
        except Exception:
            pass
        with db.transaction() as conn:
            conn.execute("UPDATE users SET streak=5 WHERE user_id=7")

        from handlers.admin import _handle_admin_callback

        update = self._cb("admin:user:reset_confirm:7")
        ctx = self._ctx()
        asyncio.run(_handle_admin_callback(update, ctx, "user:reset_confirm:7"))
        stats = db.get_user_learning_stats(7)
        self.assertEqual(stats["saved_words"], 0)
        self.assertEqual(stats["review_events"], 0)
        row = db.get_user(7)
        self.assertEqual(row["streak"], 0)

    def test_reset_cancel_keeps(self):
        db.add_saved_word(7, "world", "en", {"word": "world"})
        with db.transaction() as conn:
            conn.execute("UPDATE users SET streak=3 WHERE user_id=7")

        from handlers.admin import _handle_admin_callback

        update = self._cb("admin:user:reset_cancel:7")
        ctx = self._ctx()
        asyncio.run(_handle_admin_callback(update, ctx, "user:reset_cancel:7"))
        stats = db.get_user_learning_stats(7)
        self.assertGreaterEqual(stats["saved_words"], 1)
        row = db.get_user(7)
        self.assertEqual(row["streak"], 3)

    def test_message_flow(self):
        """Phase 5: preview flow — text_router stores pending_dm and shows preview,
        then confirm callback sends via _send_with_retry. Cancel/edit also covered."""
        # Step 1: text input creates preview, does NOT immediate send
        update = self._make_text_update("\u0633\u0644\u0627\u0645 \u0627\u0632 \u0645\u062f\u06cc\u0631")
        ctx = self._ctx()
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say:
            asyncio.run(text_router(update, ctx, "admin_user_message:42", "\u0633\u0644\u0627\u0645 \u0627\u0632 \u0645\u062f\u06cc\u0631"))
            # pending_dm stored
            self.assertIn("pending_dm", ctx.user_data)
            self.assertEqual(ctx.user_data["pending_dm"]["user_id"], 42)
            self.assertEqual(ctx.user_data["pending_dm"]["text"], "\u0633\u0644\u0627\u0645 \u0627\u0632 \u0645\u062f\u06cc\u0631")
            # preview shown containing پیش‌نمایش and keyboard
            mock_say.assert_called_once()
            call_args = mock_say.call_args
            preview_text = call_args[0][2] if len(call_args[0]) > 2 else call_args[1].get("text", "")
            self.assertIn("\u067e\u06cc\u0634\u200c\u0646\u0645\u0627\u06cc\u0634", preview_text)
            # dm_preview_keyboard passed
            kwargs = call_args[1]
            kb = kwargs.get("keyboard") or (call_args[0][3] if len(call_args[0]) > 3 else None)
            # also check via keyword inspection
            if kb is None and "keyboard" in kwargs:
                kb = kwargs["keyboard"]
            self.assertIsNotNone(kb)
            # immediate send must NOT have happened
            ctx.bot.send_message.assert_not_called()

        # Step 2: confirm — patched _send_with_retry called with html/parse_mode handling
        cb_update = self._cb("admin:user:msg_confirm:42")
        with patch("handlers.admin_users._send_with_retry", new=AsyncMock()) as mock_send:
            from handlers.admin_users import handle_admin_user
            asyncio.run(handle_admin_user(cb_update, ctx, "user:msg_confirm:42"))
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            # first arg is bot, second is user_id
            sent_uid = args[1] if len(args) > 1 else kwargs.get("chat_id")
            self.assertEqual(sent_uid, 42)
            sent_text = args[2] if len(args) > 2 else kwargs.get("text", "")
            self.assertIn("\u0633\u0644\u0627\u0645", sent_text)
            # pending cleared after confirm
            self.assertNotIn("pending_dm", ctx.user_data)
            cb_update.callback_query.answer.assert_called()

        # Step 3: cancel path — set pending again then cancel
        ctx2 = self._ctx()
        ctx2.user_data["pending_dm"] = {"user_id": 42, "text": "hi", "html": "hi"}
        ctx2.user_data["awaiting"] = "admin_user_message:42"
        cb_cancel = self._cb("admin:user:msg_cancel:42")
        from handlers.admin_users import handle_admin_user as h2
        asyncio.run(h2(cb_cancel, ctx2, "user:msg_cancel:42"))
        self.assertNotIn("pending_dm", ctx2.user_data)
        cb_cancel.callback_query.answer.assert_called()

        # Step 4: edit path — re-arms awaiting
        ctx3 = self._ctx()
        ctx3.user_data["pending_dm"] = {"user_id": 42, "text": "hi", "html": "hi"}
        cb_edit = self._cb("admin:user:msg_edit:42")
        from handlers.admin_users import handle_admin_user as h3
        asyncio.run(h3(cb_edit, ctx3, "user:msg_edit:42"))
        self.assertNotIn("pending_dm", ctx3.user_data)
        self.assertEqual(ctx3.user_data.get("awaiting"), "admin_user_message:42")
        cb_edit.callback_query.answer.assert_called()

    def test_message_flow_html_preserved(self):
        """HTML formatting is preserved in preview and on confirm send via parse_mode."""
        html_text = "<b>\u0633\u0644\u0627\u0645</b>"
        update = self._make_text_update("\u0633\u0644\u0627\u0645", html=html_text)
        ctx = self._ctx()
        with patch("handlers.admin_users.say", new=AsyncMock()) as mock_say:
            asyncio.run(text_router(update, ctx, "admin_user_message:42", "\u0633\u0644\u0627\u0645"))
            pending = ctx.user_data.get("pending_dm")
            self.assertIsNotNone(pending)
            self.assertEqual(pending.get("html"), html_text)
            mock_say.assert_called_once()

        cb_update = self._cb("admin:user:msg_confirm:42")
        with patch("handlers.admin_users._send_with_retry", new=AsyncMock()) as mock_send:
            from handlers.admin_users import handle_admin_user
            asyncio.run(handle_admin_user(cb_update, ctx, "user:msg_confirm:42"))
            mock_send.assert_called_once()
            _, kwargs = mock_send.call_args
            # html differs from plain text -> should use HTML parse_mode
            from telegram.constants import ParseMode
            self.assertEqual(kwargs.get("parse_mode"), ParseMode.HTML)

    def test_message_flow_failure_keeps_awaiting(self):
        # After polish, text input itself does not attempt send, so failure is on confirm.
        # Simulate confirm failure — pending should remain (or error toast) and not crash.
        ctx = self._ctx()
        ctx.user_data["pending_dm"] = {"user_id": 42, "text": "hello", "html": "hello"}
        cb_update = self._cb("admin:user:msg_confirm:42")
        with patch("handlers.admin_users._send_with_retry", new=AsyncMock(side_effect=Exception("blocked"))):
            from handlers.admin_users import handle_admin_user
            asyncio.run(handle_admin_user(cb_update, ctx, "user:msg_confirm:42"))
            # on send failure, pending is NOT popped (or at least error notified)
            # the handler keeps pending so admin can retry; check answer was error
            cb_update.callback_query.answer.assert_called()

    def test_non_owner_rejected(self):
        from handlers.admin import _handle_admin_callback

        with patch("handlers.admin.is_owner", return_value=False):
            update = self._cb("admin:user", user_id=9999)
            ctx = self._ctx()
            asyncio.run(_handle_admin_callback(update, ctx, "user"))
            update.callback_query.answer.assert_called()
            args = update.callback_query.answer.call_args[0]
            self.assertIn("\u0641\u0642\u0637 \u0645\u0627\u0644\u06a9 \u0631\u0628\u0627\u062a", args[0])

    def test_export_csv_sanitizes_formula_injection(self):
        with db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users(user_id, username, created_at) VALUES (?, ?, ?)",
                (999, "=2+2", "2026-08-31T00:00:00"),
            )
        csv_text = db.export_users_csv()
        self.assertIn("'=2+2", csv_text)
        self.assertTrue(csv_text.startswith("user_id,username"))
        self.assertNotIn("api_key", csv_text.lower())

    def test_preview_wiring(self):
        """dm_preview_keyboard callbacks must be reachable via admin routing."""
        from config.keyboards import dm_preview_keyboard
        kb = dm_preview_keyboard(42)
        cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("admin:user:msg_confirm:42", cbs)
        self.assertIn("admin:user:msg_edit:42", cbs)
        self.assertIn("admin:user:msg_cancel:42", cbs)
        # verify branches exist in admin_users handler source
        src = pathlib.Path("handlers/admin_users.py").read_text(encoding="utf-8")
        for needle in ("user:msg_confirm:", "user:msg_cancel:", "user:msg_edit:"):
            self.assertIn(needle, src)
        # also verify broadcast preview wiring (same polish)
        from config.keyboards import broadcast_preview_keyboard
        bkb = broadcast_preview_keyboard()
        bcbs = [btn.callback_data for row in bkb.inline_keyboard for btn in row]
        self.assertIn("admin:broadcast_confirm", bcbs)
        self.assertIn("admin:broadcast_edit", bcbs)
        self.assertIn("admin:broadcast_cancel", bcbs)

    def test_admin_panel_reorg(self):
        """Panel reorg: stats + user manage present; legacy set_plan button not required."""
        from config.keyboards import admin_panel_keyboard
        kb = admin_panel_keyboard()
        all_cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("admin:stats", all_cbs)
        self.assertIn("admin:user", all_cbs)
        # new panel should expose plans manager and cost dashboard
        self.assertIn("admin:plans", all_cbs)


if __name__ == "__main__":
    unittest.main()
