"""Integration coverage for callback-notification routing through admin handlers."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.admin import _handle_admin_callback
from services.utils.callback_notifications import CallbackNoticeIntent


class CallbackNotificationFlowTests(unittest.IsolatedAsyncioTestCase):
    def _callback_update(self, user_id: int = 1):
        query = MagicMock()
        query.answer = AsyncMock()
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = user_id
        update.callback_query = query
        return update, query

    def _context(self):
        context = MagicMock()
        context.user_data = {}
        context.bot = AsyncMock()
        return context

    async def test_non_owner_callback_uses_important_error_intent(self):
        update, query = self._callback_update(user_id=1234)
        context = self._context()

        with (
            patch("handlers.admin.is_owner", return_value=False),
            patch("handlers.admin.notify_callback", new_callable=AsyncMock) as notify,
        ):
            await _handle_admin_callback(update, context, "stats")

        notify.assert_awaited_once_with(
            query,
            "فقط مالک ربات دسترسی داره.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )

    async def test_navigation_callback_uses_info_intent(self):
        update, query = self._callback_update()
        context = self._context()

        with (
            patch("handlers.admin.is_owner", return_value=True),
            patch("handlers.admin._edit_or_send", new_callable=AsyncMock),
            patch("handlers.admin.notify_callback", new_callable=AsyncMock) as notify,
        ):
            await _handle_admin_callback(update, context, "back")

        notify.assert_awaited_once_with(
            query,
            "بازگشت",
            intent=CallbackNoticeIntent.INFO,
        )
