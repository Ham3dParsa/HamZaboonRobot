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
        from handlers.admin_ai import _handle_ai_preset_field_input
        update = _make_update(text=bad_input)
        context = _make_context()
        with patch("handlers.admin_ai.db") as mock_db:
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
        from handlers.admin_ai import _handle_ai_preset_new_name
        update = _make_update(text=name)
        context = _make_context()
        with patch("handlers.admin_ai.db") as mock_db:
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

    async def test_underscore_with_special_char_rearms(self):
        """Regression for the precedence bug: 'my_preset!' must be rejected
        even though it contains an underscore (which previously defeated the
        alnum check via `not name.isalnum() and "_" not in name`)."""
        context = await self._run("my_preset!")
        self.assertEqual(context.user_data.get("awaiting"), "ai_preset_new_name")

    async def test_overlong_name_rearms(self):
        """A name longer than MAX_PRESET_NAME_LEN must be rejected."""
        context = await self._run("n" * 70)
        self.assertEqual(context.user_data.get("awaiting"), "ai_preset_new_name")


class TestTextRouterPrefixDispatch(unittest.IsolatedAsyncioTestCase):
    """bot.py text_router must dispatch admin awaiting values through the central
    flows registry (R2) — the single source of truth for awaiting-key routing."""

    def _import_text_router(self):
        import importlib, bot as bot_module
        importlib.reload(bot_module)
        return bot_module.text_router

    async def _route(self, awaiting: str, text: str = "value"):
        from handlers.admin import _register_admin_flows  # triggers registration
        _register_admin_flows()
        from handlers.flows import text_router
        update = _make_update(user_id=1, text=text)
        context = _make_context()
        context.user_data["awaiting"] = awaiting
        await text_router(update, context, awaiting, text)
        return update, context

    async def test_ai_preset_new_name_registered(self):
        with patch("handlers.admin._handle_ai_preset_new_name", new=AsyncMock()) as mock_fn:
            await self._route("ai_preset_new_name")
            mock_fn.assert_awaited_once()

    async def test_ai_preset_edit_registered(self):
        with patch("handlers.admin._handle_ai_preset_field_input", new=AsyncMock()) as mock_fn:
            await self._route("ai_preset_edit:test:model", "gpt-4")
            mock_fn.assert_awaited_once()

    async def test_ai_custom_test_prompt_registered(self):
        with patch("handlers.admin._custom_test_step_lang", new=AsyncMock()) as mock_fn:
            await self._route("ai_custom_test_prompt", "my prompt")
            mock_fn.assert_awaited_once()

    async def test_llm_cost_user_registered(self):
        with patch("handlers.admin._handle_cost_text_input", new=AsyncMock()) as mock_fn:
            await self._route("llm_cost_user")
            mock_fn.assert_awaited_once()

    async def test_ai_fallback_rank_registered(self):
        """Regression guard for the Finding #6 routing gap: ai_fallback_rank:
        must route to _handle_ai_text_input."""
        from handlers.admin import _register_admin_flows
        _register_admin_flows()
        from handlers.flows import text_router
        update = _make_update(user_id=1, text="2")
        context = _make_context()
        context.user_data["awaiting"] = "ai_fallback_rank:gpt"
        with patch("handlers.admin._handle_ai_text_input", new=AsyncMock()) as mock_fn:
            with patch("handlers.admin.db") as mock_db:
                mock_db.get_preset.return_value = {"name": "gpt", "is_emergency": 0}
                await text_router(update, context, "ai_fallback_rank:gpt", "2")
            mock_fn.assert_awaited_once()

    async def test_admin_set_plan_registered(self):
        with patch("handlers.admin._handle_plans_text_input", new=AsyncMock()) as mock_fn:
            await self._route("admin_set_plan")
            mock_fn.assert_awaited_once()

    async def test_admin_plan_full_edit_registered(self):
        with patch("handlers.admin._handle_plan_wizard_input", new=AsyncMock()) as mock_fn:
            await self._route("admin_plan_full_edit:silver:0", "نقره‌ای")
            mock_fn.assert_awaited_once()

    async def test_admin_ai_preset_new_name_registered(self):
        with patch("handlers.admin._handle_ai_preset_new_name", new=AsyncMock()) as mock_fn:
            await self._route("admin_ai_preset_new_name")
            mock_fn.assert_awaited_once()

    async def test_router_forwards_admin_awaiting_to_flows(self):
        """bot.text_router must forward an admin awaiting value to flows.text_router."""
        from bot import text_router
        update = _make_update(user_id=1, text="my_preset")
        context = _make_context()
        context.user_data["awaiting"] = "ai_preset_new_name"
        with patch("bot.db.reset_user_blocked"):
            with patch("bot.is_owner", return_value=True):
                with patch("bot.flows_text_router", new=AsyncMock()) as mock_fn:
                    with patch("handlers.admin.db") as mock_db:
                        mock_db.get_preset.return_value = None
                        await text_router(update, context)
                    mock_fn.assert_awaited_once()

    async def test_router_rejects_nonowner_admin_flows(self):
        """Non-owner with admin_ awaiting must be rejected."""
        from bot import text_router
        update = _make_update(user_id=999, text="some value")
        context = _make_context()
        context.user_data["awaiting"] = "admin_set_plan"
        with patch("bot.db.reset_user_blocked"):
            with patch("bot.flows_text_router", new=AsyncMock()) as mock_fn:
                with patch("handlers.admin.is_owner", return_value=False):
                    await text_router(update, context)
                mock_fn.assert_not_awaited()

    async def test_callback_router_routes_flow_back_to_handle_flow_back(self):
        """callback_router(data='flow:back') must delegate to handle_flow_back."""
        from bot import callback_router
        update = _make_update(user_id=1, text="")
        update.callback_query.data = "flow:back"
        context = _make_context()
        context.user_data["awaiting"] = "ai_preset_edit:gpt:model"
        with patch("bot.db.reset_user_blocked"):
            with patch("bot.handle_flow_back", new=AsyncMock()) as mock_fn:
                await callback_router(update, context)
            mock_fn.assert_called_once()


