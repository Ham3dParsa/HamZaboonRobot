"""Unit tests for the deep outbound-message module (R3).

Covers the span-tree content model: ``render`` for MDV2/HTML/PLAIN backends,
nesting, escaping correctness (special chars, code, links, spoilers, quotes),
the ``raw=`` escape hatch (declared format only), and the delivery verbs
(``send``/``say``) routing through the retry/slot seam.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.send_pretty import (
    Backend,
    Message,
    RawFormat,
    bold,
    code,
    italic,
    link,
    plain,
    quote,
    spoiler,
    nl,
    send,
    say,
)


class TestSpanRenderMDV2(unittest.TestCase):
    def test_plain_escapes_special_chars(self):
        self.assertEqual(_one_line(plain("a.b!")), "a\\.b\\!")

    def test_bold_marks_text(self):
        self.assertEqual(_one_line(bold("واژه")), "*واژه*")

    def test_bold_with_nested_code_and_spoiler(self):
        result = _one_line(bold("واژه", code("/start"), spoiler("پنهان")))
        self.assertEqual(result, "*واژه`/start`||پنهان||*")

    def test_italic_and_quote(self):
        result = _one_line(quote(bold("نکته"), " ", italic("مهم")))
        self.assertEqual(result, "> *نکته* _مهم_")

    def test_link_escapes_url_and_children(self):
        result = _one_line(link("https://x.test/a(b)", bold("گل")))
        self.assertEqual(result, "[*گل*](https://x\\.test/a\\(b\\))")

    def test_spoiler_children_escaped(self):
        result = _one_line(spoiler("پنهان . پنهان"))
        self.assertEqual(result, "||پنهان \\. پنهان||")

    def test_newline_span(self):
        msg = Message()
        msg.add_line(plain("a"), nl(), plain("b"))
        self.assertEqual(msg.render(), "a\nb")


class TestSpanRenderHTML(unittest.TestCase):
    def test_plain_escapes_html(self):
        self.assertEqual(_one_line(plain("<b>&"), Backend.HTML), "&lt;b&gt;&amp;")

    def test_bold_and_italic(self):
        self.assertEqual(
            _one_line(bold("س"), Backend.HTML), "<b>س</b>"
        )
        self.assertEqual(
            _one_line(italic("م"), Backend.HTML), "<i>م</i>"
        )

    def test_code_and_spoiler_and_link(self):
        self.assertEqual(
            _one_line(code("<x>"), Backend.HTML), "<code>&lt;x&gt;</code>"
        )
        self.assertEqual(
            _one_line(spoiler("پ"), Backend.HTML),
            '<span class="tg-spoiler">پ</span>',
        )
        self.assertEqual(
            _one_line(link("https://x.test/?a=b&c", "گل"), Backend.HTML),
            '<a href="https://x.test/?a=b&amp;c">گل</a>',
        )


class TestSpanRenderPlain(unittest.TestCase):
    def test_strips_all_markup(self):
        msg = Message()
        msg.add_line(bold("b"), " ", code("/x"), " ", spoiler("s"))
        self.assertEqual(msg.render(Backend.PLAIN), "b /x s")


class TestMessageConstruction(unittest.TestCase):
    def test_add_line_coerces_strings(self):
        msg = Message()
        msg.add_line("سلام", bold("هم‌زبان"))
        self.assertEqual(msg.render(), "سلام*هم‌زبان*")

    def test_empty_message_renders_empty(self):
        self.assertEqual(Message().render(), "")

    def test_bad_backend_rejected(self):
        with self.assertRaises(NotImplementedError):
            Message().render(Backend.RICH)


class TestRawEscapeHatch(unittest.TestCase):
    def test_raw_requires_declared_format(self):
        # Passing a bare string content WITHOUT raw= must raise (never guess).
        from services.send_pretty import _resolve_content

        with self.assertRaises(TypeError):
            _resolve_content("plain string", None)
        # raw=HTML declares the format and yields the HTML parse mode.
        text, pm = _resolve_raw("<b>hi</b>", RawFormat.HTML)
        self.assertEqual(text, "<b>hi</b>")
        self.assertIsNotNone(pm)

    def test_raw_plain_has_no_parse_mode(self):
        text, pm = _resolve_raw("plain text", RawFormat.PLAIN)
        self.assertEqual(pm, None)


class TestDeliveryVerbs(unittest.IsolatedAsyncioTestCase):
    async def test_send_routes_through_retry_with_parse_mode(self):
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(return_value="msg")
        msg = Message()
        msg.add_line(bold("س"))
        with patch(
            "services.send_pretty._send_with_retry", new=AsyncMock(return_value="msg")
        ) as retry:
            result = await send(123, msg, bot=bot_mock)
        self.assertEqual(result, "msg")
        retry.assert_called_once()
        args, kwargs = retry.call_args
        self.assertEqual(args[1], 123)
        self.assertEqual(args[2], "*س*")
        self.assertEqual(kwargs["parse_mode"], "MarkdownV2")

    async def test_send_raw_declares_html(self):
        bot_mock = MagicMock()
        bot_mock.send_message = AsyncMock(return_value="msg")
        with patch(
            "services.send_pretty._send_with_retry", new=AsyncMock(return_value="msg")
        ) as retry:
            await send(123, "<b>hi</b>", bot=bot_mock, raw=RawFormat.HTML)
        _, kwargs = retry.call_args
        self.assertEqual(kwargs["parse_mode"], "HTML")

    async def test_say_edits_when_callback_present(self):
        update = MagicMock()
        query = MagicMock()
        query.edit_message_text = AsyncMock(return_value="edited")
        update.callback_query = query
        ctx = MagicMock()
        msg = Message()
        msg.add_line(plain("hello"))
        with patch(
            "services.send_pretty._edit_with_retry", new=AsyncMock(return_value="edited")
        ) as edit:
            result = await say(update, ctx, msg)
        self.assertEqual(result, "edited")
        edit.assert_called_once()
        args, kwargs = edit.call_args
        self.assertEqual(args[0], query)
        self.assertEqual(args[1], "hello")

    async def test_say_sends_when_no_callback(self):
        update = MagicMock()
        update.callback_query = None
        update.effective_chat.id = 123
        ctx = MagicMock()
        msg = Message()
        msg.add_line(plain("hello"))
        with patch(
            "services.send_pretty._send_with_retry", new=AsyncMock(return_value="sent")
        ) as send_retry:
            result = await say(update, ctx, msg)
        self.assertEqual(result, "sent")
        _, kwargs = send_retry.call_args
        self.assertEqual(kwargs["parse_mode"], "MarkdownV2")


def _one_line(span, backend=Backend.MDV2) -> str:
    msg = Message()
    msg.add_line(span)
    return msg.render(backend)


def _resolve_raw(text, fmt):
    from services.send_pretty import _resolve_content

    return _resolve_content(text, fmt)


if __name__ == "__main__":
    unittest.main()