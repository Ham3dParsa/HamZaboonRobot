"""Integration tests for R3 64-byte callback limit on handler-built keyboards
and R10 HTML escaping in admin_ai render sites.

Extends the routing seam (dispatch through _handle_admin_callback / handle_ai_callback)
to cover keyboards built inside handlers (full-edit wizard, summary, save-confirm)
that previously emitted raw preset names.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema

# A long custom preset name (within the 60-char R11 cap) that overflows raw callbacks.
LONG_NAME = "x" * 60


def _collect(data) -> list[str]:
    out = []
    for row in (data or []):
        for btn in row:
            if getattr(btn, "callback_data", None):
                out.append(btn.callback_data)
    return out


class HandlerBuiltCallbackByteLimitTest(unittest.TestCase):
    """full_edit_*/confirm_save_* callbacks built inside handlers must be <= 64 bytes."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        db.create_user_if_needed(1, "owner")
        db.set_preset(name=LONG_NAME, base_url="https://x", model="m", api_key="sk-123", is_custom=1)
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def _make_callback_update(self, data: str):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        return update

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_full_edit_wizard_buttons_under_64(self):
        """full_edit_next/skip/cancel on the wizard field keyboard must be <= 64 bytes
        even with a 60-char preset name."""
        from handlers.admin_ai import _show_wizard_field
        from config.keyboards import IBTN_FULL_EDIT_NEXT

        preset = db.get_preset(LONG_NAME)
        ctx = self._context()
        update = self._make_callback_update("admin:noop")
        asyncio.run(_show_wizard_field(update, ctx, LONG_NAME, 0, preset))

        # The keyboard is passed via reply_markup to edit_message_text
        render_call = update.callback_query.edit_message_text.call_args
        markup = render_call.kwargs.get("reply_markup") if render_call.kwargs else None
        self.assertIsNotNone(markup, "expected a rendered wizard keyboard")
        for cb in _collect(markup.inline_keyboard):
            self.assertLessEqual(len(cb.encode("utf-8")), 64, cb)

    def test_edit_field_under_64_with_long_name(self):
        """ai_preset_edit_keyboard callbacks must stay under 64 with a 60-char name."""
        from config.keyboards import ai_preset_edit_keyboard
        preset = {"name": LONG_NAME, "is_custom": 1, "model": "m", "base_url": "u"}
        markup = ai_preset_edit_keyboard(LONG_NAME, preset)
        for cb in _collect(markup.inline_keyboard):
            self.assertLessEqual(len(cb.encode("utf-8")), 64, cb)


