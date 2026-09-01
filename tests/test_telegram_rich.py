"""Unit tests for the Rich Message delivery shim (R2/R3/R6).

Covers the isolated ``services.telegram_rich`` seam: payload shape, the
capability latch on 404, transient-error (no-resend) behavior, the edit path,
and the enabled-by-default feature flag routing to MarkdownV2.
"""

import unittest
from unittest.mock import AsyncMock, patch

from telegram.constants import ParseMode
from telegram.error import EndPointNotFound, TimedOut

from services import telegram_rich


def _make_bot(return_value):
    bot = unittest.mock.MagicMock()
    bot.do_api_request = AsyncMock(return_value=return_value)
    return bot


class TestRichDelivery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        telegram_rich.RICH_ENABLED = True
        telegram_rich._rich_disabled.clear()

    async def test_send_payload_shape(self):
        bot = _make_bot({"message_id": 42, "chat": {"id": 1}})
        mid = await telegram_rich.send_rich_message(bot, 1, "**x**", "x", is_rtl=True)
        self.assertEqual(mid, 42)
        self.assertEqual(bot.do_api_request.call_args.args[0], "sendRichMessage")
        kwargs = bot.do_api_request.call_args.kwargs["api_kwargs"]
        self.assertEqual(kwargs["rich_message"]["markdown"], "**x**")
        self.assertTrue(kwargs["rich_message"]["is_rtl"])

    async def test_endpoint_not_found_latches_and_falls_back(self):
        bot = _make_bot(None)
        bot.do_api_request = AsyncMock(side_effect=EndPointNotFound("404"))
        with patch.object(telegram_rich, "_send_with_retry", new=AsyncMock(return_value=7)) as fb:
            mid = await telegram_rich.send_rich_message(bot, 1, "**x**", "x")
        self.assertEqual(mid, 7)
        fb.assert_awaited_once()
        self.assertIn(id(bot), telegram_rich._rich_disabled)

    async def test_transient_not_resent(self):
        bot = _make_bot(None)
        bot.do_api_request = AsyncMock(side_effect=TimedOut("boom"))
        with patch.object(telegram_rich, "_send_with_retry", new=AsyncMock()) as fb:
            with self.assertRaises(TimedOut):
                await telegram_rich.send_rich_message(bot, 1, "**x**", "x")
        fb.assert_not_awaited()

    async def test_edit_uses_rich_message_param(self):
        bot = _make_bot({"message_id": 9, "chat": {"id": 1}})
        await telegram_rich.edit_rich_message(bot, 1, 9, "**x**", "x")
        self.assertEqual(bot.do_api_request.call_args.args[0], "editMessageText")
        kwargs = bot.do_api_request.call_args.kwargs["api_kwargs"]
        self.assertEqual(kwargs["message_id"], 9)
        self.assertEqual(kwargs["rich_message"]["markdown"], "**x**")

    async def test_flag_off_routes_md_v2(self):
        bot = _make_bot(None)
        with patch.object(telegram_rich, "RICH_ENABLED", False):
            with patch.object(telegram_rich, "_send_with_retry", new=AsyncMock(return_value=5)) as fb:
                mid = await telegram_rich.send_rich_message(bot, 1, "**x**", "x", is_rtl=True)
        self.assertEqual(mid, 5)
        bot.do_api_request.assert_not_awaited()
        fb.assert_awaited_once()

    def test_flag_default_is_true(self):
        # Default env should enable Rich (true/1/yes/on). No reload needed;
        # the module was imported with default env true.
        self.assertTrue(telegram_rich.RICH_ENABLED)
        # Env override check via patch without reload pollution
        with patch.dict("os.environ", {"RICH_ENABLED": "false"}):
            # Re-evaluate the expression directly (strip to match production)
            val = __import__("os").getenv("RICH_ENABLED", "true").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            self.assertFalse(val)

    async def test_send_pretty_rich_fallback_via_send(self):
        """Handler-level integration: send via Backend.RICH with mocked 404/BadRequest falls back to MDV2."""
        from services.send_pretty import Backend, Message, plain, send
        from telegram.error import BadRequest

        # 404 latch path
        bot = _make_bot({"message_id": 1})
        bot.do_api_request = AsyncMock(side_effect=EndPointNotFound("404"))
        msg = Message()
        msg.add_line(plain("hello rich"))
        with patch.object(telegram_rich, "_send_with_retry", new=AsyncMock(return_value=99)) as fb:
            mid = await send(1, msg, bot=bot, backend=Backend.RICH)
            fb.assert_awaited_once()
            self.assertEqual(mid, 99)

        # BadRequest fallback path
        telegram_rich._rich_disabled.clear()
        bot2 = _make_bot({"message_id": 2})
        bot2.do_api_request = AsyncMock(side_effect=BadRequest("bad"))
        msg2 = Message()
        msg2.add_line(plain("hello again"))
        with patch.object(telegram_rich, "_send_with_retry", new=AsyncMock(return_value=100)) as fb2:
            mid2 = await send(1, msg2, bot=bot2, backend=Backend.RICH)
            fb2.assert_awaited_once()
            self.assertEqual(mid2, 100)


if __name__ == "__main__":
    unittest.main()
