"""C2: admin danger (red) buttons carry style=DANGER; all others stay neutral.

Locked contract: plan-20260904-button-style-standard.md (R1/R3).
Danger = irreversible only. ``✅ بله...`` confirms with destructive meaning
are danger despite the ✅ (reset_confirm, block_confirm).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.constants import KeyboardButtonStyle

from config.keyboards.admin import (
    ai_fallback_keyboard,
    ai_preset_edit_keyboard,
    ai_preset_view_keyboard,
    ai_presets_list_keyboard,
    ai_settings_keyboard,
    backup_restore_keyboard,
    broadcast_preview_keyboard,
    dm_preview_keyboard,
    llm_cost_dashboard_keyboard,
    plan_wizard_summary_keyboard,
    tts_cache_keyboard,
    user_block_confirm_keyboard,
    user_plan_confirm_keyboard,
    user_plan_picker_keyboard,
    user_profile_keyboard,
    user_reset_confirm_keyboard,
)

DANGER = KeyboardButtonStyle.DANGER
SUCCESS = KeyboardButtonStyle.SUCCESS
PRIMARY = KeyboardButtonStyle.PRIMARY


def _find(markup, callback_data):
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data == callback_data:
                return btn
    raise AssertionError(f"button {callback_data!r} not found")


def _find_prefix(markup, prefix):
    for row in markup.inline_keyboard:
        for btn in row:
            if (btn.callback_data or "").startswith(prefix):
                return btn
    raise AssertionError(f"button with prefix {prefix!r} not found")


class TestAdminDangerButtons(unittest.TestCase):
    def test_reset_confirm_is_danger(self):
        btn = _find(user_reset_confirm_keyboard(7), "admin:user:reset_confirm:7")
        self.assertEqual(btn.text, "✅ بله، ریست شود")
        self.assertEqual(btn.style, DANGER)

    def test_block_confirm_is_danger(self):
        btn = _find(user_block_confirm_keyboard(7), "admin:user:block_confirm:7")
        self.assertEqual(btn.text, "✅ بله مسدود کن")
        self.assertEqual(btn.style, DANGER)

    def test_preset_list_delete_is_danger(self):
        markup = ai_presets_list_keyboard([{"name": "p1"}], "other")
        deletes = [
            btn
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data.startswith("admin:ai_preset:delete:")
        ]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0].style, DANGER)

    def test_preset_view_delete_is_danger(self):
        markup = ai_preset_view_keyboard({"name": "p1"}, "other")
        deletes = [
            btn
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data.startswith("admin:ai_preset:delete:")
        ]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0].style, DANGER)


class TestAdminNonDangerStayNeutral(unittest.TestCase):
    def _assert_neutral(self, markup, skip=()):
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.callback_data in skip:
                    continue
                self.assertIsNone(
                    btn.style,
                    f"expected neutral: {btn.text!r} ({btn.callback_data!r}) got {btn.style}",
                )

    def test_confirm_siblings_neutral(self):
        self._assert_neutral(
            user_reset_confirm_keyboard(7), skip={"admin:user:reset_confirm:7"}
        )
        self._assert_neutral(
            user_block_confirm_keyboard(7), skip={"admin:user:block_confirm:7"}
        )
        # Plan change is reversible -> NOT danger; C3 styles it SUCCESS.
        self._assert_neutral(
            user_plan_confirm_keyboard(7, "gold"),
            skip={"admin:user:plan_confirm:7:gold"},
        )

    def test_profile_entries_neutral(self):
        # Entries merely open the confirm step; execution buttons carry danger.
        self._assert_neutral(user_profile_keyboard(7, False))
        self._assert_neutral(user_profile_keyboard(7, True))

    def test_settings_buttons_neutral(self):
        # Reversible setting writes (re-settable IDs), not irreversible loss.
        # C3: test-action buttons carry PRIMARY (skipped here, asserted below).
        self._assert_neutral(tts_cache_keyboard(""), skip={"admin:tts_cache:test"})
        self._assert_neutral(
            backup_restore_keyboard(), skip={"admin:backup_restore:test_archive"}
        )
        self._assert_neutral(ai_fallback_keyboard("a", "b", "a"))

    def test_preset_list_view_non_delete_neutral(self):
        markup = ai_presets_list_keyboard([{"name": "p1"}], "other")
        skip = {
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data.startswith("admin:ai_preset:delete:")
        }
        self._assert_neutral(markup, skip=skip)
        markup = ai_preset_view_keyboard({"name": "p1"}, "other")
        skip = {
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            # C2 danger + C3 PRIMARY test action.
            if btn.callback_data.startswith("admin:ai_preset:delete:")
            or btn.callback_data.startswith("admin:ai_preset:test:")
        }
        self._assert_neutral(markup, skip=skip)

    def test_preset_edit_discard_neutral(self):
        # Discard drops unsaved drafts only (no DB loss) -> not danger.
        # C3: the save button carries SUCCESS (skipped here, asserted below).
        markup = ai_preset_edit_keyboard("p1")
        skip = {
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            if (btn.callback_data or "").startswith("admin:ai_preset:save:")
        }
        self._assert_neutral(markup, skip=skip)

    def test_preview_wizard_siblings_neutral(self):
        # Edit/cancel/close siblings of SUCCESS confirms carry no style.
        self._assert_neutral(
            dm_preview_keyboard(7), skip={"admin:user:msg_confirm:7"}
        )
        self._assert_neutral(
            broadcast_preview_keyboard(), skip={"admin:broadcast_confirm"}
        )
        self._assert_neutral(
            plan_wizard_summary_keyboard("gold"),
            skip={"admin:plans:full_edit_save:gold"},
        )


class TestPresetDeleteConfirmHandlerDanger(unittest.TestCase):
    """C2b: handler-built delete-confirm screen carries DANGER on the
    confirm-delete execution button (``confirm_delete_yes``)."""

    def test_delete_confirm_screen_confirm_is_danger(self):
        from handlers.admin_ai import _delete_ai_preset

        update = MagicMock()
        context = MagicMock()
        with (
            patch(
                "handlers.admin_ai.db.get_preset",
                return_value={"name": "p1"},
            ),
            patch(
                "handlers.admin_ai.db.get_active_preset_name",
                return_value="other",
            ),
            patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say,
        ):
            asyncio.run(_delete_ai_preset(update, context, "p1"))
        mock_say.assert_called_once()
        markup = mock_say.call_args[1].get("keyboard")
        self.assertIsNotNone(markup, "delete-confirm screen must pass a keyboard")
        btn = _find_prefix(markup, "admin:ai_preset:confirm_delete_yes:")
        self.assertEqual(btn.text, "✅ بله، حذف کن")
        self.assertEqual(btn.style, DANGER)

    def test_delete_confirm_screen_cancel_stays_neutral(self):
        from handlers.admin_ai import _delete_ai_preset

        update = MagicMock()
        context = MagicMock()
        with (
            patch(
                "handlers.admin_ai.db.get_preset",
                return_value={"name": "p1"},
            ),
            patch(
                "handlers.admin_ai.db.get_active_preset_name",
                return_value="other",
            ),
            patch("handlers.admin_ai.say", new=AsyncMock()) as mock_say,
        ):
            asyncio.run(_delete_ai_preset(update, context, "p1"))
        markup = mock_say.call_args[1].get("keyboard")
        btn = _find_prefix(markup, "admin:ai_preset:confirm_delete_no:")
        self.assertIsNone(
            btn.style, f"expected neutral cancel, got {btn.style}",
        )


class TestFullEditWizardSaveHandlerSuccess(unittest.TestCase):
    """C3b: handler-built full-edit wizard summary (``ai_preset:full_edit_save``)
    carries SUCCESS on the save-all button only; cancel stays neutral."""

    def _run_summary(self, mock_say):
        from handlers.admin_ai import _show_wizard_summary

        update = MagicMock()
        context = MagicMock()
        context.user_data = {"full_edit": {"preset": "p1", "values": {}}}
        with (
            patch(
                "handlers.admin_ai.db.get_preset",
                return_value={"name": "p1"},
            ),
            patch("handlers.admin_ai.say", new=mock_say),
        ):
            asyncio.run(_show_wizard_summary(update, context, "p1"))
        return mock_say.call_args[1].get("keyboard")

    def test_wizard_save_is_success(self):
        markup = self._run_summary(AsyncMock())
        self.assertIsNotNone(markup, "wizard summary must pass a keyboard")
        btn = _find_prefix(markup, "admin:ai_preset:full_edit_save:")
        self.assertEqual(btn.text, "✅ ذخیره همه تغییرات")
        self.assertEqual(btn.style, SUCCESS)

    def test_wizard_cancel_stays_neutral(self):
        markup = self._run_summary(AsyncMock())
        btn = _find_prefix(markup, "admin:ai_preset:full_edit_cancel:")
        self.assertIsNone(
            btn.style, f"expected neutral cancel, got {btn.style}",
        )


class TestAdminSuccessButtons(unittest.TestCase):
    """C3: save/confirm/apply execution buttons carry style=SUCCESS.

    Each call-site was verified to execute on click: plan_confirm ->
    db.set_plan, msg_confirm -> DM send, broadcast_confirm -> broadcast
    send, preset save -> _confirm_save_preset, wizard save-all ->
    _handle_plan_wizard_save. Labels/callback_data unchanged.
    """

    def test_plan_change_confirm_is_success(self):
        btn = _find(user_plan_confirm_keyboard(7, "gold"), "admin:user:plan_confirm:7:gold")
        self.assertEqual(btn.text, "✅ بله، تغییر بده")
        self.assertEqual(btn.style, SUCCESS)

    def test_dm_confirm_is_success(self):
        btn = _find(dm_preview_keyboard(7), "admin:user:msg_confirm:7")
        self.assertEqual(btn.text, "✅ تایید ارسال")
        self.assertEqual(btn.style, SUCCESS)

    def test_broadcast_confirm_is_success(self):
        btn = _find(broadcast_preview_keyboard(), "admin:broadcast_confirm")
        self.assertEqual(btn.text, "✅ تایید همگانی")
        self.assertEqual(btn.style, SUCCESS)

    def test_preset_edit_save_is_success(self):
        btn = _find_prefix(ai_preset_edit_keyboard("p1"), "admin:ai_preset:save:")
        self.assertEqual(btn.style, SUCCESS)

    def test_plan_wizard_save_all_is_success(self):
        btn = _find(plan_wizard_summary_keyboard("gold"), "admin:plans:full_edit_save:gold")
        self.assertEqual(btn.style, SUCCESS)


class TestAdminPrimaryButtons(unittest.TestCase):
    """C3: test actions and the current-plan marker carry style=PRIMARY.
    Refresh stays neutral (neither forward-progress, current-selection, nor
    a connection test). Labels/callback_data unchanged."""

    def test_preset_view_test_is_primary(self):
        btn = _find_prefix(
            ai_preset_view_keyboard({"name": "p1"}, "other"), "admin:ai_preset:test:"
        )
        self.assertEqual(btn.style, PRIMARY)

    def test_ai_settings_test_buttons_are_primary(self):
        markup = ai_settings_keyboard()
        self.assertEqual(_find(markup, "admin:ai_test_connection").style, PRIMARY)
        self.assertEqual(_find(markup, "admin:ai_custom_test").style, PRIMARY)

    def test_tts_test_is_primary(self):
        btn = _find(tts_cache_keyboard(""), "admin:tts_cache:test")
        self.assertEqual(btn.text, "🧪 تست")
        self.assertEqual(btn.style, PRIMARY)

    def test_archive_test_is_primary(self):
        btn = _find(backup_restore_keyboard(), "admin:backup_restore:test_archive")
        self.assertEqual(btn.style, PRIMARY)

    def test_cost_dashboard_refresh_stays_neutral(self):
        btn = _find(llm_cost_dashboard_keyboard(), "llm:refresh")
        self.assertIsNone(btn.style, f"expected neutral refresh, got {btn.style}")

    def test_current_plan_marker_is_primary_label_untouched(self):
        plans = [
            {"name": "free", "display_name": "رایگان"},
            {"name": "gold", "display_name": "طلایی"},
        ]
        markup = user_plan_picker_keyboard(7, plans, current_plan="gold")
        current_btn = _find(markup, "admin:user:plan_select:7:gold")
        other_btn = _find(markup, "admin:user:plan_select:7:free")
        # Style only: label keeps the ✅…(فعلی) text/emoji marker byte-identical.
        self.assertIn("(فعلی)", current_btn.text)
        self.assertEqual(current_btn.style, PRIMARY)
        self.assertIsNone(other_btn.style)


if __name__ == "__main__":
    unittest.main()