class AiConnectionEscapingTest(unittest.TestCase):
    """_test_ai_connection must escape AI-provider output (R10 / D2)."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        db.create_user_if_needed(1, "owner")
        db.set_preset(name="custom_gpt", base_url="https://x", model="m", api_key="sk-123", is_custom=1)
        db.set_setting("ai_primary_preset", "custom_gpt")
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def _make_callback_update(self, data: str):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        return update

    def test_ai_connection_error_message_escaped(self):
        """An error_message with '<' must render escaped, not break HTML parse."""
        from handlers.admin_ai import _test_ai_connection

        ctx = self._context()
        update = self._make_callback_update("admin:ai_test_connection")

        result = {
            "success": False,
            "error_class": "BadRequest",
            "error_message": "unexpected <tag> & broken",
            "latency_ms": 10,
        }
        with patch("handlers.admin_ai.ai.test_connection", return_value=result):
            asyncio.run(_test_ai_connection(update, ctx))

        rendered = update.callback_query.edit_message_text.call_args[0][0]
        self.assertIn("&lt;tag&gt;", rendered)
        self.assertIn("&amp;", rendered)
        self.assertNotIn("unexpected <tag>", rendered)

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx


class GroupLabelCallbackSafetyTest(unittest.TestCase):
    """Stale group-label callbacks must not leak their hash into pending edits."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        db.create_user_if_needed(1, "owner")
        db.set_preset(name="custom_preset", base_url="https://x", model="m", is_custom=1)
        db.set_preset(
            name="grouped_preset",
            base_url="https://x",
            model="m",
            is_custom=1,
            group_label="legacy label",
        )
        db.set_preset(
            name="hash_like_grouped_preset",
            base_url="https://x",
            model="m",
            is_custom=1,
            group_label="abcdef123456",
        )
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def _callback_update(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        return update

    def _text_update(self):
        update = MagicMock()
        update.callback_query = None
        update.message.reply_text = AsyncMock()
        return update

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_stale_hash_is_rejected_without_changing_wizard_or_database(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        context.user_data["full_edit"] = {
            "preset": "custom_preset",
            "values": {},
            "field_idx": 17,
        }

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:full_edit_pick_group:{preset_token('custom_preset')}:000000000000",
            )
        )

        self.assertEqual(context.user_data["full_edit"]["values"], {})
        self.assertEqual(db.get_preset("custom_preset")["group_label"], "")
        update.callback_query.answer.assert_awaited_once_with(
            "برچسب گروه یافت نشد. دوباره ویرایش را باز کنید.",
            show_alert=True,
        )

    def test_legacy_plain_label_callback_still_selects_the_existing_label(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        context.user_data["full_edit"] = {
            "preset": "custom_preset",
            "values": {},
            "field_idx": 17,
        }

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:full_edit_pick_group:{preset_token('custom_preset')}:legacy%20label",
            )
        )

        self.assertEqual(context.user_data["full_edit"]["values"]["group_label"], "legacy label")

    def test_legacy_hash_like_label_callback_still_selects_the_existing_label(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        context.user_data["full_edit"] = {
            "preset": "custom_preset",
            "values": {},
            "field_idx": 17,
        }

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:full_edit_pick_group:{preset_token('custom_preset')}:abcdef123456",
            )
        )

        self.assertEqual(context.user_data["full_edit"]["values"]["group_label"], "abcdef123456")

    def test_stale_group_manager_rename_is_rejected_without_awaiting_state(self):
        from handlers.admin import _handle_admin_callback

        update = self._callback_update()
        context = self._context()

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                "ai_preset:group_manager_rename:000000000000",
            )
        )

        self.assertNotIn("awaiting", context.user_data)
        update.callback_query.answer.assert_awaited_once_with(
            "برچسب گروه یافت نشد.",
            show_alert=True,
        )

    def test_stale_group_manager_clear_is_rejected_without_database_change(self):
        from handlers.admin import _handle_admin_callback

        update = self._callback_update()
        context = self._context()

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                "ai_preset:group_manager_clear:000000000000",
            )
        )

        self.assertEqual(db.get_preset("grouped_preset")["group_label"], "legacy label")
        update.callback_query.answer.assert_awaited_once_with(
            "برچسب گروه یافت نشد.",
            show_alert=True,
        )

    def test_rename_confirmation_keeps_group_label_plain_text(self):
        from handlers.admin_ai import _handle_ai_text_input

        update = self._text_update()
        context = self._context()
        awaiting = "admin_group_manager_rename:legacy%20label"

        asyncio.run(
            _handle_ai_text_input(update, context, awaiting, "old&new")
        )

        confirmation = update.message.reply_text.await_args_list[0].args[0]
        self.assertIn("old&new", confirmation)
        self.assertIn("legacy label", confirmation)
        self.assertNotIn("&amp;", confirmation)


