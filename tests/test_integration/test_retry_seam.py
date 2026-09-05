import unittest
from unittest.mock import AsyncMock, patch
from telegram.error import RetryAfter, TimedOut, BadRequest
from services.utils.helpers import _execute_telegram_action_with_retry


class TestRetrySeam(unittest.IsolatedAsyncioTestCase):
    async def test_retry_seam_success_first_attempt(self):
        action = AsyncMock(return_value="ok")
        res = await _execute_telegram_action_with_retry(action)
        self.assertEqual(res, "ok")
        self.assertEqual(action.call_count, 1)

    async def test_retry_seam_recovers_from_retry_after(self):
        action = AsyncMock(side_effect=[RetryAfter(0.01), "recovered"])
        res = await _execute_telegram_action_with_retry(action)
        self.assertEqual(res, "recovered")
        self.assertEqual(action.call_count, 2)

    async def test_retry_seam_recovers_from_network_timeout(self):
        action = AsyncMock(side_effect=[TimedOut("timeout"), "success_after_timeout"])
        res = await _execute_telegram_action_with_retry(action, is_idempotent=True)
        self.assertEqual(res, "success_after_timeout")
        self.assertEqual(action.call_count, 2)

    async def test_retry_seam_fails_fast_on_bad_request(self):
        action = AsyncMock(side_effect=BadRequest("Message not modified"))
        with self.assertRaises(BadRequest):
            await _execute_telegram_action_with_retry(action)
        self.assertEqual(action.call_count, 1)

    async def test_retry_seam_exceeds_max_attempts(self):
        action = AsyncMock(side_effect=[TimedOut("t"), TimedOut("t"), TimedOut("t")])
        with self.assertRaises(TimedOut):
            await _execute_telegram_action_with_retry(action, is_idempotent=True)
        self.assertEqual(action.call_count, 3)

    async def test_send_path_no_retry_on_timeout(self):
        action = AsyncMock(side_effect=TimedOut("timeout"))
        with patch(
            "services.utils.helpers.asyncio.sleep", new=AsyncMock()
        ) as mock_sleep:
            with self.assertRaises(TimedOut):
                await _execute_telegram_action_with_retry(action)
        self.assertEqual(action.call_count, 1)
        mock_sleep.assert_not_called()

    async def test_retry_after_clamped(self):
        action = AsyncMock(side_effect=[RetryAfter(35), "recovered"])
        with patch(
            "services.utils.helpers.asyncio.sleep", new=AsyncMock()
        ) as mock_sleep:
            res = await _execute_telegram_action_with_retry(action)
        self.assertEqual(res, "recovered")
        self.assertEqual(action.call_count, 2)
        mock_sleep.assert_called_once()
        self.assertEqual(mock_sleep.call_args[0][0], 30)

    async def test_slot_missing_fail_closed(self):
        action = AsyncMock(return_value="ok")
        with patch("services.send_pretty._telegram_slots", None):
            with self.assertRaisesRegex(RuntimeError, "telegram slot unavailable"):
                await _execute_telegram_action_with_retry(action)
        action.assert_not_called()

    async def test_reset_flag_gating(self):
        action = AsyncMock(return_value="ok")
        with patch("services.utils.helpers._reset_telegram_cb") as mock_reset:
            res = await _execute_telegram_action_with_retry(
                action, is_idempotent=True, reset_telegram_cb=False
            )
        self.assertEqual(res, "ok")
        mock_reset.assert_not_called()
        action2 = AsyncMock(return_value="ok")
        with patch("services.utils.helpers._reset_telegram_cb") as mock_reset2:
            res2 = await _execute_telegram_action_with_retry(action2, is_idempotent=True)
        self.assertEqual(res2, "ok")
        mock_reset2.assert_called_once()
