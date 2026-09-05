import unittest
from unittest.mock import AsyncMock
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
        res = await _execute_telegram_action_with_retry(action)
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
            await _execute_telegram_action_with_retry(action)
        self.assertEqual(action.call_count, 3)