class PerPresetGroupDetachmentTest(unittest.TestCase):
    """A custom preset can leave a group without changing its peers."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path
        db.init_db()
        db.create_user_if_needed(1, "owner")
        for name in ("target_preset", "peer_preset", "ungrouped_preset"):
            db.set_preset(
                name=name,
                base_url="https://x",
                model="m",
                is_custom=1,
                group_label="shared group" if name != "ungrouped_preset" else "",
            )
        db.set_preset(
            name="solo_preset",
            base_url="https://x",
            model="m",
            is_custom=1,
            group_label="solo group",
        )
        db.set_preset(
            name="000000000000",
            base_url="https://x",
            model="m",
            is_custom=1,
            group_label="hash-named group",
        )
        db.set_group_key("shared group", "$SHARED_GROUP_KEY")
        db.set_group_key("solo group", "$SOLO_GROUP_KEY")
        self.owner_patcher = patch("handlers.admin.is_owner", return_value=True)
        self.owner_patcher.start()
        self.addCleanup(self.owner_patcher.stop)

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def _callback_update(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        return update

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    def test_edit_keyboard_emits_detach_only_for_grouped_preset(self):
        from config.keyboards import ai_preset_edit_keyboard
        from services.utils.callback_codec import preset_token

        grouped = ai_preset_edit_keyboard("target_preset", db.get_preset("target_preset"))
        ungrouped = ai_preset_edit_keyboard("ungrouped_preset", db.get_preset("ungrouped_preset"))

        grouped_callbacks = _collect(grouped.inline_keyboard)
        ungrouped_callbacks = _collect(ungrouped.inline_keyboard)
        detach_callback = f"admin:ai_preset:detach_group:{preset_token('target_preset')}"
        self.assertIn(detach_callback, grouped_callbacks)
        self.assertLessEqual(len(detach_callback.encode("utf-8")), 64)
        self.assertFalse(any("detach_group" in callback for callback in ungrouped_callbacks))

    def test_saved_detach_only_clears_selected_preset_group_label(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        preset_ref = preset_token("target_preset")

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_ref}",
            )
        )

        self.assertEqual(context.user_data["preset_edits"]["target_preset"]["group_label"], "")
        self.assertEqual(db.get_preset("target_preset")["group_label"], "shared group")
        self.assertEqual(db.get_preset("peer_preset")["group_label"], "shared group")
        update.callback_query.answer.assert_awaited_once_with(
            "✅ حذف از گروه ثبت شد. برای اعمال، ذخیره را بزنید.",
            show_alert=False,
        )

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:confirm_save_yes:{preset_ref}",
            )
        )

        self.assertEqual(db.get_preset("target_preset")["group_label"], "")
        self.assertEqual(db.get_preset("peer_preset")["group_label"], "shared group")

    def test_discarded_detach_preserves_stored_group_label(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        preset_ref = preset_token("target_preset")

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_ref}",
            )
        )
        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:discard_all:{preset_ref}",
            )
        )

        self.assertEqual(db.get_preset("target_preset")["group_label"], "shared group")
        self.assertNotIn("target_preset", context.user_data.get("preset_edits", {}))

    def test_stale_detach_token_cannot_target_a_hash_named_preset(self):
        from handlers.admin import _handle_admin_callback

        update = self._callback_update()
        context = self._context()

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                "ai_preset:detach_group:000000000000",
            )
        )

        self.assertNotIn("preset_edits", context.user_data)
        self.assertEqual(db.get_preset("000000000000")["group_label"], "hash-named group")
        update.callback_query.answer.assert_awaited_once_with(
            "پیش‌تنظیم یافت نشد",
            show_alert=True,
        )

    def test_detaching_final_member_deletes_its_orphaned_shared_key(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        preset_ref = preset_token("solo_preset")

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_ref}",
            )
        )
        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:confirm_save_yes:{preset_ref}",
            )
        )

        self.assertEqual(db.get_preset("solo_preset")["group_label"], "")
        self.assertIsNone(db.get_group_key("solo group"))

    def test_detaching_one_of_several_members_keeps_the_shared_key(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        preset_ref = preset_token("target_preset")

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_ref}",
            )
        )
        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:confirm_save_yes:{preset_ref}",
            )
        )

        self.assertEqual(db.get_group_key("shared group"), "$SHARED_GROUP_KEY")

    def test_saved_detach_with_rename_deletes_the_orphaned_shared_key(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        preset_ref = preset_token("solo_preset")

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_ref}",
            )
        )
        context.user_data["preset_edits"]["solo_preset"]["name"] = "renamed_solo"
        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:confirm_save_yes:{preset_ref}",
            )
        )

        self.assertIsNone(db.get_preset("solo_preset"))
        self.assertEqual(db.get_preset("renamed_solo")["group_label"], "")
        self.assertIsNone(db.get_group_key("solo group"))

    def test_rename_detach_save_rolls_back_when_old_preset_removal_fails(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        preset_ref = preset_token("solo_preset")

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_ref}",
            )
        )
        context.user_data["preset_edits"]["solo_preset"]["name"] = "renamed_solo"
        with db.get_conn() as conn:
            conn.execute(
                "CREATE TRIGGER reject_solo_delete BEFORE DELETE ON ai_presets "
                "WHEN OLD.name = 'solo_preset' "
                "BEGIN SELECT RAISE(ABORT, 'simulated delete failure'); END"
            )
            conn.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            asyncio.run(
                _handle_admin_callback(
                    update,
                    context,
                    f"ai_preset:confirm_save_yes:{preset_ref}",
                )
            )

        self.assertEqual(db.get_preset("solo_preset")["group_label"], "solo group")
        self.assertIsNone(db.get_preset("renamed_solo"))
        self.assertEqual(db.get_group_key("solo group"), "$SOLO_GROUP_KEY")

    def test_full_edit_is_blocked_while_detach_is_pending(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        preset_ref = preset_token("target_preset")

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_ref}",
            )
        )
        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:full_edit:{preset_ref}",
            )
        )

        self.assertNotIn("full_edit", context.user_data)
        self.assertEqual(
            update.callback_query.answer.await_args_list[-1].args[0],
            "ابتدا تغییرات فعلی را ذخیره یا دور بریزید.",
        )

    def test_late_rename_collision_preserves_both_presets_and_pending_detach(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        preset_ref = preset_token("solo_preset")

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_ref}",
            )
        )
        context.user_data["preset_edits"]["solo_preset"]["name"] = "claimed_name"
        db.set_preset(
            name="claimed_name",
            base_url="https://protected",
            model="protected-model",
            is_custom=1,
            group_label="protected group",
        )

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:confirm_save_yes:{preset_ref}",
            )
        )

        self.assertEqual(db.get_preset("solo_preset")["group_label"], "solo group")
        self.assertEqual(db.get_preset("claimed_name")["model"], "protected-model")
        self.assertEqual(
            context.user_data["preset_edits"]["solo_preset"],
            {"group_label": "", "name": "claimed_name"},
        )
        update.callback_query.answer.assert_awaited_with(
            "این نام هم‌اکنون توسط پیش‌تنظیم دیگری استفاده می‌شود.",
            show_alert=True,
        )

    def test_detach_is_blocked_while_full_edit_is_active(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()
        preset_ref = preset_token("target_preset")

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:full_edit:{preset_ref}",
            )
        )
        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_ref}",
            )
        )

        self.assertEqual(context.user_data["full_edit"]["preset"], "target_preset")
        self.assertNotIn("preset_edits", context.user_data)
        self.assertEqual(
            update.callback_query.answer.await_args_list[-1].args[0],
            "ابتدا ویرایش کامل را تمام یا لغو کنید.",
        )

    def test_full_edit_is_blocked_by_pending_edits_for_another_preset(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_token('target_preset')}",
            )
        )
        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:full_edit:{preset_token('solo_preset')}",
            )
        )

        self.assertNotIn("full_edit", context.user_data)
        self.assertEqual(
            update.callback_query.answer.await_args_list[-1].args[0],
            "ابتدا تغییرات فعلی را ذخیره یا دور بریزید.",
        )

    def test_detach_is_blocked_by_full_edit_for_another_preset(self):
        from handlers.admin import _handle_admin_callback
        from services.utils.callback_codec import preset_token

        update = self._callback_update()
        context = self._context()

        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:full_edit:{preset_token('target_preset')}",
            )
        )
        asyncio.run(
            _handle_admin_callback(
                update,
                context,
                f"ai_preset:detach_group:{preset_token('solo_preset')}",
            )
        )

        self.assertEqual(context.user_data["full_edit"]["preset"], "target_preset")
        self.assertNotIn("preset_edits", context.user_data)
        self.assertEqual(
            update.callback_query.answer.await_args_list[-1].args[0],
            "ابتدا ویرایش کامل را تمام یا لغو کنید.",
        )


if __name__ == "__main__":
    unittest.main()
