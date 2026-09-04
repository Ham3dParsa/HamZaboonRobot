"""Integration tests for R2 (stale orphan prompts) + R3 (preset name charset).

R2:
- starting a second awaiting prompt clears the first prompt's keyboard
  (``_rotate_awaiting_msg`` strips markup of the stored ``_awaiting_msg``
  before tracking the new message; restart-safe + idempotent).
- every preset-wizard/single-field-edit awaiting keyboard contains a
  Close button (``admin:close``) alongside flow back/cancel.

R3:
- canonical preset-name validator (``services/ai/preset_fields.py``):
  accepts ``zen_mimo_v2.5_free`` / ``zen_mimo-v25_free``; rejects leading
  dot, trailing hyphen, ``..`` runs, ``:`` and >60 chars.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_ctx():
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot = AsyncMock()
    return ctx


class PresetNameValidatorTest(unittest.TestCase):
    """R3: single source of truth accepts . and - with the locked edge rules."""

    def test_accepts_dot_and_hyphen(self):
        from services.ai.preset_fields import validate_preset_name

        self.assertEqual(validate_preset_name("zen_mimo_v2.5_free"), "zen_mimo_v2.5_free")
        self.assertEqual(validate_preset_name("zen_mimo-v25_free"), "zen_mimo-v25_free")

    def test_accepts_legacy_names(self):
        from services.ai.preset_fields import validate_preset_name

        self.assertEqual(validate_preset_name("my_openai"), "my_openai")
        self.assertEqual(validate_preset_name("GPT4"), "gpt4")

    def test_rejects_leading_dot_trailing_hyphen(self):
        from services.ai.preset_fields import validate_preset_name

        self.assertIsNone(validate_preset_name(".zen"))
        self.assertIsNone(validate_preset_name("zen-"))
        self.assertIsNone(validate_preset_name("-zen"))
        self.assertIsNone(validate_preset_name("zen."))

    def test_rejects_double_runs_and_colon(self):
        from services.ai.preset_fields import validate_preset_name

        self.assertIsNone(validate_preset_name("ze..n"))
        self.assertIsNone(validate_preset_name("ze--n"))
        self.assertIsNone(validate_preset_name("ze:n"))
        self.assertIsNone(validate_preset_name("my_preset!"))

    def test_rejects_overlong_and_empty(self):
        from services.ai.preset_fields import validate_preset_name

        self.assertIsNone(validate_preset_name("n" * 61))
        self.assertEqual(validate_preset_name("n" * 60), "n" * 60)
        self.assertIsNone(validate_preset_name(""))
        self.assertIsNone(validate_preset_name("   "))

    def test_normalizes_spaces_and_case(self):
        from services.ai.preset_fields import validate_preset_name

        self.assertEqual(validate_preset_name("My Preset"), "my_preset")


class RotateAwaitingMsgTest(unittest.TestCase):
    """R2: rotating to a second prompt strips the first prompt's keyboard."""

    def test_rotate_clears_first_keyboard_and_stores_second(self):
        from services.utils.helpers import _rotate_awaiting_msg

        ctx = _make_ctx()
        ctx.user_data["_awaiting_msg"] = {"chat_id": 1, "message_id": 11}
        update = MagicMock()
        update.callback_query = None
        update.effective_message = None
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        new_msg = MagicMock()
        new_msg.message_id = 22
        new_chat = MagicMock()
        new_chat.id = 1
        new_msg.chat = new_chat
        with patch(
            "services.utils.helpers._edit_markup_with_retry", new=AsyncMock()
        ) as mock_edit:
            asyncio.run(_rotate_awaiting_msg(ctx, update, new_msg))
        mock_edit.assert_called_once_with(ctx.bot, 1, 11, None)
        self.assertEqual(
            ctx.user_data["_awaiting_msg"], {"chat_id": 1, "message_id": 22}
        )

    def test_rotate_same_message_skips_strip_and_restores(self):
        """Back-to-back prompts on one message (callback edits reuse it).

        The stored old tuple aliases the just-rendered prompt — stripping it
        would remove the keyboard ``say`` just set. Rotation must skip the
        strip and just (re-)store (opencode WARNING, PR 568).
        """
        from services.utils.helpers import _rotate_awaiting_msg

        ctx = _make_ctx()
        ctx.user_data["_awaiting_msg"] = {"chat_id": 1, "message_id": 11}
        update = MagicMock()
        update.callback_query = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.message_id = 11
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        new_msg = MagicMock()
        new_msg.message_id = 11
        new_chat = MagicMock()
        new_chat.id = 1
        new_msg.chat = new_chat
        with patch(
            "services.utils.helpers._edit_markup_with_retry", new=AsyncMock()
        ) as mock_edit:
            asyncio.run(_rotate_awaiting_msg(ctx, update, new_msg))
        mock_edit.assert_not_called()
        self.assertEqual(
            ctx.user_data["_awaiting_msg"], {"chat_id": 1, "message_id": 11}
        )

    def test_rotate_not_modified_keeps_old_tracking(self):
        """``say`` returning None (edit-not-modified answers the callback).

        Nothing new to track — the old entry must stay intact so a later
        rotation can still strip it (opencode WARNING, PR 568).
        """
        from services.utils.helpers import _rotate_awaiting_msg

        ctx = _make_ctx()
        ctx.user_data["_awaiting_msg"] = {"chat_id": 1, "message_id": 11}
        update = MagicMock()
        update.callback_query = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.message_id = 11
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        with patch(
            "services.utils.helpers._edit_markup_with_retry", new=AsyncMock()
        ) as mock_edit:
            asyncio.run(_rotate_awaiting_msg(ctx, update, None))
        mock_edit.assert_not_called()
        self.assertEqual(
            ctx.user_data["_awaiting_msg"], {"chat_id": 1, "message_id": 11}
        )

    def test_rotate_with_no_previous_prompt_just_stores(self):
        from services.utils.helpers import _rotate_awaiting_msg

        ctx = _make_ctx()
        update = MagicMock()
        update.callback_query = None
        update.effective_message = None
        update.effective_chat = MagicMock()
        update.effective_chat.id = 7
        new_msg = MagicMock()
        new_msg.message_id = 33
        new_chat = MagicMock()
        new_chat.id = 7
        new_msg.chat = new_chat
        with patch(
            "services.utils.helpers._edit_markup_with_retry", new=AsyncMock()
        ) as mock_edit:
            asyncio.run(_rotate_awaiting_msg(ctx, update, new_msg))
        mock_edit.assert_not_called()
        self.assertEqual(
            ctx.user_data["_awaiting_msg"], {"chat_id": 7, "message_id": 33}
        )


