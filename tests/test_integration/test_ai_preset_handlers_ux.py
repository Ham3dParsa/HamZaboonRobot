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
        defaults = {"base_url": "https://x", "model": "m", "is_custom": 1, "priority": 0}
        defaults.update(kwargs)
        db.set_preset(name=name, **defaults)


class AiPresetDeleteConfirmFlowTest(_Phase3AiPresetFlowBase):
    """R3: deleting a custom preset requires a two-step inline confirm."""

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

    def test_duplicate_forces_clone_is_custom(self):
        # Even when duplicating a non-custom (built-in-like) preset, the clone
        # must be is_custom=1 so it is immediately editable in the UI.
        self._make_preset("builtin_like", is_custom=0)
        self._callback(f"ai_preset:duplicate:{db_resolve('builtin_like')}")
        clone = db.get_preset("builtin_like (copy)")
        self.assertIsNotNone(clone)
        self.assertEqual(clone["is_custom"], 1, "duplicate must force is_custom=1")


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


def db_resolve(name: str) -> str:
    from services.utils.callback_codec import preset_token
    return preset_token(name)


if __name__ == "__main__":
    unittest.main()
