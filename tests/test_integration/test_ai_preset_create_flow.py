"""Integration tests for the R14 AI-preset create flow.

The create flow (after entering a new preset name) prompts for a fallback-chain
priority via an inline keyboard, prompts for enabled status plus a lightweight
ping test, then presents a create summary with an inline test and an enable
toggle before continuing into the full-edit wizard.

Defaults (R14): a new preset is created disabled and appended at the lowest
priority unless the owner explicitly chooses otherwise at the prompts.

These tests dispatch through the real ``_handle_admin_callback`` ->
``handle_ai_callback`` path and assert Telegram output, the emitted keyboard
callback prefixes, and the resulting DB row.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AiPresetCreateFlowTest(unittest.TestCase):
    """Create-flow priority/status/summary steps routed through the admin router."""

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
            "existing_gpt",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
            priority=0,
        )
        # Phase 4 (R3: no auto-seed): seed a deep-enough fallback chain so the
        # manual-priority tests can enter ranks that exceed the previous empty
        # chain without being clamped to max_rank.
        for i in range(1, 7):
            db.set_preset(
                f"chain_{i}",
                base_url="https://api.example.com",
                model="gpt-test",
                api_key="test",
                in_fallback_chain=1,
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

    def _make_message_update(self, text: str, user_id: int = 1):
        message = MagicMock()
        message.text = text
        message.reply_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.message = message
        update.callback_query = None
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def _new_flow(self):
        self.flow_ctx = self._make_context()
        return self.flow_ctx

    def _enter_name(self, name: str):
        return self._text(self.flow_ctx, "admin_ai_preset_new_name", name)

    def _text(self, ctx, awaiting: str, text: str):
        from handlers.flows import text_router as flows_text_router

        update = self._make_message_update(text)
        asyncio.run(flows_text_router(update, ctx, awaiting, text))
        return update

    def _callback(self, action: str):
        from handlers.admin import _handle_admin_callback

        data = f"admin:{action}"
        update = self._make_callback_update(data)
        asyncio.run(_handle_admin_callback(update, self.flow_ctx, action))
        return update

    def test_create_flow_defaults_disabled_and_lowest_priority(self):
        """R14: after entering a name, priority prompt is shown; choosing bottom
        and leaving status creates a disabled preset at the lowest priority."""
        self._new_flow()
        update = self._enter_name("my_new_preset")

        priority_markup = update.message.reply_text.call_args.kwargs.get("reply_markup")
        data = priority_markup.to_json() if priority_markup else ""
        self.assertIn("ai_preset:create:priority", data)

        up = self._callback("ai_preset:create:priority:bottom")
        status_json = up.callback_query.edit_message_text.call_args.kwargs["reply_markup"].to_json()
        self.assertIn("ai_preset:create:status", status_json)
        # Status screen must not offer test before fields are filled (bug fix)
        self.assertNotIn("ai_preset:create:test", status_json)

        up = self._callback("ai_preset:create:status:off")
        created = db.get_preset("my_new_preset")
        self.assertIsNotNone(created, "preset must be persisted after create flow")
        self.assertEqual(created["enabled"], 0, "R14 default: new preset is disabled")
        chain = db.get_fallback_chain_presets()
        expected = max(int(p.get("priority", 0)) for p in chain if p["name"] != "my_new_preset") + 1
        self.assertEqual(created["priority"], expected, "bottom => lowest priority (max existing + 1)")
        summary_json = up.callback_query.edit_message_text.call_args.kwargs["reply_markup"].to_json()
        # Incomplete preset must not expose test, only full edit + toggle
        self.assertNotIn("ai_preset:create:test", summary_json)
        self.assertIn("ai_preset:create:toggle_enable", summary_json)
        self.assertIn("full_edit", summary_json)

    def test_create_flow_priority_top_sets_zero(self):
        """Choosing top sets the highest priority (0)."""
        self._new_flow()
        self._enter_name("top_preset")
        self._callback("ai_preset:create:priority:top")
        self._callback("ai_preset:create:status:on")
        created = db.get_preset("top_preset")
        self.assertEqual(created["priority"], 0)
        self.assertEqual(created["enabled"], 1, "explicit on overrides the disabled default")

    def test_create_flow_manual_priority_number(self):
        """Choosing manual priority enters a text-awaiting state and applies the number."""
        self._new_flow()
        self._enter_name("manual_preset")
        self._callback("ai_preset:create:priority:manual")
        self.assertIn("ai_preset_create_priority", self.flow_ctx.user_data["awaiting"])

        self._text(self.flow_ctx, "ai_preset_create_priority:manual_preset", "5")
        self._callback("ai_preset:create:status:on")
        created = db.get_preset("manual_preset")
        self.assertEqual(created["priority"], 5)

    def test_create_flow_enable_toggle_on_summary(self):
        """The summary enable toggle flips the just-created preset's status."""
        self._new_flow()
        self._enter_name("toggled_preset")
        self._callback("ai_preset:create:priority:bottom")
        self._callback("ai_preset:create:status:off")
        self.assertEqual(db.get_preset("toggled_preset")["enabled"], 0)
        self._callback("ai_preset:create:toggle_enable")
        self.assertEqual(db.get_preset("toggled_preset")["enabled"], 1)

    def test_create_flow_manual_rank_clamped_to_last(self):
        """A manual rank larger than the chain size is clamped to the lowest slot."""
        self._new_flow()
        self._enter_name("clamped_preset")
        self._callback("ai_preset:create:priority:manual")
        self._text(self.flow_ctx, "ai_preset_create_priority:clamped_preset", "999")
        self._callback("ai_preset:create:status:on")
        created = db.get_preset("clamped_preset")
        max_rank = sum(
            1 for p in db.get_fallback_chain_presets()
            if not p.get("is_emergency") and p["name"] != "clamped_preset"
        )
        self.assertEqual(created["priority"], max_rank, "out-of-range manual rank clamps to last slot")

    def test_create_test_incomplete_shows_full_edit_hint(self):
        """Incomplete preset (no base_url/model/key) must not run real test, shows full-edit hint."""
        self._new_flow()
        self._enter_name("incomplete_preset")
        self._callback("ai_preset:create:priority:bottom")
        self._callback("ai_preset:create:status:off")
        # Drive the create:test callback while still incomplete - must not call live network
        with patch("services.ai.ai.test_connection") as mock_test:
            up = self._callback("ai_preset:create:test")
            mock_test.assert_not_called()
            kwargs = up.callback_query.edit_message_text.call_args.kwargs
            # The warning is rendered and offers full edit
            self.assertIn("full_edit", str(kwargs.get("reply_markup").to_json()))

    def test_finish_create_guards_empty_state_no_row_created(self):
        """Kilo R7: a lost/stale create state must not persist an empty-PK preset."""
        from services import db as sdb

        before = len(sdb.get_presets())
        self._new_flow()
        # No name was ever entered; drive _finish_create via a stale status choice.
        self._callback("ai_preset:create:status:on")
        self.assertEqual(len(sdb.get_presets()), before, "no empty-primary-key preset row may be created")

    def test_finish_create_guards_missing_row(self):
        """Kilo R7: a toggle on a deleted preset must not recreate an empty row."""
        from services import db as sdb

        self._new_flow()
        self._enter_name("gone_preset")
        self._callback("ai_preset:create:priority:bottom")
        self._callback("ai_preset:create:status:on")
        self.assertIsNotNone(sdb.get_preset("gone_preset"))
        sdb.delete_preset("gone_preset")
        before = len(sdb.get_presets())
        # A stale toggle button still in the chat re-enters the summary step.
        self._callback("ai_preset:create:toggle_enable")
        self.assertEqual(len(sdb.get_presets()), before, "must not recreate a deleted preset")