class TestHandleFlowBack(unittest.IsolatedAsyncioTestCase):
    """handle_flow_back() back-navigation branches (Finding #6 move)."""

    async def _run(self, awaiting: str):
        from handlers.admin import handle_flow_back
        update = _make_update()
        context = _make_context()
        context.user_data["awaiting"] = awaiting
        with patch("handlers.admin._edit_ai_preset", new=AsyncMock()) as m_edit:
            with patch("handlers.admin._exit_awaiting_flow", new=AsyncMock()) as m_exit:
                await handle_flow_back(update, context)
        return m_edit, m_exit, update, context

    async def test_ai_preset_edit_branch(self):
        m_edit, m_exit, update, context = await self._run("ai_preset_edit:gpt:model")
        m_edit.assert_called_once_with(update, context, "gpt")
        m_exit.assert_not_called()

    async def test_ai_preset_full_edit_branch(self):
        m_edit, m_exit, update, context = await self._run("ai_preset_full_edit:gpt:0")
        m_edit.assert_called_once_with(update, context, "gpt")
        m_exit.assert_not_called()

    async def test_admin_plan_full_edit_branch(self):
        m_edit, m_exit, update, context = await self._run("admin_plan_full_edit:silver:0")
        m_exit.assert_called_once()
        m_edit.assert_not_called()

    async def test_generic_admin_awaiting_branch(self):
        m_edit, m_exit, update, context = await self._run("admin_set_plan")
        m_exit.assert_called_once()
        m_edit.assert_not_called()

    async def test_empty_awaiting_branch(self):
        m_edit, m_exit, update, context = await self._run("")
        m_exit.assert_not_called()
        m_edit.assert_not_called()
        update.callback_query.answer.assert_called()


class TestAiCallWrappedInToThread(unittest.IsolatedAsyncioTestCase):
    """Finding #1: sync AI calls in admin handlers must run via asyncio.to_thread."""

    async def test_ai_connection_runs_via_to_thread(self):
        from handlers.admin_ai import _test_ai_connection
        update = _make_update()
        context = _make_context()
        with patch("handlers.admin_ai.db.get_active_preset") as mock_preset:
            mock_preset.return_value = {"base_url": "", "model": "test", "timeout_seconds": 30.0}
            with patch("handlers.admin_ai.ai.test_connection") as mock_test:
                with patch("handlers.admin_ai.asyncio.to_thread", new=AsyncMock()) as mock_to_thread:
                    mock_to_thread.return_value = {"success": True, "latency_ms": 42, "model": "test", "usage": {}}
                    await _test_ai_connection(update, context)
        mock_to_thread.assert_called_once()
        args, _ = mock_to_thread.call_args
        self.assertIs(args[0], mock_test)

    async def _run_custom_test_with_mocks(self, target: str):
        from handlers.admin_ai import _run_custom_test
        update = _make_update()
        context = _make_context()
        context.user_data["custom_test_state"] = {"prompt": "test", "lang": "en", "goal": "general", "level": "beginner"}
        with patch("handlers.admin_ai.prompts.daily_batch_system_prompt", return_value="system prompt"):
            with patch("handlers.admin_ai.db.get_active_preset") as mock_active:
                mock_active.return_value = {"name": "current"}
                with patch("handlers.admin_ai.db.get_preset") as mock_get_preset:
                    mock_get_preset.return_value = {"name": "candidate"}
                    with patch("handlers.admin_ai.asyncio.to_thread", new=AsyncMock()) as mock_to_thread:
                        mock_to_thread.return_value = {"word": "hello"}
                        await _run_custom_test(update, context, target)
        return mock_to_thread

    async def test_custom_test_current_runs_via_to_thread(self):
        mock_to_thread = await self._run_custom_test_with_mocks("current")
        mock_to_thread.assert_called_once()
        args, _ = mock_to_thread.call_args
        from services.ai import ai
        self.assertIs(args[0], ai.custom_test_card)

    async def test_custom_test_ab_runs_via_to_thread_twice(self):
        mock_to_thread = await self._run_custom_test_with_mocks("ab")
        self.assertEqual(mock_to_thread.call_count, 2)


