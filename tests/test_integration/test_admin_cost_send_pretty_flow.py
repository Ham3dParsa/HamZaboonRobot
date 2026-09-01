"""Integration tests for llm-cost dashboard (R3/R4/R5 + send_pretty).

Verifies:
- Backend.RICH rendering with 4-col tables (Name | Req | Avg Cost | Share)
- llm:range:* , llm:breakdown:* , llm:currency:* callbacks route via say/backend RICH
- composite preset_kind breakdown table
- no direct reply_text / bot.send_message wiring regression
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminCostSendPrettyFlowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_message_update(self, text: str = "hello"):
        msg = MagicMock()
        msg.text = text
        msg.reply_text = AsyncMock()
        update = MagicMock()
        update.message = msg
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        update.effective_user = MagicMock()
        update.effective_user.id = 1
        update.callback_query = None
        return update

    def _make_callback_update(self, data: str):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        query.message.message_id = 1
        update = MagicMock()
        update.callback_query = query
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        update.effective_user = MagicMock()
        update.effective_user.id = 1
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    # --- existing wiring ---

    def test_dashboard_without_callback_uses_say_rich(self):
        from handlers.admin_cost import _show_llm_cost_dashboard
        from services.send_pretty import Backend

        update = self._make_message_update()
        ctx = self._make_context()
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_show_llm_cost_dashboard(update, ctx))
            mock_say.assert_called_once()
            _, kwargs = mock_say.call_args
            self.assertEqual(kwargs["backend"], Backend.RICH)
            self.assertEqual(kwargs["mode"], "auto")
            self.assertIn("keyboard", kwargs)

    def test_user_not_found_uses_say_send(self):
        from handlers.admin_cost import _handle_cost_text_input

        update = self._make_message_update("unknown_user_12345")
        ctx = self._make_context()
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_cost_text_input(update, ctx, "llm_cost_user", "unknown_user_12345"))
            mock_say.assert_called_once()
            args, kwargs = mock_say.call_args
            self.assertIn("User not found", args[2])
            from services.send_pretty import RawFormat

            self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
            self.assertEqual(kwargs["mode"], "send")
            self.assertEqual(ctx.user_data["awaiting"], "llm_cost_user")

    def test_invalid_price_rate_uses_say_send(self):
        from handlers.admin_cost import _handle_cost_text_input

        update = self._make_message_update("not_a_number")
        ctx = self._make_context()
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_cost_text_input(update, ctx, "llm_price_rate", "not_a_number"))
            mock_say.assert_called_once()
            args, kwargs = mock_say.call_args
            self.assertIn("عدد معتبر", args[2])
            from services.send_pretty import RawFormat

            self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
            self.assertEqual(kwargs["mode"], "send")

    def test_pricing_text_success_uses_say_send(self):
        from handlers.admin_cost import _handle_cost_text_input

        update = self._make_message_update("65000")
        ctx = self._make_context()
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_cost_text_input(update, ctx, "llm_price_rate", "65000"))
            mock_say.assert_called_once()
            args, kwargs = mock_say.call_args
            # _llm_pricing_text returns "LLM pricing"
            self.assertIn("LLM pricing", args[2])
            from services.send_pretty import RawFormat

            self.assertEqual(kwargs["raw"], RawFormat.PLAIN)
            self.assertEqual(kwargs["mode"], "send")

    def test_wiring_no_direct_reply_text(self):
        text = Path("handlers/admin_cost.py").read_text(encoding="utf-8")
        self.assertNotIn("update.message.reply_text", text)
        self.assertNotIn("update.effective_message.reply_text", text)
        self.assertNotIn("context.bot.send_message", text)

    # --- new: range / breakdown / currency callbacks ---

    def test_range_callback_updates_state_and_renders_rich(self):
        from handlers.admin_cost import _handle_llm_callback
        from services.send_pretty import Backend

        for val in ("today", "7d", "30d", "mtd", "all"):
            update = self._make_callback_update(f"llm:range:{val}")
            ctx = self._make_context()
            with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(_handle_llm_callback(update, ctx, f"llm:range:{val}"))
                mock_say.assert_called_once()
                _, kwargs = mock_say.call_args
                self.assertEqual(kwargs["backend"], Backend.RICH)
                self.assertEqual(ctx.user_data["llm_cost_state"]["range"], val)
                # rendered rich text contains overview heading
                # check content is Message and renders
                content = mock_say.call_args[0][2] if len(mock_say.call_args[0]) > 2 else mock_say.call_args[1].get("content")
                if content is not None:
                    rendered = content.render(Backend.RICH)
                    self.assertIn("LLM Cost", rendered)
                    # hub overview is 2-col card
                    self.assertIn("Metric | Value", rendered)

    def test_breakdown_tabs_each_render_rich_4col(self):
        from handlers.admin_cost import _handle_llm_callback
        from services.send_pretty import Backend

        # seed some data so breakdown tables have rows
        db.add_llm_request(
            user_id=1, plan="free", request_kind="daily_batch", model="gpt-test",
            outcome="success", prompt_tokens=100, completion_tokens=50, total_tokens=150,
            input_cost_usd_per_million=1.0, output_cost_usd_per_million=2.0,
            usd_to_toman_rate=60000, latency_ms=100, preset_name="preset_a",
        )
        db.add_llm_request(
            user_id=1, plan="free", request_kind="custom_word", model="gpt-test",
            outcome="success", prompt_tokens=200, completion_tokens=100, total_tokens=300,
            input_cost_usd_per_million=1.0, output_cost_usd_per_million=2.0,
            usd_to_toman_rate=60000, latency_ms=120, preset_name="preset_b",
        )

        for tab in ("preset", "plan", "kind", "model", "user", "preset_kind"):
            update = self._make_callback_update(f"llm:breakdown:{tab}")
            ctx = self._make_context()
            with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(_handle_llm_callback(update, ctx, f"llm:breakdown:{tab}"))
                mock_say.assert_called_once()
                _, kwargs = mock_say.call_args
                self.assertEqual(kwargs["backend"], Backend.RICH)
                self.assertEqual(ctx.user_data["llm_cost_state"]["breakdown"], tab)
                content = mock_say.call_args[0][2] if len(mock_say.call_args[0]) > 2 else None
                if content is not None:
                    rendered = content.render(Backend.RICH)
                    # 4-col breakdown header must appear (even if no rows, header is present or none placeholder)
                    # For tabs with rows, header is in table; for empty, quote "none" but we seeded data
                    self.assertIn("Name | Req | Avg Cost | Share", rendered)

    def test_currency_callback_updates_state(self):
        from handlers.admin_cost import _handle_llm_callback
        from services.send_pretty import Backend

        for mode in ("usd", "toman", "both"):
            update = self._make_callback_update(f"llm:currency:{mode}")
            ctx = self._make_context()
            with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(_handle_llm_callback(update, ctx, f"llm:currency:{mode}"))
                mock_say.assert_called_once()
                self.assertEqual(ctx.user_data["llm_cost_currency"], mode)
                self.assertEqual(mock_say.call_args[1]["backend"], Backend.RICH)

    def test_preset_kind_composite_bucket(self):
        from handlers.admin_cost import _build_llm_cost_message
        from services.send_pretty import Backend

        db.add_llm_request(
            user_id=1, plan="free", request_kind="daily_batch", model="gpt-test",
            outcome="success", prompt_tokens=100, completion_tokens=50, total_tokens=150,
            input_cost_usd_per_million=1.0, output_cost_usd_per_million=2.0,
            usd_to_toman_rate=60000, latency_ms=100, preset_name="preset_a",
        )
        db.add_llm_request(
            user_id=1, plan="free", request_kind="custom_word", model="gpt-test",
            outcome="success", prompt_tokens=100, completion_tokens=50, total_tokens=150,
            input_cost_usd_per_million=1.0, output_cost_usd_per_million=2.0,
            usd_to_toman_rate=60000, latency_ms=100, preset_name="preset_a",
        )
        state = {"range": "all", "detail": False, "view": "breakdown", "breakdown": "preset_kind", "plan": None, "user_id": None, "request_kind": None, "model": None, "outcome": None}
        msg = _build_llm_cost_message(state, currency_mode="both")
        rendered = msg.render(Backend.RICH)
        # composite bucket format preset:kind (rich escapes underscores)
        self.assertIn("preset\\_a:daily\\_batch", rendered)
        self.assertIn("preset\\_a:custom\\_word", rendered)
        self.assertIn("Name | Req | Avg Cost | Share", rendered)
        # hub: breakdown view shows Filters pill, not overview 4-col
        self.assertIn("Filters:", rendered)

    def test_custom_range_rejected_as_invalid(self):
        from handlers.admin_cost import _handle_llm_callback

        update = self._make_callback_update("llm:range:custom")
        ctx = self._make_context()
        with patch("handlers.admin_cost.notify_callback", new=AsyncMock()) as mock_notify:
            with patch("handlers.admin_cost.say", new=AsyncMock()) as mock_say:
                asyncio.run(_handle_llm_callback(update, ctx, "llm:range:custom"))
                mock_say.assert_not_called()
                mock_notify.assert_called_once()

    def test_legend_callback_shows_legend(self):
        from unittest.mock import AsyncMock, patch
        import asyncio

        from handlers.admin_cost import _handle_llm_callback
        from telegram import InlineKeyboardMarkup

        update = self._make_callback_update("llm:legend")
        ctx = self._make_context()
        with patch("handlers.admin_cost._edit_or_send", new=AsyncMock()) as mock_edit:
            asyncio.run(_handle_llm_callback(update, ctx, "llm:legend"))
            mock_edit.assert_called_once()
            args = mock_edit.call_args[0]
            kwargs = mock_edit.call_args[1]
            text = args[2] if len(args) > 2 else kwargs.get("text", "")
            self.assertIn("راهنما", text)
            self.assertIn("✅ موفق", text)
            self.assertIsInstance(kwargs["reply_markup"], InlineKeyboardMarkup)
            all_data = [btn.callback_data for row in kwargs["reply_markup"].inline_keyboard for btn in row]
            self.assertIn("llm:refresh", all_data)

    def test_dashboard_keyboard_contains_legend(self):
        from config.keyboards.admin import llm_cost_dashboard_keyboard

        kb = llm_cost_dashboard_keyboard()
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("llm:legend", all_data)

    def test_view_tabs_switch_view(self):
        from handlers.admin_cost import _handle_llm_callback
        from services.send_pretty import Backend

        for view in ("overview", "breakdown", "recent"):
            update = self._make_callback_update(f"llm:view:{view}")
            ctx = self._make_context()
            with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
                asyncio.run(_handle_llm_callback(update, ctx, f"llm:view:{view}"))
                mock_say.assert_called_once()
                self.assertEqual(ctx.user_data["llm_cost_state"]["view"], view)
                self.assertEqual(mock_say.call_args[1]["backend"], Backend.RICH)
                content = mock_say.call_args[0][2] if len(mock_say.call_args[0]) > 2 else None
                if content is not None:
                    rendered = content.render(Backend.RICH)
                    self.assertIn("LLM Cost", rendered)

    def test_page_breakdown_pager_and_clamp(self):
        from handlers.admin_cost import _handle_llm_callback
        from services.send_pretty import Backend

        # seed 6 presets to get 2 pages (5pp)
        for i in range(6):
            db.add_llm_request(
                user_id=1, plan="free", request_kind="daily_batch", model="gpt-test",
                outcome="success", prompt_tokens=10, completion_tokens=10, total_tokens=20,
                input_cost_usd_per_million=1.0, output_cost_usd_per_million=1.0,
                usd_to_toman_rate=60000, latency_ms=10, preset_name=f"preset_{i}",
            )
        ctx = self._make_context()
        ctx.user_data["llm_cost_state"] = {"range": "all", "view": "breakdown", "breakdown": "preset", "breakdown_page": 0, "detail": False}
        # go to page 1
        update = self._make_callback_update("llm:page:breakdown:1")
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_llm_callback(update, ctx, "llm:page:breakdown:1"))
            self.assertEqual(ctx.user_data["llm_cost_state"]["breakdown_page"], 1)
        # 999 stored as 999 (clamped for display to last page via builder/_show, no duplicate COUNT)
        update2 = self._make_callback_update("llm:page:breakdown:999")
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_llm_callback(update2, ctx, "llm:page:breakdown:999"))
            self.assertEqual(ctx.user_data["llm_cost_state"]["breakdown_page"], 999)

    def test_page_recent_pager_and_clamp(self):
        from handlers.admin_cost import _handle_llm_callback

        for i in range(9):
            db.add_llm_request(
                user_id=1, plan="free", request_kind="custom_word", model="gpt-test",
                outcome="success", prompt_tokens=10, completion_tokens=10, total_tokens=20,
                input_cost_usd_per_million=1.0, output_cost_usd_per_million=1.0,
                usd_to_toman_rate=60000, latency_ms=10, preset_name="preset_a",
            )
        ctx = self._make_context()
        ctx.user_data["llm_cost_state"] = {"range": "all", "view": "recent", "recent_page": 0, "detail": True}
        update = self._make_callback_update("llm:page:recent:1")
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_llm_callback(update, ctx, "llm:page:recent:1"))
            self.assertEqual(ctx.user_data["llm_cost_state"]["recent_page"], 1)
        update2 = self._make_callback_update("llm:page:recent:999")
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")) as mock_say:
            asyncio.run(_handle_llm_callback(update2, ctx, "llm:page:recent:999"))
            self.assertEqual(ctx.user_data["llm_cost_state"]["recent_page"], 999)

    def test_projection_toggle(self):
        from handlers.admin_cost import _handle_llm_callback

        ctx = self._make_context()
        ctx.user_data["llm_cost_state"] = {"range": "mtd", "view": "overview", "show_projection": False}
        update = self._make_callback_update("llm:projection")
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")):
            asyncio.run(_handle_llm_callback(update, ctx, "llm:projection"))
            self.assertTrue(ctx.user_data["llm_cost_state"]["show_projection"])
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")):
            asyncio.run(_handle_llm_callback(update, ctx, "llm:projection"))
            self.assertFalse(ctx.user_data["llm_cost_state"]["show_projection"])

    def test_currency_cycle(self):
        from handlers.admin_cost import _handle_llm_callback

        ctx = self._make_context()
        ctx.user_data["llm_cost_currency"] = "both"
        update = self._make_callback_update("llm:currency:cycle")
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")):
            asyncio.run(_handle_llm_callback(update, ctx, "llm:currency:cycle"))
            self.assertEqual(ctx.user_data["llm_cost_currency"], "usd")
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")):
            asyncio.run(_handle_llm_callback(update, ctx, "llm:currency:cycle"))
            self.assertEqual(ctx.user_data["llm_cost_currency"], "toman")
        with patch("handlers.admin_cost.say", new=AsyncMock(return_value="sent")):
            asyncio.run(_handle_llm_callback(update, ctx, "llm:currency:cycle"))
            self.assertEqual(ctx.user_data["llm_cost_currency"], "both")

    def test_noop_callback(self):
        from handlers.admin_cost import _handle_llm_callback

        update = self._make_callback_update("llm:noop")
        ctx = self._make_context()
        with patch("handlers.admin_cost.notify_callback", new=AsyncMock()) as mock_notify:
            with patch("handlers.admin_cost.say", new=AsyncMock()) as mock_say:
                asyncio.run(_handle_llm_callback(update, ctx, "llm:noop"))
                mock_notify.assert_called_once()
                mock_say.assert_not_called()


if __name__ == "__main__":
    unittest.main()
