import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.error import NetworkError

import bot


class LoggingTests(unittest.IsolatedAsyncioTestCase):
    def test_polling_and_transport_loggers_suppress_info(self):
        for logger_name in ("apscheduler", "httpcore", "httpx", "telegram"):
            self.assertGreaterEqual(logging.getLogger(logger_name).level, logging.WARNING)

    async def test_connection_health_logs_success(self):
        context = SimpleNamespace(bot=SimpleNamespace(get_me=AsyncMock()))

        with self.assertLogs("hamzaban", level=logging.INFO) as captured:
            await bot.connection_health_job(context)

        context.bot.get_me.assert_awaited_once()
        self.assertIn("Telegram connection healthy", captured.output[0])

    async def test_connection_health_logs_network_failure_without_traceback(self):
        context = SimpleNamespace(
            bot=SimpleNamespace(get_me=AsyncMock(side_effect=NetworkError("offline")))
        )

        with self.assertLogs("hamzaban", level=logging.WARNING) as captured:
            await bot.connection_health_job(context)

        self.assertIn("Telegram connection check failed", captured.output[0])
        self.assertNotIn("Traceback", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
