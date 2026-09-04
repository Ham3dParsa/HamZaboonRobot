"""Integration render-snapshot tests for the Admin AI preset panel (Phase 1).

Covers the Phase 1 cosmetic rules R6 (shared clean ``{toggle} <b>name</b>
[tags]`` list render on both list sites), R8 (emoji dictionary applied to the
fallback chain and usage-details views), and R9 (usage label relabeled to
«مصرف ۲۴ ساعته»). Dispatches through the real ``_handle_admin_callback`` ->
``handle_ai_callback`` path on an isolated scratch DB and asserts the rendered
message text captured on the callback edit mock.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class AdminAiRenderFlowTest(unittest.TestCase):
    """Admin AI preset render snapshots routed through the real dispatcher."""

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

    @staticmethod
    def _rendered_text(update) -> str:
        call = update.callback_query.edit_message_text.call_args
        return call.kwargs.get("text") or call[0][0]

    def test_linear_presets_uses_clean_shared_brief(self):
        """R6/R8: list renders ``{toggle} <b>name</b> [tags]`` with no stray
        active ✅ marker and correct toggle emoji."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "render_primary",
            base_url="https://api.example.com",
            model="gpt-test",
            is_emergency=1,
            enabled=1,
        )
        db.set_setting("ai_primary_preset", "render_primary")

        update = self._make_callback_update("admin:ai_presets")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_presets"))

        text = self._rendered_text(update)
        # The emergency preset sits on page 1 and is deterministic.
        self.assertIn("🟢 <b>render_primary</b>", text)
        self.assertNotIn("✅", text)

    def test_linear_presets_marks_active_with_target_emoji(self):
        """R8: the shorthand loses no 🎯 for the active preset on its page."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "render_active",
            base_url="https://api.example.com",
            model="gpt-test",
            enabled=1,
        )
        db.set_setting("ai_primary_preset", "render_active")

        active = db.get_active_preset_name()
        # Find the page index that holds the active preset.
        per_page = 5
        index = next(i for i, p in enumerate(db.get_presets()) if p["name"] == active)
        page = index // per_page

        update = self._make_callback_update(f"admin:ai_preset:page:{page}")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, f"ai_preset:page:{page}"))

        text = self._rendered_text(update)
        self.assertIn(f"🟢 <b>{active}</b> [🎯]", text)
        self.assertIn("🎯", text)

    def test_linear_presets_escapes_bold_name_value(self):
        """T8b: the linear list keeps the HTML bold name and escapes dynamic
        model/URL values (no manual html_escape left in the handler path)."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "list_escape",
            base_url="https://api.example.com/?a=1&b=2",
            model="gpt <m>",
            enabled=1,
        )
        db.set_setting("ai_primary_preset", "list_escape")

        update = self._make_callback_update("admin:ai_presets")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_presets"))

        text = self._rendered_text(update)
        self.assertIn("<b>list_escape</b>", text)
        self.assertIn("gpt &lt;m&gt;", text)
        self.assertIn("a=1&amp;b=2", text)
        self.assertNotIn("gpt <m>", text)

    def test_field_edit_prompt_escapes_current_in_code(self):
        """T8c: the field-edit prompt shows the current value inside a ``<code>``
        span and escapes dynamic values (no manual html_escape left in the
        handler path)."""
        from handlers.admin_ai import _edit_ai_preset_field

        db.set_preset(
            "field_esc",
            base_url="https://api.example.com",
            model="gpt <m>",
            api_key="test",
        )
        update = self._make_callback_update("admin:ai_preset:edit:field_esc")
        ctx = self._make_context()
        asyncio.run(_edit_ai_preset_field(update, ctx, "field_esc", "model"))

        text = self._rendered_text(update)
        self.assertIn("<code>gpt &lt;m&gt;</code>", text)
        self.assertNotIn("<code>gpt <m></code>", text)

    def test_create_finish_escapes_name_in_code(self):
        """T8d: the create-finish summary shows the preset name inside a
        ``<code>`` span and escapes dynamic values (no manual html_escape left
        in the handler path)."""
        from handlers.admin_ai import _finish_create

        ctx = self._make_context()
        ctx.user_data["preset_create"] = {"name": "my<gpt>"}
        ctx.user_data["awaiting"] = None
        db.set_preset("my<gpt>", enabled=0)
        update = self._make_callback_update("admin:ai_preset:create:status:on")
        asyncio.run(_finish_create(update, ctx))

        text = self._rendered_text(update)
        self.assertIn("<code>my&lt;gpt&gt;</code>", text)
        self.assertNotIn("<code>my<gpt></code>", text)

    def test_create_priority_escapes_name_in_code(self):
        """T8d/Kilo: the create-priority screen shows the pending name inside a
        ``<code>`` span and escapes dynamic values."""
        from handlers.admin_ai import _show_create_priority

        ctx = self._make_context()
        ctx.user_data["preset_create"] = {"name": "my<gpt>"}
        update = self._make_callback_update("admin:ai_preset:create:priority:manual")
        asyncio.run(_show_create_priority(update, ctx))

        text = self._rendered_text(update)
        self.assertIn("— <code>my&lt;gpt&gt;</code>", text)
        self.assertNotIn("— <code>my<gpt></code>", text)

    def test_create_status_escapes_name_in_code(self):
        """T8d/Kilo: the create-status screen shows the pending name inside a
        ``<code>`` span and escapes dynamic values."""
        from handlers.admin_ai import _show_create_status

        ctx = self._make_context()
        ctx.user_data["preset_create"] = {"name": "my<gpt>"}
        update = self._make_callback_update("admin:ai_preset:create:status:on")
        asyncio.run(_show_create_status(update, ctx))

        text = self._rendered_text(update)
        self.assertIn("— <code>my&lt;gpt&gt;</code>", text)
        self.assertNotIn("— <code>my<gpt></code>", text)

    def test_group_view_escapes_label_and_key(self):
        """T8e/Kilo: the group-detail view escapes the group label and masked
        key when they contain angle brackets."""
        from handlers.admin import _handle_admin_callback
        from handlers.admin_ai import _key_hash

        api_key = "sk-a<&b"
        db.set_preset(
            "grp_esc",
            base_url="https://api.example.com",
            model="gpt",
            api_key=api_key,
            group_label="گ<ا",
        )
        kh = _key_hash(api_key)
        update = self._make_callback_update(f"admin:ai_preset:group:{kh}")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, f"ai_preset:group:{kh}"))

        text = self._rendered_text(update)
        self.assertIn("گروه: گ&lt;ا", text)
        self.assertNotIn("گروه: گ<ا", text)

    def test_group_manager_puts_each_group_on_own_line(self):
        """T8e: the group-manager list renders one group per line (fixes the
        legacy ``"".join`` gluing where rows ran together)."""
        from handlers.admin import _handle_admin_callback

        db.set_preset("grp_a", base_url="https://api.example.com", model="gpt", group_label="گ<ا")
        db.set_preset("grp_b", base_url="https://api.example.com", model="gpt", group_label="g2")

        update = self._make_callback_update("admin:ai_preset:group_manager")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_preset:group_manager"))

        text = self._rendered_text(update)
        self.assertIn("• <b>گ&lt;ا</b> — 1 پریست\n• <b>g2</b> — 1 پریست", text)

    def test_fallback_chain_uses_emergency_and_active_emoji(self):
        """R8: the fallback chain render shows 🛡️ for emergency and 🟢 for a
        normal enabled preset (no legacy ✅/🚨 markers)."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "custom_normal",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
        )
        update = self._make_callback_update("admin:fallback_chain")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "fallback_chain"))

        text = self._rendered_text(update)
        self.assertIn("🟢", text)
        self.assertNotIn("🚨", text)

    def test_fallback_panel_renders_html_and_escapes_preset(self):
        """T8f: the fallback panel renders via spans (HTML bold title) and
        escapes a preset name containing angle brackets."""
        from handlers.admin import _handle_admin_callback

        db.set_setting("ai_primary_preset", "a<b")
        db.set_setting("ai_fallback_preset", "f&c")
        update = self._make_callback_update("admin:ai_fallback")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_fallback"))

        text = self._rendered_text(update)
        self.assertIn("🔄 <b>مدیریت پیش‌تنظیم پشتیبان (Fallback)</b>", text)
        self.assertIn("Primary: a&lt;b", text)
        self.assertIn("Fallback: f&amp;c", text)

    def test_custom_test_results_escapes_card_fields(self):
        """T8g: the custom-test results render bold labels + escaped card fields
        (no manual html_escape left in the handler path)."""
        from handlers import admin_ai
        from handlers.admin_ai import _run_custom_test

        db.set_preset(
            "cand_real",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
            enabled=1,
        )
        ctx = self._make_context()
        ctx.user_data["custom_test_state"] = {
            "prompt": "p", "lang": "en", "goal": "general", "level": "beginner",
            "candidate_preset": "cand_real",
        }
        with patch.object(admin_ai.ai, "custom_test_card", return_value={
            "word": "w<m", "fa_meaning": "م&ا", "examples": "['a','b']"
        }), patch("handlers.admin_ai.prompts.daily_batch_system_prompt", return_value="SYS"):
            update = self._make_callback_update("admin:ai_custom_test:target:candidate")
            asyncio.run(_run_custom_test(update, ctx, "candidate"))

        text = self._rendered_text(update)
        self.assertIn("<b>Candidate (cand_real)</b>", text)
        self.assertIn("Word: w&lt;m", text)
        self.assertIn("Meaning: م&amp;ا", text)
        self.assertNotIn("Word: w<m", text)

    def test_custom_test_missing_candidate_shows_explicit_error(self):
        """T1: missing candidate preset shows an explicit error, never an
        invented 'gapgpt' fallback preset."""
        from handlers import admin_ai
        from handlers.admin_ai import _run_custom_test

        ctx = self._make_context()
        ctx.user_data["custom_test_state"] = {
            "prompt": "p", "lang": "en", "goal": "general", "level": "beginner",
        }
        with patch.object(admin_ai.ai, "custom_test_card", return_value={
            "word": "w", "fa_meaning": "م", "examples": "[]"
        }) as mock_card, patch("handlers.admin_ai.prompts.daily_batch_system_prompt", return_value="SYS"):
            update = self._make_callback_update("admin:ai_custom_test:target:candidate")
            asyncio.run(_run_custom_test(update, ctx, "candidate"))

        self.assertFalse(mock_card.called)
        text = self._rendered_text(update)
        self.assertNotIn("gapgpt", text)
        self.assertIn("کاندیدا", text)
        update.callback_query.answer.assert_awaited()
        _, answer_kw = update.callback_query.answer.call_args
        self.assertTrue(answer_kw.get("show_alert"))

    def test_custom_test_ab_missing_candidate_fails_fast_zero_provider_calls(self):
        """W1: target=ab with a missing candidate must fail fast with ZERO
        provider calls — the current-config call must not run first and have
        its result discarded."""
        from handlers import admin_ai
        from handlers.admin_ai import _run_custom_test

        ctx = self._make_context()
        ctx.user_data["custom_test_state"] = {
            "prompt": "p", "lang": "en", "goal": "general", "level": "beginner",
        }
        with patch.object(admin_ai.ai, "custom_test_card", return_value={
            "word": "w", "fa_meaning": "م", "examples": "[]"
        }) as mock_card, patch("handlers.admin_ai.prompts.daily_batch_system_prompt", return_value="SYS"):
            update = self._make_callback_update("admin:ai_custom_test:target:ab")
            asyncio.run(_run_custom_test(update, ctx, "ab"))

        self.assertFalse(mock_card.called)
        text = self._rendered_text(update)
        self.assertIn("کاندیدا", text)
        update.callback_query.answer.assert_awaited()
        _, answer_kw = update.callback_query.answer.call_args
        self.assertTrue(answer_kw.get("show_alert"))

    def test_ai_connection_result_escapes_model_and_error(self):
        """T8g: the AI connection result renders bold title + escaped model/error
        fields (no manual html_escape left in the handler path)."""
        from handlers import admin_ai
        from handlers.admin_ai import _test_ai_connection

        ctx = self._make_context()
        db.set_preset("conn_active", base_url="https://api.example.com", model="gpt", api_key="test", enabled=1)
        db.set_setting("ai_primary_preset", "conn_active")
        with patch.object(admin_ai.ai, "test_connection", return_value={
            "success": True, "latency_ms": 42, "model": "g<m", "usage": "t&k",
        }):
            update = self._make_callback_update("admin:ai_test_connection")
            asyncio.run(_test_ai_connection(update, ctx))

        text = self._rendered_text(update)
        self.assertIn("✅ <b>اتصال موفق</b>", text)
        self.assertIn("Model: g&lt;m", text)
        self.assertIn("Tokens: t&amp;k", text)
        self.assertNotIn("Model: g<m", text)

    def test_help_screens_render_html_bold_headers(self):
        """T8h: the help overview screens render via spans with bold section
        headers (no manual HTML string in the handler path)."""
        from handlers.admin_ai import _show_help_fallback_chain, _show_help_presets

        for fn, cb in ((_show_help_presets, "help:presets"), (_show_help_fallback_chain, "help:chain")):
            ctx = self._make_context()
            update = self._make_callback_update(f"admin:{cb}")
            asyncio.run(fn(update, ctx))
            text = self._rendered_text(update)
            self.assertIn("❓ <b>راهنمای", text)

    def test_confirm_screens_escape_preset_name_in_bold(self):
        """T8-last: the save-confirm preview and delete-confirm screens escape
        dynamic values (T3 rewrote save-confirm as a numbered old/new Rich
        preview via the shared helper, so it asserts through patched say)."""
        from handlers import admin_ai
        from handlers.admin_ai import _delete_ai_preset
        from services.send_pretty import Backend

        db.set_preset("confirm<g", base_url="https://api.example.com", model="gpt", api_key="test", enabled=0)

        # save-confirm: needs pending edits; renders RICH via the helper.
        ctx = self._make_context()
        ctx.user_data["preset_edits"] = {"confirm<g": {"model": "x"}}
        update = self._make_callback_update("admin:ai_preset:save:confirm<g")
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say:
            asyncio.run(admin_ai._confirm_save_preset(update, ctx, "confirm<g"))
        mock_say.assert_called_once()
        self.assertEqual(mock_say.call_args[1].get("backend"), Backend.RICH)
        save_text = mock_say.call_args[0][2].render(Backend.RICH)
        self.assertIn("تأیید ذخیره", save_text)
        self.assertIn("confirm\\<g", save_text)
        self.assertNotIn("confirm<g", save_text)
        self.assertIn("`gpt`", save_text)
        self.assertIn("`x`", save_text)

        # delete-confirm: preset must not be active
        db.set_setting("ai_primary_preset", "confirm<g")
        # override active to a different preset so delete is allowed
        db.set_preset("confirm_active", base_url="https://api.example.com", model="gpt", api_key="test")
        db.set_setting("ai_primary_preset", "confirm_active")
        ctx2 = self._make_context()
        update2 = self._make_callback_update("admin:ai_preset:delete:confirm<g")
        asyncio.run(_delete_ai_preset(update2, ctx2, "confirm<g"))
        del_text = self._rendered_text(update2)
        self.assertIn("آیا از حذف پیش‌تنظیم «confirm&lt;g» مطمئنید؟", del_text)
        self.assertNotIn("«confirm<g»", del_text)

    def test_fallback_chain_escapes_preset_name_in_bold(self):
        """Kilo: the fallback-chain screen escapes a preset name containing
        angle brackets (classic can't-parse-entities guard)."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "chain<g>", base_url="https://api.example.com", model="gpt",
            api_key="test", enabled=1,
        )
        update = self._make_callback_update("admin:fallback_chain")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "fallback_chain"))

        text = self._rendered_text(update)
        self.assertIn("<b>chain&lt;g&gt;</b>", text)
        self.assertNotIn("chain<g>", text)

    def test_usage_page_escapes_preset_name(self):
        """Kilo: the usage page escapes a preset name containing angle brackets
        in the row render."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "usage<g>", base_url="https://api.example.com", model="gpt",
            api_key="test", max_daily_req=5,
        )
        update = self._make_callback_update("admin:fallback:usage_details")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "fallback:usage_details"))

        text = self._rendered_text(update)
        self.assertIn("<b>usage&lt;g&gt;</b>", text)
        self.assertNotIn("usage<g>", text)

    def test_usage_details_relabeled_and_uses_quota_emoji(self):
        """R9/R8: usage panel header is «مصرف ۲۴ ساعته» and quota rows use
        🔋/🪫 per the emoji dictionary."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "custom_gpt",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
            max_daily_req=5,
        )
        update = self._make_callback_update("admin:fallback:usage_details")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "fallback:usage_details"))

        text = self._rendered_text(update)
        self.assertIn("مصرف ۲۴ ساعته", text)
        self.assertNotIn("مصرف روزانه", text)
        self.assertRegex(text, r"[🔋🪫]")

    def test_fallback_panel_status_primary(self):
        """R8: fallback panel shows «🎯 Primary Active» when fallback is off."""
        from handlers.admin import _handle_admin_callback

        db.set_fallback_active(False)
        update = self._make_callback_update("admin:ai_fallback")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_fallback"))

        text = self._rendered_text(update)
        self.assertIn("🎯 Primary Active", text)
        self.assertNotIn("🔴", text)
        self.assertNotIn("🟢", text)

    def test_fallback_panel_status_normal_tier(self):
        """R8: fallback on with a normal-tier preset → «🎯 Fallback ACTIVE»."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "backup_normal",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
            is_emergency=0,
        )
        db.set_setting("ai_fallback_preset", "backup_normal")
        db.set_fallback_active(True)
        update = self._make_callback_update("admin:ai_fallback")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_fallback"))

        text = self._rendered_text(update)
        self.assertIn("🎯 Fallback ACTIVE", text)
        self.assertNotIn("🛡️", text)
        self.assertNotIn("🔴", text)

    def test_fallback_panel_status_emergency_tier(self):
        """R8: fallback on with an emergency-tier preset → «🎯 🛡️ Emergency
        ACTIVE», combining live-routing and critical-tier markers."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "backup_emergency",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
            is_emergency=1,
        )
        db.set_setting("ai_fallback_preset", "backup_emergency")
        db.set_fallback_active(True)
        update = self._make_callback_update("admin:ai_fallback")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_fallback"))

        text = self._rendered_text(update)
        self.assertIn("🎯 🛡️ Emergency ACTIVE", text)
        self.assertNotIn("🔴", text)
        self.assertNotIn("🟢", text)

    def test_ai_settings_no_active_preset_shows_notice(self):
        """Kilo R5: the AI settings panel must not crash when no active preset exists;
        it shows a Persian notice instead of degrading to a ghost default."""
        from handlers.admin import _handle_admin_callback

        # Make sure no preset is enabled.
        for p in db.get_presets():
            db.delete_preset(p["name"])

        update = self._make_callback_update("admin:ai_settings")
        ctx = self._make_context()
        # Must not raise NoActivePresetError.
        asyncio.run(_handle_admin_callback(update, ctx, "ai_settings"))

        text = self._rendered_text(update)
        self.assertIn("پیش‌تنظیم فعالی وجود ندارد", text)

    def test_ai_settings_with_active_preset_renders_html_bold(self):
        """T8a: the settings panel renders HTML bold via send_pretty spans, with
        the dynamic values escaped and the bold labels byte-identical to the
        pre-migration HTML output."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "span_active",
            base_url="https://api.example.com",
            model="gpt-test <x>",
            enabled=1,
        )
        db.set_setting("ai_primary_preset", "span_active")

        update = self._make_callback_update("admin:ai_settings")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_settings"))

        text = self._rendered_text(update)
        # Bold labels stay HTML.
        self.assertIn("<b>تنظیمات هوش مصنوعی</b>", text)
        self.assertIn("<b>پیش‌تنظیم فعال:</b> span_active", text)
        # Dynamic value with a reserved HTML char is escaped by the renderer.
        self.assertIn("gpt-test &lt;x&gt;", text)
        self.assertNotIn("gpt-test <x>", text)

    # --- Draft-indicator ticket (R1-R4) ---

    def test_edit_keyboard_shows_staged_draft_marker_and_value(self):
        """R2 (T2): staged model row carries a ✏️ prefix; values live in the
        menu tables now, not on buttons; callback_data unchanged."""
        from config.keyboards.admin import ai_preset_edit_keyboard
        from services.utils.confirm_summary import FieldDiff

        kb_plain = ai_preset_edit_keyboard("draft_p")
        kb_draft = ai_preset_edit_keyboard("draft_p", [FieldDiff(field="model", label="Model", old="old-model", new="new-model")])
        plain_callbacks = [b.callback_data for row in kb_plain.inline_keyboard for b in row]
        draft_callbacks = [b.callback_data for row in kb_draft.inline_keyboard for b in row]
        self.assertEqual(plain_callbacks, draft_callbacks)

        def _texts(kb):
            return [b.text for row in kb.inline_keyboard for b in row]

        draft_texts = _texts(kb_draft)
        model_row = next(t for t in draft_texts if "Model" in t)
        self.assertTrue(model_row.startswith("✏️"))
        # No button carries stored or draft values anymore.
        for t in draft_texts:
            self.assertNotIn("new-model", t)
            self.assertNotIn("https://api.example.com", t)
        # Unstaged base_url row keeps its label with no marker.
        base_row = next(t for t in draft_texts if "Base URL" in t)
        self.assertNotIn("✏️", base_row)

    def test_edit_keyboard_masks_api_key_draft(self):
        """R3 (T2): staged api_key draft leaves no plaintext on any button."""
        from config.keyboards.admin import ai_preset_edit_keyboard
        from services.utils.confirm_summary import FieldDiff

        kb = ai_preset_edit_keyboard("draft_k", [FieldDiff(field="api_key", label="API Key", old="••••1111", new="••••2222")])
        texts = [b.text for row in kb.inline_keyboard for b in row]
        for t in texts:
            self.assertNotIn("sk-1234567890abcdef", t)
            self.assertNotIn("old-key-value-1234567890", t)
        key_row = next(t for t in texts if "API Key" in t)
        self.assertTrue(key_row.startswith("✏️"))

    def test_edit_menu_shows_pending_count_header(self):
        """R2 (T2): edit menu header shows «N تغییر در انتظار — هنوز ذخیره نشده»."""
        from handlers import admin_ai
        from services.send_pretty import Backend

        db.set_preset("draft_h", base_url="https://api.example.com", model="old", api_key="test")
        ctx = self._make_context()
        ctx.user_data["preset_edits"] = {"draft_h": {"model": "new-model"}}
        update = self._make_callback_update("admin:ai_preset:edit:draft_h")
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say:
            asyncio.run(admin_ai._edit_ai_preset(update, ctx, "draft_h"))
        mock_say.assert_called_once()
        self.assertEqual(mock_say.call_args[1].get("backend"), Backend.RICH)
        text = mock_say.call_args[0][2].render(Backend.RICH)
        self.assertIn("۱ تغییر در انتظار — هنوز ذخیره نشده", text)
        kb = mock_say.call_args[1].get("keyboard")
        self.assertIsNotNone(kb)
        texts = [b.text for row in kb.inline_keyboard for b in row]
        model_row = next(t for t in texts if "Model" in t)
        self.assertTrue(model_row.startswith("✏️"))

    def test_edit_keyboard_empty_draft_still_marks_dirty(self):
        """Empty-string draft still marks the row dirty (✏️ prefix, no value)."""
        from config.keyboards.admin import ai_preset_edit_keyboard
        from services.utils.confirm_summary import FieldDiff

        kb = ai_preset_edit_keyboard("draft_e", [FieldDiff(field="group_label", label="Group Label", old="g", new="—")], has_group=True)
        texts = [b.text for row in kb.inline_keyboard for b in row]
        cleared_row = next(t for t in texts if "Group Label" in t or "برچسب" in t)
        self.assertTrue(cleared_row.startswith("✏️"))
        for t in texts:
            self.assertNotIn("(خالی)", t)

    def test_edit_menu_shows_long_draft_value_full(self):
        """R5 (T2): long/multiline values are NOT truncated — Rich wraps them
        full in the menu table."""
        from handlers import admin_ai
        from services.send_pretty import Backend

        db.set_preset("draft_t", base_url="https://api.example.com", model="old", api_key="test")
        long_draft = "x" * 40 + "multiline-tail"
        ctx = self._make_context()
        ctx.user_data["preset_edits"] = {"draft_t": {"model": long_draft}}
        update = self._make_callback_update("admin:ai_preset:edit:draft_t")
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say:
            asyncio.run(admin_ai._edit_ai_preset(update, ctx, "draft_t"))
        text = mock_say.call_args[0][2].render(Backend.RICH)
        self.assertIn(f"`{long_draft}`", text)

    def test_edit_keyboard_rejects_non_field_diff_items(self):
        """T6: non-FieldDiff dirty state fails fast at the keyboard boundary."""
        from config.keyboards.admin import ai_preset_edit_keyboard

        with self.assertRaises(TypeError):
            ai_preset_edit_keyboard("draft_b", ["model"])  # type: ignore[list-item]
        with self.assertRaises(TypeError):
            ai_preset_edit_keyboard("draft_b", {"model": "x"})  # type: ignore[arg-type]

    def test_single_field_confirm_mentions_draft_and_needs_save(self):
        """R6 (T2) + T9: staging sends no toast and re-renders the menu
        once — the menu's just_staged line is the sole staged feedback."""
        from handlers import admin_ai
        from services.send_pretty import Backend

        db.set_preset("draft_c", base_url="https://api.example.com", model="old", api_key="test")
        ctx = self._make_context()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = None
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        update.message = msg
        update.message.text = "new-model"
        with patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say, \
                patch("handlers.admin_ai.notify_callback", new=AsyncMock()) as mock_notify:
            asyncio.run(admin_ai._handle_ai_preset_field_input(update, ctx, "draft_c", "model", "new-model"))
        self.assertEqual(ctx.user_data["preset_edits"]["draft_c"]["model"], "new-model")
        # Single menu re-render, no extra ✅ message, no toast.
        mock_say.assert_called_once()
        msg.reply_text.assert_not_called()
        mock_notify.assert_not_called()
        menu_text = mock_say.call_args[0][2].render(Backend.RICH)
        self.assertIn("«Model»", menu_text)
        self.assertIn("نگه داشته شد", menu_text)


    def test_preset_view_shows_24h_usage_stats(self):
        """T8 (U3): the preset view appends the 24h usage-stats block with the
        seeded values in Persian digits (one cheap get_hourly_usage read)."""
        import datetime

        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "stats_p",
            base_url="https://api.example.com",
            model="gpt",
            api_key="test",
            enabled=1,
        )
        bucket = datetime.datetime.now(datetime.timezone.utc).isoformat()[:13]
        db.increment_hourly_usage("stats_p", bucket, req_count=3, token_count=1500)

        update = self._make_callback_update("admin:ai_preset:view:stats_p")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_preset:view:stats_p"))

        text = self._rendered_text(update)
        self.assertIn("مصرف ۲۴ ساعته", text)
        self.assertIn("درخواست‌ها: ۳ | توکن‌ها: ۱۵۰۰", text)

    def test_preset_view_zero_usage_renders_graceful_empty(self):
        """T8 (U3): a preset with no usage rows still renders the stats block
        with ۰ values — no crash on missing rows."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "stats_empty",
            base_url="https://api.example.com",
            model="gpt",
            enabled=1,
        )
        update = self._make_callback_update("admin:ai_preset:view:stats_empty")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_preset:view:stats_empty"))

        text = self._rendered_text(update)
        self.assertIn("مصرف ۲۴ ساعته", text)
        self.assertIn("درخواست‌ها: ۰ | توکن‌ها: ۰", text)


if __name__ == "__main__":
    unittest.main()