class PresetWizardCloseButtonTest(unittest.TestCase):
    """R2: every preset-edit awaiting keyboard offers admin:close."""

    def _callback_datas(self, keyboard):
        return [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]

    def test_preset_edit_keyboard_has_close_back_cancel(self):
        from config.keyboards import preset_edit_awaiting_inline_keyboard

        datas = self._callback_datas(preset_edit_awaiting_inline_keyboard())
        self.assertIn("admin:close", datas)
        self.assertIn("flow:back", datas)
        self.assertIn("flow:cancel", datas)

    def test_field_edit_prompt_uses_close_keyboard(self):
        from handlers.admin_ai import _edit_ai_preset_field

        update = MagicMock()
        update.callback_query = MagicMock()
        update.effective_message = MagicMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        ctx = _make_ctx()
        with patch("handlers.admin_ai.db.get_preset", return_value={"name": "p"}), \
             patch("handlers.admin_ai.say", new=AsyncMock(return_value=None)), \
             patch(
                 "handlers.admin_ai._rotate_awaiting_msg", new=AsyncMock()
             ) as mock_rotate:
            asyncio.run(_edit_ai_preset_field(update, ctx, "p", "model"))
        mock_rotate.assert_called_once()

    def test_field_edit_prompt_keyboard_contains_close(self):
        from handlers.admin_ai import _edit_ai_preset_field

        update = MagicMock()
        update.callback_query = MagicMock()
        update.effective_message = MagicMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        ctx = _make_ctx()
        with patch("handlers.admin_ai.db.get_preset", return_value={"name": "p"}), \
             patch("handlers.admin_ai.say", new=AsyncMock(return_value=None)) as mock_say, \
             patch("handlers.admin_ai._rotate_awaiting_msg", new=AsyncMock()):
            asyncio.run(_edit_ai_preset_field(update, ctx, "p", "model"))
        keyboard = mock_say.call_args[1]["keyboard"]
        self.assertIn("admin:close", self._callback_datas(keyboard))

    def test_field_retry_prompt_keyboard_contains_close(self):
        from handlers.admin_ai import _handle_ai_preset_field_input

        msg = MagicMock()
        msg.text = "!!!"
        update = MagicMock()
        update.message = msg
        update.callback_query = None
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        ctx = _make_ctx()
        with patch(
            "handlers.admin_ai.db.get_preset",
            return_value={"name": "p", "model": "m"},
        ), patch("handlers.admin_ai.say", new=AsyncMock(return_value=None)) as mock_say, \
            patch("handlers.admin_ai._rotate_awaiting_msg", new=AsyncMock()):
            asyncio.run(_handle_ai_preset_field_input(update, ctx, "p", "max_concurrency", "!!!"))
        keyboard = mock_say.call_args[1]["keyboard"]
        self.assertIn("admin:close", self._callback_datas(keyboard))


if __name__ == "__main__":
    unittest.main()
