"""Integration tests for admin_ai preset field-label canonicalization (#342)
and the field-edit back-button / keyboard-consistency fixes (#343, systemic).

Dispatches through the real ``_handle_admin_callback`` -> ``handle_ai_callback``
and the handlers.flows text_router path and asserts Telegram output, the emitted
keyboard callback prefixes, and user_data state.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class _AiPresetLabelsAndBackBase(unittest.TestCase):
    """Scratch-DB harness shared by the label + back-button flow tests."""

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
            "custom_gpt",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
            priority=0,
        )
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
        update.message = None
        return update

    def _make_message_update(self, text: str, user_id: int = 1):
        message = MagicMock()
        message.text = text
        message.reply_text = AsyncMock()
        message.delete = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.message = message
        update.callback_query = None
        return update

    def _callback(self, action: str):
        from handlers.admin import _handle_admin_callback

        update = self._make_callback_update(f"admin:{action}")
        asyncio.run(_handle_admin_callback(update, self.flow_ctx, action))
        return update

    def _text(self, awaiting: str, text: str):
        from handlers.flows import text_router as flows_text_router

        update = self._make_message_update(text)
        asyncio.run(flows_text_router(update, self.flow_ctx, awaiting, text))
        return update

    def _markup(self, call_args):
        return call_args.kwargs["reply_markup"].to_json()


class AiPresetFieldEditBackTest(_AiPresetLabelsAndBackBase):
    """#343 Rule 3: field-edit initial prompt emits flow:back; Back resumes the
    preset-edit menu and preserves unsaved edits."""

    def test_field_edit_initial_prompt_uses_flow_back(self):
        from handlers.admin_ai import _edit_ai_preset_field

        update = self._make_callback_update("x")
        asyncio.run(_edit_ai_preset_field(update, self.flow_ctx, "custom_gpt", "model"))
        markup = self._markup(update.callback_query.edit_message_text.call_args)
        self.assertIn("flow:back", markup)
        self.assertNotIn("admin:back", markup)

    def test_field_edit_flow_back_resumes_edit_and_keeps_edits(self):
        from handlers.admin import handle_flow_back
        from handlers.admin_ai import _edit_ai_preset_field

        # Begin a field edit, then commit an unsaved value into preset_edits.
        self.flow_ctx.user_data["preset_edits"] = {"custom_gpt": {"model": "gpt-4o"}}
        asyncio.run(_edit_ai_preset_field(update := self._make_callback_update("x"), self.flow_ctx, "custom_gpt", "model"))
        self.assertEqual(self.flow_ctx.user_data["awaiting"], "ai_preset_edit:custom_gpt:model")

        # Dispatch flow:back -> handle_flow_back.
        back_update = self._make_callback_update("flow:back")
        asyncio.run(handle_flow_back(back_update, self.flow_ctx))

        # Back must return to the preset-edit menu, not the main admin panel.
        self.assertNotIn("awaiting", self.flow_ctx.user_data)
        text = back_update.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("custom_gpt", text)
        self.assertIn("انتخاب فیلد برای تغییر", text)
        # Unsaved edits must be preserved.
        self.assertEqual(self.flow_ctx.user_data["preset_edits"], {"custom_gpt": {"model": "gpt-4o"}})


class AiPresetCreateNameBackTest(_AiPresetLabelsAndBackBase):
    """#343 Rule 4 #2: create-preset-name error retry stays in the admin panel
    (admin:back), consistent with the initial prompt."""

    def test_create_name_error_retry_uses_admin_awaiting(self):
        self.flow_ctx.user_data["awaiting"] = "admin_ai_preset_new_name"
        up = self._text("admin_ai_preset_new_name", "INVALID NAME!!")
        markup = self._markup(up.message.reply_text.call_args)
        self.assertIn("admin:back", markup)
        self.assertNotIn("flow:back", markup)


class AiPresetFullEditErrorRetryTest(_AiPresetLabelsAndBackBase):
    """#343 Rule 4 #3: a full-edit-wizard validation error re-renders the wizard
    field with its custom nav buttons instead of swapping in flow:back (which
    would abort the whole wizard)."""

    def test_full_edit_error_rerenders_wizard_field(self):
        from handlers.admin_ai import _handle_full_edit_input, WIZARD_FIELDS

        self.flow_ctx.user_data["full_edit"] = {"preset": "custom_gpt", "field_idx": 0, "values": {}}
        self.flow_ctx.user_data["awaiting"] = "ai_preset_full_edit:custom_gpt:0"
        # Field 0 is "name"; an invalid value triggers the error retry.
        up = self._make_message_update("inv@lid")
        asyncio.run(_handle_full_edit_input(up, self.flow_ctx, "custom_gpt", 0, "inv@lid"))
        markup = self._markup(up.message.reply_text.call_args)
        self.assertIn("full_edit_cancel", markup)
        self.assertIn("full_edit_next", markup)
        self.assertNotIn("flow:back", markup)
        # The wizard must not have been aborted.
        self.assertEqual(self.flow_ctx.user_data["full_edit"]["field_idx"], 0)
        self.assertEqual(self.flow_ctx.user_data["awaiting"], f"ai_preset_full_edit:custom_gpt:{WIZARD_FIELDS.index('name')}")


class AiPresetLabelCanonicalizationTest(_AiPresetLabelsAndBackBase):
    """#342 Rule 1/2: single-field edit prompt, confirmation, and full-edit
    wizard all use the canonical all-English short label map."""

    def test_confirmation_uses_canonical_label_not_raw_field_name(self):
        from handlers.admin_ai import _handle_ai_preset_field_input

        self.flow_ctx.user_data["awaiting"] = "ai_preset_edit:custom_gpt:max_tpm"
        up = self._make_message_update("500")
        asyncio.run(_handle_ai_preset_field_input(up, self.flow_ctx, "custom_gpt", "max_tpm", "500"))
        confirmation = up.message.reply_text.call_args_list[0].args[0]
        self.assertIn("Max TPM", confirmation)
        self.assertNotIn("max_tpm", confirmation)

    def test_field_edit_prompt_uses_short_label(self):
        from handlers.admin_ai import _edit_ai_preset_field

        update = self._make_callback_update("x")
        asyncio.run(_edit_ai_preset_field(update, self.flow_ctx, "custom_gpt", "api_key"))
        text = update.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("API Key", text)
        self.assertNotIn("literal; stored encrypted", text)

    def test_full_edit_wizard_uses_canonical_english_label(self):
        from handlers.admin_ai import _show_wizard_field, WIZARD_FIELDS

        preset = db.get_preset("custom_gpt")
        idx = WIZARD_FIELDS.index("max_tpm")
        self.flow_ctx.user_data["full_edit"] = {"preset": "custom_gpt", "field_idx": idx, "values": {}}
        update = self._make_callback_update("x")
        asyncio.run(_show_wizard_field(update, self.flow_ctx, "custom_gpt", idx, preset))
        text = update.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("Max TPM", text)
        self.assertNotIn("حد توکن در دقیقه", text)


if __name__ == "__main__":
    unittest.main()