class AiPresetDetailAndActivateTest(unittest.TestCase):
    """Detail view test button and auto-enable-on-activate (reviewer must-fix)."""

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
        self.flow_ctx = self._make_context()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

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

    def _callback(self, action: str):
        from handlers.admin import _handle_admin_callback

        data = f"admin:{action}"
        update = self._make_callback_update(data)
        asyncio.run(_handle_admin_callback(update, self.flow_ctx, action))
        return update

    def test_detail_view_has_test_button(self):
        db.set_preset("view_test", base_url="https://x", model="m", api_key="sk-test")
        # Drive to detail view via view callback
        from services.utils.callback_codec import preset_token

        up = self._callback(f"ai_preset:view:{preset_token('view_test')}")
        markup = up.callback_query.edit_message_text.call_args.kwargs["reply_markup"].to_json()
        self.assertIn("ai_preset:test:", markup)

    def test_detail_test_incomplete_shows_hint(self):
        db.set_preset("incomplete_detail", base_url="", model="", api_key="")
        from services.utils.callback_codec import preset_token

        with patch("services.ai.ai.test_connection") as mock_test:
            up = self._callback(f"ai_preset:test:{preset_token('incomplete_detail')}")
            mock_test.assert_not_called()
            text = up.callback_query.edit_message_text.call_args.args[0]
            self.assertIn("کامل نیست", text)

    def test_detail_test_success_branch(self):
        db.set_preset("complete_detail", base_url="https://x", model="m", api_key="sk-test")
        from services.utils.callback_codec import preset_token

        with patch("services.ai.ai.test_connection", return_value={"success": True, "latency_ms": 42}) as mock_test:
            up = self._callback(f"ai_preset:test:{preset_token('complete_detail')}")
            mock_test.assert_called_once()
            text = up.callback_query.edit_message_text.call_args.args[0]
            self.assertIn("اتصال موفق", text)

    def test_activate_disabled_auto_enables(self):
        # New presets are created disabled; activate should auto-enable and set primary
        db.set_preset("to_activate", base_url="https://x", model="m", api_key="sk-test", enabled=0)
        self.assertEqual(db.get_preset("to_activate")["enabled"], 0)
        from services.utils.callback_codec import preset_token

        self._callback(f"ai_preset:activate:{preset_token('to_activate')}")
        preset = db.get_preset("to_activate")
        self.assertEqual(preset["enabled"], 1, "activate must auto-enable disabled preset")
        self.assertEqual(db.get_active_preset_name(), "to_activate")

    def test_activate_failure_return_false_shows_error(self):
        db.set_preset("fail_preset", base_url="https://x", model="m", api_key="sk-test", enabled=1)
        from services.utils.callback_codec import preset_token

        with patch("services.db.preset_registry.activate_preset", return_value=False):
            up = self._callback(f"ai_preset:activate:{preset_token('fail_preset')}")
            # Should have answered with error and re-rendered view
            self.assertTrue(up.callback_query.answer.called)
            self.assertTrue(up.callback_query.edit_message_text.called)

    def test_activate_failure_raises_shows_error(self):
        db.set_preset("raise_preset", base_url="https://x", model="m", api_key="sk-test", enabled=1)
        from services.utils.callback_codec import preset_token

        with patch("services.db.preset_registry.activate_preset", side_effect=RuntimeError("boom")):
            up = self._callback(f"ai_preset:activate:{preset_token('raise_preset')}")
            self.assertTrue(up.callback_query.answer.called)
            self.assertTrue(up.callback_query.edit_message_text.called)


if __name__ == "__main__":
    unittest.main()