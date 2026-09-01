"""Regression for BTN_SETTINGS via text_router with no callback_query (fix/settings-menu-callback-crash)."""

import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import bot
from config.keyboards import BTN_SETTINGS
from services.send_pretty import RawFormat


class SettingsMenuViaTextRouterTests(unittest.IsolatedAsyncioTestCase):
    def _text_update(self, text: str, user_id: int = 1):
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.callback_query = None
        update.message.text = text
        update.message.reply_text = AsyncMock()
        return update

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = AsyncMock()
        return ctx

    async def test_btn_settings_via_text_router_no_callback_does_not_crash(self):
        update = self._text_update(BTN_SETTINGS)
        ctx = self._context()
        ctx.user_data["awaiting"] = None

        with (
            patch("bot._maintenance_blocked", new=AsyncMock(return_value=False)),
            patch.object(bot, "_telegram_offline", False),
            patch("bot.db.reset_user_blocked"),
            patch("handlers.user.db.get_user", return_value={"onboarded": True, "target_lang": "en", "goal": "general", "level": "beginner"}),
            patch("handlers.user.say", new_callable=AsyncMock) as mock_say,
            patch("handlers.user.notify_callback", new_callable=AsyncMock) as notify,
        ):
            await bot.text_router(update, ctx)

        mock_say.assert_awaited_once_with(
            update, ctx, f"{BTN_SETTINGS}:\nاز دکمه‌های زیر یکی را انتخاب کن.", keyboard=ANY, raw=RawFormat.PLAIN
        )
        notify.assert_not_awaited()

    async def test_btn_settings_not_onboarded_via_text_router_no_callback(self):
        update = self._text_update(BTN_SETTINGS)
        ctx = self._context()
        ctx.user_data["awaiting"] = None

        with (
            patch("bot._maintenance_blocked", new=AsyncMock(return_value=False)),
            patch.object(bot, "_telegram_offline", False),
            patch("bot.db.reset_user_blocked"),
            patch("handlers.user.db.get_user", return_value=None),
            patch("handlers.user._send_with_retry", new_callable=AsyncMock) as mock_send,
            patch("handlers.user.notify_callback", new_callable=AsyncMock) as notify,
        ):
            await bot.text_router(update, ctx)

        mock_send.assert_awaited_once()
        notify.assert_not_awaited()
