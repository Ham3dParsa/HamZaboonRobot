import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest, NetworkError, TimedOut

from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback


class CallbackNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_intents_map_to_central_presentation_policy(self):
        cases = (
            (CallbackNoticeIntent.SUCCESS, False),
            (CallbackNoticeIntent.INFO, False),
            (CallbackNoticeIntent.IMPORTANT_ERROR, True),
        )

        for intent, show_alert in cases:
            with self.subTest(intent=intent.value):
                query = AsyncMock()

                await notify_callback(query, "notice", intent=intent)

                query.answer.assert_awaited_once_with("notice", show_alert=show_alert)

    async def test_empty_notice_acknowledges_without_visible_text(self):
        query = AsyncMock()

        await notify_callback(query)

        query.answer.assert_awaited_once_with()

    async def test_stale_callback_query_errors_are_ignored(self):
        for message in (
            "Query is too old and response timeout expired",
            "Query ID is invalid",
        ):
            with self.subTest(message=message):
                query = AsyncMock()
                query.answer.side_effect = BadRequest(message)

                await notify_callback(query, "notice")

    async def test_network_failures_are_ignored(self):
        for error in (TimedOut("timeout"), NetworkError("network")):
            with self.subTest(error=type(error).__name__):
                query = AsyncMock()
                query.answer.side_effect = error

                await notify_callback(query, "notice")

    async def test_unexpected_bad_request_propagates(self):
        query = AsyncMock()
        query.answer.side_effect = BadRequest("message is not modified")

        with self.assertRaises(BadRequest):
            await notify_callback(query, "notice")

    async def test_unexpected_telegram_error_propagates(self):
        query = AsyncMock()
        query.answer.side_effect = RuntimeError("unexpected")

        with self.assertRaisesRegex(RuntimeError, "unexpected"):
            await notify_callback(query, "notice")

    async def test_awaiting_flow_does_not_swallow_unexpected_notification_error(self):
        from services.utils import helpers

        update = MagicMock()
        update.effective_user.id = 1
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"awaiting": "anything"}

        with patch(
            "services.utils.helpers.notify_callback", new_callable=AsyncMock
        ) as notify:
            notify.side_effect = BadRequest("message is not modified")
            with self.assertRaises(BadRequest):
                await helpers._exit_awaiting_flow(update, context, via_callback=True)

        notify.assert_awaited_once_with(
            update.callback_query,
            "لغو شد.",
            intent=helpers.CallbackNoticeIntent.INFO,
        )

    async def test_study_inactive_does_not_swallow_unexpected_notification_error(self):
        from handlers.study_handler import handle_study_inactive

        update = MagicMock()
        context = MagicMock()

        with patch(
            "handlers.study_handler.notify_callback",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected"),
        ):
            with self.assertRaisesRegex(RuntimeError, "unexpected"):
                await handle_study_inactive(update, context)


if __name__ == "__main__":
    unittest.main()
