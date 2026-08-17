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


if __name__ == "__main__":
    unittest.main()
