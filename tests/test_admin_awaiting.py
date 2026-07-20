"""Test that all admin/ai awaiting flows re-arm on validation failure."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Update, Message, CallbackQuery, Chat, User


def _make_update(user_id: int = 123, text: str = "") -> Update:
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = user_id
    update.message = MagicMock(spec=Message)
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.callback_query = MagicMock(spec=CallbackQuery)
    update.callback_query.answer = AsyncMock()
    return update


def _make_context() -> MagicMock:
    context = MagicMock()
    context.user_data = {}
    context.bot = AsyncMock()
    return context


class TestAiPresetFieldInputReArm(unittest.IsolatedAsyncioTestCase):
    """_handle_ai_preset_field_input must re-arm awaiting on ValueError."""

    async def _run(self, field_name: str, bad_input: str):
        from handlers.admin import _handle_ai_preset_field_input
        update = _make_update(text=bad_input)
        context = _make_context()
        with patch("handlers.admin.db") as mock_db:
            mock_db.get_preset.return_value = {"name": "test", "base_url": "", "model": "",
                                               "daily_batch_size": 6, "max_concurrency": 2,
                                               "max_rpm": 30, "timeout_seconds": 30.0,
                                               "temperature": 0.6, "max_output_tokens": 4096}
            await _handle_ai_preset_field_input(update, context, "test", field_name, bad_input)
        return context, update

    async def test_int_field_bad_input_rearms(self):
        context, _ = await self._run("daily_batch_size", "not_a_number")
        self.assertEqual(context.user_data.get("awaiting"), "ai_preset_edit:test:daily_batch_size")

    async def test_float_field_bad_input_rearms(self):
        context, _ = await self._run("timeout_seconds", "not_a_float")
        self.assertEqual(context.user_data.get("awaiting"), "ai_preset_edit:test:timeout_seconds")

    async def test_temperature_bad_input_rearms(self):
        context, _ = await self._run("temperature", "bad")
        self.assertEqual(context.user_data.get("awaiting"), "ai_preset_edit:test:temperature")

    async def test_max_concurrency_bad_input_rearms(self):
        context, _ = await self._run("max_concurrency", "xyz")
        self.assertEqual(context.user_data.get("awaiting"), "ai_preset_edit:test:max_concurrency")


class TestAiPresetNewNameReArm(unittest.IsolatedAsyncioTestCase):
    """_handle_ai_preset_new_name must re-arm awaiting on validation failure."""

    async def _run(self, name: str, existing_name: str | None = None):
        from handlers.admin import _handle_ai_preset_new_name
        update = _make_update(text=name)
        context = _make_context()
        with patch("handlers.admin.db") as mock_db:
            mock_db.get_preset.return_value = (
                {"name": existing_name} if existing_name else None
            )
            await _handle_ai_preset_new_name(update, context, name)
        return context

    async def test_invalid_name_rearms(self):
        context = await self._run("!!!@@@")
        self.assertEqual(context.user_data.get("awaiting"), "ai_preset_new_name")

    async def test_duplicate_name_rearms(self):
        context = await self._run("existing_name", existing_name="existing_name")
        self.assertEqual(context.user_data.get("awaiting"), "ai_preset_new_name")

    async def test_empty_name_rearms(self):
        context = await self._run("")
        self.assertEqual(context.user_data.get("awaiting"), "ai_preset_new_name")


class TestTextRouterPrefixDispatch(unittest.IsolatedAsyncioTestCase):
    """bot.py text_router must dispatch ai_preset_* and ai_custom_test_* awaiting values."""

    def _import_text_router(self):
        import importlib, bot as bot_module
        importlib.reload(bot_module)
        return bot_module.text_router

    async def test_router_dispatches_ai_preset_new_name(self):
        """Check that text_router's condition matches ai_preset_new_name."""
        from bot import text_router
        update = _make_update(user_id=1, text="my_preset")
        context = _make_context()
        context.user_data["awaiting"] = "ai_preset_new_name"
        with patch("handlers.admin._handle_ai_preset_new_name", new=AsyncMock()) as mock_fn:
            with patch("handlers.admin.db") as mock_db:
                mock_db.get_preset.return_value = None
                await text_router(update, context)
            mock_fn.assert_called_once()

    async def test_router_dispatches_ai_preset_edit(self):
        from bot import text_router
        update = _make_update(user_id=1, text="gpt-4")
        context = _make_context()
        context.user_data["awaiting"] = "ai_preset_edit:test:model"
        with patch("handlers.admin._handle_ai_preset_field_input", new=AsyncMock()) as mock_fn:
            with patch("handlers.admin.db") as mock_db:
                mock_db.get_preset.return_value = {"name": "test"}
                await text_router(update, context)
            mock_fn.assert_called_once()

    async def test_router_dispatches_ai_custom_test_prompt(self):
        from bot import text_router
        update = _make_update(user_id=1, text="my prompt")
        context = _make_context()
        context.user_data["awaiting"] = "ai_custom_test_prompt"
        with patch("handlers.admin._custom_test_step_lang", new=AsyncMock()) as mock_fn:
            with patch("handlers.admin.db") as mock_db:
                await text_router(update, context)
            mock_fn.assert_called_once()

    async def test_router_rejects_nonowner_admin_flows(self):
        """Non-owner with admin_ awaiting must be rejected."""
        from bot import text_router
        update = _make_update(user_id=999, text="some value")
        context = _make_context()
        context.user_data["awaiting"] = "admin_set_plan"
        with patch("handlers.admin._handle_admin_text_input", new=AsyncMock()) as mock_fn:
            with patch("handlers.admin.is_owner", return_value=False):
                await text_router(update, context)
            mock_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