class TestIsAdminAwaiting(unittest.IsolatedAsyncioTestCase):
    """is_admin_awaiting() is the single source of truth for admin awaiting keys
    (Finding #6). It must recognize every admin awaiting key and reject user keys."""

    def test_known_admin_keys_return_true(self):
        from handlers.admin import is_admin_awaiting
        for key in (
            "admin_set_plan", "admin_broadcast", "admin_restore",
            "admin_plan_full_edit:silver:0", "admin_ai_preset_new_name",
            "admin_group_batch_key:abc", "admin_group_set_label:abc",
            "admin_group_manager_rename:abc",
            "ai_preset_new_name", "ai_preset_edit:gpt:model",
            "ai_preset_full_edit:gpt:0", "ai_custom_test_prompt",
            "ai_fallback_rank:gpt", "llm_cost_user", "llm_cost_model",
            "llm_price_input", "llm_price_output", "llm_price_rate",
        ):
            self.assertTrue(is_admin_awaiting(key), key)

    def test_non_admin_keys_return_false(self):
        from handlers.admin import is_admin_awaiting
        for key in ("ask_word", "", "flow:back", "stats", "llm:usage", "srs:fe", "user_settings"):
            self.assertFalse(is_admin_awaiting(key), key)

    def test_empty_and_none_return_false(self):
        from handlers.admin import is_admin_awaiting
        self.assertFalse(is_admin_awaiting(""))
        self.assertFalse(is_admin_awaiting(None))


class TestValidateWizardValueLengthCaps(unittest.TestCase):
    """_validate_wizard_value must enforce length caps on name and group_label."""

    def _validate(self, field: str, raw: str, preset_name: str = "existing") -> bool:
        from handlers.admin_ai import _validate_wizard_value
        return _validate_wizard_value(field, raw, preset_name) is not None

    @patch("handlers.admin_ai.db.get_preset", return_value=None)
    def test_name_over_60_rejected(self, _):
        self.assertFalse(self._validate("name", "n" * 61))

    @patch("handlers.admin_ai.db.get_preset", return_value=None)
    def test_name_under_60_accepted(self, _):
        self.assertTrue(self._validate("name", "valid_name"))

    @patch("handlers.admin_ai.db.get_preset", return_value=None)
    def test_name_60_accepted(self, _):
        self.assertTrue(self._validate("name", "n" * 60))

    def test_group_label_empty_rejected(self):
        self.assertFalse(self._validate("group_label", ""))

    def test_group_label_over_40_rejected(self):
        self.assertFalse(self._validate("group_label", "g" * 41))

    def test_group_label_valid_accepted(self):
        self.assertTrue(self._validate("group_label", "valid group"))

    def test_group_label_40_accepted(self):
        self.assertTrue(self._validate("group_label", "g" * 40))


class TestGroupLabelTextInputCaps(unittest.IsolatedAsyncioTestCase):
    """_handle_ai_text_input group-set-label and group-rename paths must enforce
    the group_label length cap / non-empty validation (D3)."""

    async def test_group_set_label_overlong_rearms(self):
        from handlers.admin_ai import _handle_ai_text_input
        update = _make_update(text="g" * 41)
        context = _make_context()
        context.user_data["awaiting"] = "admin_group_set_label:abc"
        await _handle_ai_text_input(update, context, "admin_group_set_label:abc", "g" * 41)
        # awaiting preserved for retry
        self.assertEqual(context.user_data.get("awaiting"), "admin_group_set_label:abc")

    async def test_group_set_label_empty_rearms(self):
        from handlers.admin_ai import _handle_ai_text_input
        update = _make_update(text="")
        context = _make_context()
        context.user_data["awaiting"] = "admin_group_set_label:abc"
        await _handle_ai_text_input(update, context, "admin_group_set_label:abc", "")
        self.assertEqual(context.user_data.get("awaiting"), "admin_group_set_label:abc")

    async def test_group_manager_rename_overlong_rearms(self):
        from handlers.admin_ai import _handle_ai_text_input
        update = _make_update(text="g" * 41)
        context = _make_context()
        context.user_data["awaiting"] = "admin_group_manager_rename:old"
        await _handle_ai_text_input(update, context, "admin_group_manager_rename:old", "g" * 41)
        self.assertEqual(context.user_data.get("awaiting"), "admin_group_manager_rename:old")


if __name__ == "__main__":
    unittest.main()
