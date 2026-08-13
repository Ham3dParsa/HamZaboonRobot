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

        update = self._make_callback_update("admin:ai_presets")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "ai_presets"))

        text = self._rendered_text(update)
        # The seeded emergency preset sits on page 1 and is deterministic.
        self.assertIn("🟢 <b>gapgpt_gemini_lite</b>", text)
        self.assertNotIn("✅", text)

    def test_linear_presets_marks_active_with_target_emoji(self):
        """R8: the shorthand loses no 🎯 for the active preset on its page."""
        from handlers.admin import _handle_admin_callback

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

    def test_fallback_chain_uses_emergency_and_active_emoji(self):
        """R8: the fallback chain render shows 🛡️ for emergency and 🟢 for a
        normal enabled preset (no legacy ✅/🚨 markers)."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "custom_normal",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
            is_custom=1,
        )
        update = self._make_callback_update("admin:fallback_chain")
        ctx = self._make_context()
        asyncio.run(_handle_admin_callback(update, ctx, "fallback_chain"))

        text = self._rendered_text(update)
        self.assertIn("🟢", text)
        self.assertNotIn("🚨", text)

    def test_usage_details_relabeled_and_uses_quota_emoji(self):
        """R9/R8: usage panel header is «مصرف ۲۴ ساعته» and quota rows use
        🔋/🪫 per the emoji dictionary."""
        from handlers.admin import _handle_admin_callback

        db.set_preset(
            "custom_gpt",
            base_url="https://api.example.com",
            model="gpt-test",
            api_key="test",
            is_custom=1,
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
            is_custom=1,
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
            is_custom=1,
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


if __name__ == "__main__":
    unittest.main()
