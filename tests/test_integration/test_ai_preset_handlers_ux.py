"""Integration tests for Phase 3 handlers/UX: R3 delete confirm, R4 duplicate,
R5 edit-back, R7 usage pagination.

These dispatch through the real ``_handle_admin_callback`` -> ``handle_ai_callback``
path and assert Telegram output, the emitted keyboard callback prefixes, and the
resulting DB state.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class _Phase3AiPresetFlowBase(unittest.TestCase):
    """Scratch-DB harness + admin router dispatch shared by Phase 3 flows."""

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

    def _make_preset(self, name: str, **kwargs):
        defaults = {"base_url": "https://x", "model": "m", "priority": 0}
        defaults.update(kwargs)
        db.set_preset(name=name, **defaults)


class AiPresetDeleteConfirmFlowTest(_Phase3AiPresetFlowBase):
    """R3: deleting a custom preset requires a two-step inline confirm."""

    def setUp(self):
        super().setUp()
        # Phase 4 (R3: no auto-seed): seed a separate active preset so the
        # presets under test are never the active preset (which the R6 guard
        # blocks from deletion).
        db.set_preset("active_preset", base_url="https://x", model="m")
        db.set_setting("ai_primary_preset", "active_preset")

    def test_first_delete_tap_shows_confirm_not_deletion(self):
        self._make_preset("victim")
        before = {p["name"] for p in db.get_presets()}
        up = self._callback(f"ai_preset:delete:{db_resolve('victim')}")
        # The preset must still exist after the first (confirm) tap.
        self.assertEqual({p["name"] for p in db.get_presets()}, before,
                         "first tap must NOT delete")
        text = up.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("مطمئن", text)
        markup = up.callback_query.edit_message_text.call_args.kwargs["reply_markup"].to_json()
        self.assertIn("ai_preset:confirm_delete_yes", markup)
        self.assertIn("ai_preset:confirm_delete_no", markup)

    def test_confirm_yes_deletes_and_returns_to_list(self):
        self._make_preset("doomed")
        self._callback(f"ai_preset:delete:{db_resolve('doomed')}")
        self._callback(f"ai_preset:confirm_delete_yes:{db_resolve('doomed')}")
        self.assertIsNone(db.get_preset("doomed"), "confirm-yes must delete the preset")

    def test_confirm_no_cancels_deletion(self):
        self._make_preset("spared")
        self._callback(f"ai_preset:delete:{db_resolve('spared')}")
        self._callback(f"ai_preset:confirm_delete_no:{db_resolve('spared')}")
        self.assertIsNotNone(db.get_preset("spared"), "confirm-no must keep the preset")


class AiPresetDuplicateFlowTest(_Phase3AiPresetFlowBase):
    """R4: duplicate a preset by cloning into a new name."""

    def test_duplicate_preset_creates_copy_with_copy_suffix(self):
        self._make_preset("orig", base_url="https://o", model="m1", priority=2,
                          input_cost_per_million=1.5)
        up = self._callback(f"ai_preset:duplicate:{db_resolve('orig')}")
        # Duplicate should immediately persist a clone named "<orig> (copy)".
        copy = db.get_preset("orig (copy)")
        self.assertIsNotNone(copy, "duplicate must create a new preset")
        self.assertEqual(copy["base_url"], "https://o")
        self.assertEqual(copy["model"], "m1")
        self.assertEqual(copy["input_cost_per_million"], 1.5)
        markup = up.callback_query.edit_message_text.call_args.kwargs["reply_markup"].to_json()
        self.assertIn("ai_preset:duplicate:", markup)

    def test_duplicate_clone_preserves_enabled_state(self):
        # A clone inherits the source's enabled state so it can never start
        # routing without an explicit owner choice.
        self._make_preset("disabled_src", enabled=0)
        self._callback(f"ai_preset:duplicate:{db_resolve('disabled_src')}")
        clone = db.get_preset("disabled_src (copy)")
        self.assertIsNotNone(clone)
        self.assertEqual(clone["enabled"], 0, "clone must inherit disabled state")
        self.assertNotIn("is_custom", clone, "is_custom column must be gone")


class AiPresetEditBackFlowTest(_Phase3AiPresetFlowBase):
    """R5: the full-edit wizard exposes a Back button routing to full_edit_back,
    and re-renders both the stored (Current) and in-progress (Draft) value."""

    def test_wizard_summary_offers_back(self):
        self._make_preset("backable")
        # Advance the wizard past field 0 where Back is disabled before asserting.
        self._callback(f"ai_preset:full_edit:{db_resolve('backable')}")
        up = self._callback(f"ai_preset:full_edit_next:{db_resolve('backable')}")
        markup = up.callback_query.edit_message_text.call_args.kwargs["reply_markup"].to_json()
        self.assertIn("ai_preset:full_edit_back", markup)

    def test_wizard_first_field_has_no_back(self):
        self._make_preset("front")
        up = self._callback(f"ai_preset:full_edit:{db_resolve('front')}")
        markup = up.callback_query.edit_message_text.call_args.kwargs["reply_markup"].to_json()
        self.assertNotIn("full_edit_back", markup)

    def test_wizard_empty_draft_not_rendered(self):
        # A draft of "" must not render a meaningless empty "پیشنویس" line.
        from handlers.admin_ai import _show_wizard_field, WIZARD_FIELDS

        self._make_preset("drafty", base_url="https://x")
        preset = db.get_preset("drafty")
        ctx = self._make_context()
        ctx.user_data["full_edit"] = {"preset": "drafty", "field_idx": 0,
                                      "values": {WIZARD_FIELDS[0]: ""}}
        update = self._make_callback_update("x")
        asyncio.run(_show_wizard_field(update, ctx, "drafty", 0, preset))
        text = update.callback_query.edit_message_text.call_args.args[0]
        self.assertNotIn("پیشنویس", text)

    def test_wizard_whitespace_draft_not_rendered(self):
        # A whitespace-only draft must not render a near-empty "پیشنویس" line.
        from handlers.admin_ai import _show_wizard_field, WIZARD_FIELDS

        self._make_preset("drafty_ws", base_url="https://x")
        preset = db.get_preset("drafty_ws")
        ctx = self._make_context()
        ctx.user_data["full_edit"] = {"preset": "drafty_ws", "field_idx": 0,
                                      "values": {WIZARD_FIELDS[0]: "   "}}
        update = self._make_callback_update("x")
        asyncio.run(_show_wizard_field(update, ctx, "drafty_ws", 0, preset))
        text = update.callback_query.edit_message_text.call_args.args[0]
        self.assertNotIn("پیشنویس", text)

    def test_wizard_nonempty_draft_rendered(self):
        from handlers.admin_ai import _show_wizard_field, WIZARD_FIELDS

        self._make_preset("drafty2", base_url="https://x")
        preset = db.get_preset("drafty2")
        ctx = self._make_context()
        ctx.user_data["full_edit"] = {"preset": "drafty2", "field_idx": 0,
                                      "values": {WIZARD_FIELDS[0]: "my draft"}}
        update = self._make_callback_update("x")
        asyncio.run(_show_wizard_field(update, ctx, "drafty2", 0, preset))
        text = update.callback_query.edit_message_text.call_args.args[0]
        self.assertIn("پیشنویس", text)
        self.assertIn("my draft", text)


class AiPresetUsagePaginationTest(_Phase3AiPresetFlowBase):
    """R7: fallback usage details are paginated per_page=5 with prev/next."""

    def test_usage_lists_page_one_with_next_when_many(self):
        for i in range(7):
            self._make_preset(f"preset_{i}")
        up = self._callback("fallback:usage_details")
        markup = up.callback_query.edit_message_text.call_args.kwargs["reply_markup"].to_json()
        self.assertIn("fallback:usage_page", markup)
        self.assertIn(":next", markup)
        text = up.callback_query.edit_message_text.call_args.args[0]
        # Page one must show at most USAGE_PAGE_SIZE rows (5).
        self.assertLessEqual(text.count("req"), 5)
        # A next page must exist when more rows remain.
        self.assertIn("صفحه 1/", text)

    def test_usage_page_next_advances(self):
        # Phase 4 (R3: no auto-seed): seed extra "noise" presets so the target
        # presets fall on a later page and pagination navigation is exercised.
        for i in range(10):
            self._make_preset(f"noise_{i}")
        for i in range(7):
            self._make_preset(f"preset_{i}")
        # The handler treats the callback number as an absolute 0-based page
        # index. Walk pages until a custom preset appears or we exhaust them.
        texts = []
        page_idx = 0
        while True:
            up = self._callback("fallback:usage_details" if page_idx == 0 else f"fallback:usage_page:{page_idx}:next")
            texts.append(up.callback_query.edit_message_text.call_args.args[0])
            if any(f"preset_{i}" in texts[-1] for i in range(7)):
                break
            markup = up.callback_query.edit_message_text.call_args.kwargs["reply_markup"].to_json()
            if ":next" not in markup:
                break
            page_idx += 1
        combined = "\n".join(texts)
        self.assertGreater(len(texts), 1, "should take more than one page")
        self.assertTrue(
            any(f"preset_{i}" in combined for i in range(7)),
            "custom presets must appear on some usage page",
        )


class AiPresetEditMenuPreviewTest(_Phase3AiPresetFlowBase):
    """T2 (R2/R5/R6): single-field edit menu renders one vertical قبلی/جدید
    table per dirty field (WIZARD_FIELDS order), a Persian-digit pending
    header, and masked api_key values; staging toasts + re-renders in place."""

    def _render_menu(self, preset_name, edits):
        from handlers import admin_ai
        from services.send_pretty import Backend

        update = self._make_callback_update("x")
        ctx = self._make_context()
        ctx.user_data["preset_edits"] = {preset_name: dict(edits)}
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say:
            asyncio.run(admin_ai._edit_ai_preset(update, ctx, preset_name))
        mock_say.assert_called_once()
        self.assertEqual(mock_say.call_args[1].get("backend"), Backend.RICH)
        content = mock_say.call_args[0][2]
        return content.render(Backend.RICH), mock_say.call_args[1].get("keyboard")

    def test_two_dirty_fields_render_two_tables_with_old_and_new(self):
        self._make_preset("preview_p", base_url="https://old.example.com",
                          model="old-model")
        rendered, _ = self._render_menu("preview_p", {
            "model": "new-model",
            "base_url": "https://new.example.com/v1",
        })
        # Both dirty labels with old+new values as code cells.
        self.assertIn("Model", rendered)
        self.assertIn("Base URL", rendered)
        self.assertIn("`old-model`", rendered)
        self.assertIn("`new-model`", rendered)
        self.assertIn("`https://old.example.com`", rendered)
        self.assertIn("`https://new.example.com/v1`", rendered)
        self.assertIn("قبلی", rendered)
        self.assertIn("جدید", rendered)
        # One vertical table per dirty field (pipe header per table).
        self.assertIn("| وضعیت | مقدار |", rendered)
        self.assertEqual(rendered.count("| --- | --- |"), 2)
        # WIZARD_FIELDS order: base_url (idx 2) before model (idx 3).
        self.assertLess(rendered.index("Base URL"), rendered.index("Model"))
        # Header counter uses Persian digits.
        self.assertIn("۲ تغییر در انتظار — هنوز ذخیره نشده", rendered)

    def test_clean_field_has_no_table(self):
        self._make_preset("preview_c", base_url="https://old.example.com",
                          model="old-model")
        rendered, _ = self._render_menu("preview_c", {"model": "new-model"})
        self.assertIn("۱ تغییر در انتظار — هنوز ذخیره نشده", rendered)
        self.assertIn("Model", rendered)
        # Clean fields render no table and no heading at all.
        self.assertNotIn("Temperature", rendered)
        self.assertNotIn("Base URL", rendered)
        self.assertEqual(rendered.count("| --- | --- |"), 1)

    def test_api_key_values_masked(self):
        self._make_preset("preview_k", base_url="https://x", model="m",
                          api_key="seed-key-will-not-resolve")
        draft_key = "sk-1234567890abcdef"
        rendered, keyboard = self._render_menu("preview_k", {"api_key": draft_key})
        from services.db.key_crypto import mask_key

        self.assertIn("API Key", rendered)
        # Staged plaintext key never leaks into the menu or the keyboard.
        self.assertNotIn(draft_key, rendered)
        for row in keyboard.inline_keyboard:
            for button in row:
                self.assertNotIn(draft_key, button.text)
        # Masked draft visible; old cell masked or "—" (fail-closed, never plaintext).
        self.assertIn(f"`{mask_key(draft_key)}`", rendered)

    def test_edit_keyboard_dirty_prefix_counters_and_no_values(self):
        self._make_preset("preview_b", base_url="https://old.example.com",
                          model="old-model")
        _, keyboard = self._render_menu("preview_b", {
            "model": "new-model",
            "base_url": "https://new.example.com/v1",
        })
        texts = [b.text for row in keyboard.inline_keyboard for b in row]
        # Dirty rows carry ✏️ prefix; clean rows do not.
        model_row = next(t for t in texts if "Model" in t)
        base_row = next(t for t in texts if "Base URL" in t)
        temp_row = next(t for t in texts if "Temperature" in t)
        self.assertTrue(model_row.startswith("✏️"))
        self.assertTrue(base_row.startswith("✏️"))
        self.assertFalse(temp_row.startswith("✏️"))
        # Values live in menu tables now, not on buttons.
        for t in texts:
            self.assertNotIn("new-model", t)
            self.assertNotIn("https://", t)
        # Save/discard counters use Persian digits; callback_data unchanged.
        self.assertIn("💾 ذخیره (۲)", texts)
        self.assertIn("🗑️ دور ریختن همه (۲)", texts)
        callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        self.assertTrue(any(c.startswith("admin:ai_preset:save:") for c in callbacks))
        self.assertTrue(any(c.startswith("admin:ai_preset:discard_all:") for c in callbacks))

    def test_field_input_toasts_and_rerenders_menu_once(self):
        from handlers import admin_ai

        self._make_preset("preview_i", base_url="https://x", model="old-model")
        message = MagicMock()
        message.text = "new-model"
        message.reply_text = AsyncMock()
        message.delete = AsyncMock()
        update = self._make_callback_update("x")
        update.message = message
        ctx = self._make_context()
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say, \
                patch("handlers.admin_ai.notify_callback", new=AsyncMock()) as mock_notify:
            asyncio.run(admin_ai._handle_ai_preset_field_input(
                update, ctx, "preview_i", "model", "new-model"))
        # Staged, single menu re-render (no extra ✅ message), toast sent.
        self.assertEqual(ctx.user_data["preset_edits"]["preview_i"]["model"], "new-model")
        mock_say.assert_called_once()
        mock_notify.assert_called_once()
        toast_text = mock_notify.call_args[0][1]
        self.assertIn("Model", toast_text)
        message.reply_text.assert_not_called()


class AiPresetConfirmSavePreviewTest(_Phase3AiPresetFlowBase):
    """T3 (R3/R5/R6): save-confirm renders numbered old+new tables via the
    shared helper, conditional notes, and a 3-button keyboard reusing the
    existing confirm_save_yes/no + ai_preset:edit routes."""

    def _render_confirm(self, preset_name, edits):
        from handlers import admin_ai
        from services.send_pretty import Backend

        update = self._make_callback_update("x")
        ctx = self._make_context()
        ctx.user_data["preset_edits"] = {preset_name: dict(edits)}
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say:
            asyncio.run(admin_ai._confirm_save_preset(update, ctx, preset_name))
        mock_say.assert_called_once()
        self.assertEqual(mock_say.call_args[1].get("backend"), Backend.RICH)
        content = mock_say.call_args[0][2]
        return content.render(Backend.RICH), mock_say.call_args[1].get("keyboard"), ctx

    def test_confirm_renders_numbered_old_new_tables(self):
        self._make_preset("conf_p", base_url="https://old.example.com",
                          model="old-model")
        rendered, _, _ = self._render_confirm("conf_p", {
            "model": "new-model",
            "base_url": "https://new.example.com/v1",
        })
        self.assertIn("تأیید ذخیره", rendered)
        self.assertIn("conf\\_p", rendered)
        # Numbered per-field blocks (Persian digits; "." is Rich-escaped).
        self.assertIn("۱\\.", rendered)
        self.assertIn("۲\\.", rendered)
        # Both dirty labels with old+new values as code cells.
        self.assertIn("Model", rendered)
        self.assertIn("Base URL", rendered)
        self.assertIn("`old-model`", rendered)
        self.assertIn("`new-model`", rendered)
        self.assertIn("`https://old.example.com`", rendered)
        self.assertIn("`https://new.example.com/v1`", rendered)
        self.assertIn("قبلی", rendered)
        self.assertIn("جدید", rendered)
        self.assertEqual(rendered.count("| --- | --- |"), 2)
        # WIZARD_FIELDS order: base_url (idx 2) before model (idx 3).
        self.assertLess(rendered.index("Base URL"), rendered.index("Model"))
        # Dirty-count line uses Persian digits.
        self.assertIn("۲ مورد تغییر کرده است", rendered)

    def test_active_preset_note_present(self):
        self._make_preset("conf_act", base_url="https://x", model="m", enabled=1)
        db.set_setting("ai_primary_preset", "conf_act")
        rendered, _, _ = self._render_confirm("conf_act", {"model": "m2"})
        self.assertIn("🎯", rendered)

    def test_inactive_preset_note_absent(self):
        self._make_preset("conf_other", base_url="https://x", model="m", enabled=1)
        self._make_preset("conf_inact", base_url="https://x", model="m", enabled=1)
        db.set_setting("ai_primary_preset", "conf_other")
        rendered, _, _ = self._render_confirm("conf_inact", {"model": "m2"})
        self.assertNotIn("🎯", rendered)

    def test_priority_note_only_when_priority_or_fallback_dirty(self):
        self._make_preset("conf_pr", base_url="https://x", model="m", priority=0)
        rendered, _, _ = self._render_confirm("conf_pr", {"priority": 5})
        self.assertIn("⛓️", rendered)
        rendered_fb, _, _ = self._render_confirm("conf_pr", {"in_fallback_chain": 0})
        self.assertIn("⛓️", rendered_fb)
        rendered_clean, _, _ = self._render_confirm("conf_pr", {"model": "m2"})
        self.assertNotIn("⛓️", rendered_clean)

    def test_empty_edits_guard_text(self):
        from handlers import admin_ai

        self._make_preset("conf_empty", base_url="https://x", model="m")
        update = self._make_callback_update("x")
        ctx = self._make_context()
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say, \
                patch("handlers.admin_ai.notify_callback", new=AsyncMock()) as mock_notify:
            asyncio.run(admin_ai._confirm_save_preset(update, ctx, "conf_empty"))
        mock_say.assert_not_called()
        mock_notify.assert_called_once()
        self.assertIn("تغییری برای ذخیره وجود ندارد", mock_notify.call_args[0][1])

    def test_keyboard_three_buttons_reuse_existing_routes(self):
        self._make_preset("conf_k", base_url="https://x", model="old-m")
        _, keyboard, _ = self._render_confirm("conf_k", {"model": "new-m"})
        rows = keyboard.inline_keyboard
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(len(rows[1]), 1)
        texts = [b.text for row in rows for b in row]
        self.assertIn("✅ بله، ذخیره کن", texts)
        self.assertIn("❌ لغو ذخیره", texts)
        self.assertIn("↩️ بازگشت به ویرایش", texts)
        callbacks = [b.callback_data for row in rows for b in row]
        self.assertTrue(any(c.startswith("admin:ai_preset:confirm_save_yes:") for c in callbacks))
        self.assertTrue(any(c.startswith("admin:ai_preset:confirm_save_no:") for c in callbacks))
        edit_cbs = [c for c in callbacks if c.startswith("admin:ai_preset:edit:")]
        self.assertEqual(len(edit_cbs), 1)

    def test_third_button_routes_to_edit_with_drafts_intact(self):
        from handlers import admin_ai
        from services.send_pretty import Backend

        self._make_preset("conf_e", base_url="https://x", model="old-m")
        update = self._make_callback_update("x")
        ctx = self._make_context()
        ctx.user_data["preset_edits"] = {"conf_e": {"model": "new-m"}}
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say:
            asyncio.run(admin_ai._confirm_save_preset(update, ctx, "conf_e"))
        keyboard = mock_say.call_args[1].get("keyboard")
        callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        edit_cb = next(c for c in callbacks if c.startswith("admin:ai_preset:edit:"))
        # Tapping it re-renders the edit menu with drafts intact.
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_menu:
            asyncio.run(admin_ai._edit_ai_preset(update, ctx, "conf_e"))
        self.assertEqual(ctx.user_data["preset_edits"]["conf_e"], {"model": "new-m"})
        menu_text = mock_menu.call_args[0][2].render(Backend.RICH)
        self.assertIn("۱ تغییر در انتظار", menu_text)


def db_resolve(name: str) -> str:
    from services.utils.callback_codec import preset_token
    return preset_token(name)


if __name__ == "__main__":
    unittest.main()
