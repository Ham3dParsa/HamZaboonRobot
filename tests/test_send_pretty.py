"""Unit tests for the deep outbound-message module (R3).

Covers the span-tree content model: ``render`` for MDV2/HTML/PLAIN backends,
nesting, escaping correctness (special chars, code, links, spoilers, quotes),
the ``raw=`` escape hatch (declared format only), and the delivery verbs
(``send``/``say``) routing through the retry/slot seam.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest
from config import custom_emoji
from services.send_pretty import (
    Backend,
    Message,
    RawFormat,
    CustomEmoji,
    Details,
    Heading,
    List,
    ListItem,
    Math,
    Raw,
    TaskListItem,
    Table,
    bold,
    code,
    emoji,
    italic,
    link,
    plain,
    quote,
    spoiler,
    underline,
    strike,
    mark,
    tg_spoiler,
    nl,
    send,
    say,
    edit,
    edit_markup,
)


class TestCustomEmoji(unittest.TestCase):
    def test_emoji_md_v2(self):
        msg = Message()
        msg.add_line(emoji("5378324170671202286", fallback="📖"))
        self.assertEqual(
            msg.render(Backend.MDV2), "![📖](tg://emoji?id=5378324170671202286)"
        )

    def test_emoji_html(self):
        msg = Message()
        msg.add_line(emoji("5378324170671202286", fallback="📖"))
        self.assertEqual(
            msg.render(Backend.HTML),
            '<tg-emoji emoji-id="5378324170671202286">📖</tg-emoji>',
        )

    def test_emoji_plain(self):
        msg = Message()
        msg.add_line(emoji("5378324170671202286", fallback="📖"))
        self.assertEqual(msg.render(Backend.PLAIN), "📖")

    def test_emoji_unknown_key_uses_default_fallback(self):
        msg = Message()
        msg.add_line(emoji("zzz_not_a_real_key"))
        self.assertEqual(
            msg.render(Backend.MDV2), "![❓](tg://emoji?id=zzz_not_a_real_key)"
        )

    def test_emoji_registry_resolves_configured(self):
        with patch.dict(
            custom_emoji.CUSTOM_EMOJI, {"book": ("999", "📚")}
        ):
            msg = Message()
            msg.add_line(emoji("book"))
            self.assertEqual(
                msg.render(Backend.MDV2), "![📚](tg://emoji?id=999)"
            )


class TestRichRender(unittest.TestCase):
    def test_render_rich_no_longer_raises(self):
        msg = Message()
        msg.add_line(plain("x"))
        self.assertEqual(msg.render(Backend.RICH), "x")

    def test_heading(self):
        msg = Message()
        msg.add_line(Heading(2, plain("واژه")))
        self.assertEqual(msg.render(Backend.RICH), "## واژه")

    def test_table(self):
        msg = Message()
        msg.add_line(
            Table(header=(plain("ف"), plain("ا")), rows=((plain("کتاب"), plain("book")),))
        )
        self.assertEqual(
            msg.render(Backend.RICH), "| ف | ا |\n| --- | --- |\n| کتاب | book |"
        )

    def test_unordered_list(self):
        msg = Message()
        msg.add_line(List(False, (ListItem(plain("a")), ListItem(plain("b")))))
        self.assertEqual(msg.render(Backend.RICH), "- a\n- b")

    def test_task_list(self):
        msg = Message()
        msg.add_line(
            List(
                False,
                (
                    TaskListItem(True, plain("done")),
                    TaskListItem(False, plain("todo")),
                ),
            )
        )
        self.assertEqual(msg.render(Backend.RICH), "- [x] done\n- [ ] todo")

    def test_details(self):
        msg = Message()
        msg.add_line(Details(plain("بیشتر"), plain("متن")))
        self.assertEqual(
            msg.render(Backend.RICH),
            "<details><summary>بیشتر</summary>متن</details>",
        )

    def test_details_open_attribute(self):
        msg = Message()
        msg.add_line(Details(plain("بیشتر"), plain("متن"), open=True))
        self.assertEqual(
            msg.render(Backend.RICH),
            "<details open><summary>بیشتر</summary>متن</details>",
        )

    def test_details_no_newline_before_close_tag(self):
        # Telegram Rich leaks a literal ``</details>`` if the closing tag is
        # preceded by a newline (@mira bug).  A trailing newline in the body
        # must be stripped so the close tag stays on the same line as content.
        msg = Message()
        msg.add_line(Details(plain("بیشتر"), plain("متن\n")))
        self.assertEqual(
            msg.render(Backend.RICH),
            "<details><summary>بیشتر</summary>متن</details>",
        )

    def test_raw_rich_span_verbatim(self):
        # A ``Raw`` span injects verbatim Rich markup (e.g. an HTML table inside
        # <details>) that the span tree cannot express.
        markup = "<details open><summary>s</summary><table><tr><td><b>x</b></td></tr></table></details>"
        msg = Message()
        msg.add_line(Raw(markup))
        self.assertEqual(msg.render(Backend.RICH), markup)
        self.assertEqual(msg.render(Backend.PLAIN), markup)

    def test_underline_rich_and_plain(self):
        msg = Message()
        msg.add_line(underline("متن"))
        self.assertEqual(msg.render(Backend.RICH), "__متن__")
        self.assertEqual(msg.render(Backend.PLAIN), "متن")

    def test_strikethrough_rich_and_plain(self):
        msg = Message()
        msg.add_line(strike("متن"))
        self.assertEqual(msg.render(Backend.RICH), "~~متن~~")
        self.assertEqual(msg.render(Backend.PLAIN), "متن")

    def test_marked_rich_and_plain(self):
        msg = Message()
        msg.add_line(mark("متن"))
        self.assertEqual(msg.render(Backend.RICH), "==متن==")
        self.assertEqual(msg.render(Backend.PLAIN), "متن")

    def test_tg_spoiler_rich_and_table_cell(self):
        msg = Message()
        msg.add_line(tg_spoiler("راز"))
        self.assertEqual(msg.render(Backend.RICH), "<tg-spoiler>راز</tg-spoiler>")
        # table-safe spoiler must render inside a Markdown table cell
        msg2 = Message()
        msg2.add_line(Table(header=None, rows=((tg_spoiler("راز"), plain("ترجمه")),)))
        self.assertIn("<tg-spoiler>راز</tg-spoiler>", msg2.render(Backend.RICH))

    def test_math_inline(self):
        msg = Message()
        msg.add_line(Math("x^2"))
        self.assertEqual(msg.render(Backend.RICH), "$x^2$")

    def test_math_block(self):
        msg = Message()
        msg.add_line(Math("E=mc^2", block=True))
        self.assertEqual(msg.render(Backend.RICH), "$$E=mc^2$$")

    def test_emoji_in_rich(self):
        msg = Message()
        msg.add_line(emoji("5378324170671202286", fallback="📖"))
        self.assertEqual(
            msg.render(Backend.RICH), "![](tg://emoji?id=5378324170671202286)"
        )

    def test_rich_nested(self):
        msg = Message()
        msg.add_line(Heading(1, bold("عنوان")))
        self.assertEqual(msg.render(Backend.RICH), "# **عنوان**")

    def test_rich_blocks_separated_by_blank_line(self):
        msg = Message()
        msg.add_line(plain("line one"))
        msg.add_line(plain("line two"))
        self.assertEqual(msg.render(Backend.RICH), "line one\n\nline two")

    def test_rich_examples_quote_then_spoiler_on_own_lines(self):
        msg = Message()
        msg.add_line(quote(plain("✦ "), plain("en")))
        msg.add_line(spoiler(plain("fa")))
        self.assertEqual(msg.render(Backend.RICH), "> ✦ en\n\n||fa||")

    def test_rich_quote_newline_breaks_within_same_quote(self):
        msg = Message()
        msg.add_line(quote(plain("✦ en"), nl(), spoiler(plain("fa"))))
        self.assertEqual(msg.render(Backend.RICH), "> ✦ en\n>\n> ||fa||")


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

    def test_newline_span_html_emits_literal_newline(self):
        msg = Message()
        msg.add_line(plain("a"), nl(), plain("b"))
        self.assertEqual(msg.render(Backend.HTML), "a\nb")


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
        # Backend.RICH is implemented (phase 02); assert it renders rather than
        # raising. Unknown backends still fall through to MDV2 via the else
        # branch, so rejection is no longer the contract here.
        msg = Message()
        msg.add_line(plain("x"))
        self.assertEqual(msg.render(Backend.RICH), "x")


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

    def test_raw_with_message_raises(self):
        """raw= is only for pre-formatted strings; passing a Message must fail
        loudly instead of emitting an object repr."""
        from services.send_pretty import _resolve_content

        msg = Message()
        msg.add_line("hello")
        with self.assertRaises(TypeError):
            _resolve_content(msg, RawFormat.HTML)


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
        msg = MagicMock()
        msg.reply_text = AsyncMock(return_value="sent")
        update.message = msg
        ctx = MagicMock()
        text = Message()
        text.add_line(plain("hello"))
        result = await say(update, ctx, text)
        self.assertEqual(result, "sent")
        args, kwargs = msg.reply_text.call_args
        self.assertEqual(args[0], "hello")
        self.assertEqual(kwargs["parse_mode"], "MarkdownV2")

    async def test_say_sends_when_mode_send_despite_callback(self):
        update = MagicMock()
        update.callback_query = MagicMock()
        update.message.reply_text = AsyncMock(return_value="sent")
        result = await say(update, MagicMock(), "hi", mode="send", raw=RawFormat.PLAIN)
        self.assertEqual(result, "sent")
        update.callback_query.edit_message_text.assert_not_called()

    async def test_say_sends_new_message_when_no_message_present(self):
        update = MagicMock()
        update.callback_query = None
        update.effective_chat.id = 123
        update.message = None
        ctx = MagicMock()
        text = Message()
        text.add_line(plain("hello"))
        with patch(
            "services.send_pretty._send_with_retry", new=AsyncMock(return_value="sent")
        ) as send_retry:
            result = await say(update, ctx, text)
        self.assertEqual(result, "sent")
        _, kwargs = send_retry.call_args
        self.assertEqual(kwargs["parse_mode"], "MarkdownV2")

    async def test_say_renders_html_when_backend_html(self):
        """say(..., backend=Backend.HTML) renders spans as HTML and sets HTML parse mode."""
        update = MagicMock()
        update.callback_query = None
        update.effective_chat.id = 123
        update.message = None
        ctx = MagicMock()
        text = Message()
        text.add_line(bold("active"), plain("gapgpt"))
        with patch(
            "services.send_pretty._send_with_retry", new=AsyncMock(return_value="sent")
        ) as send_retry:
            result = await say(update, ctx, text, backend=Backend.HTML)
        self.assertEqual(result, "sent")
        args, kwargs = send_retry.call_args
        self.assertEqual(args[2], "<b>active</b>gapgpt")
        self.assertEqual(kwargs["parse_mode"], "HTML")

    async def test_say_edits_html_when_callback_and_backend_html(self):
        update = MagicMock()
        update.callback_query = MagicMock()
        update.effective_chat.id = 123
        ctx = MagicMock()
        text = Message()
        text.add_line(code("gpt-4o"))
        with patch(
            "services.send_pretty._edit_with_retry", new=AsyncMock(return_value="edited")
        ) as edit:
            result = await say(update, ctx, text, backend=Backend.HTML)
        self.assertEqual(result, "edited")
        args, kwargs = edit.call_args
        self.assertEqual(args[1], "<code>gpt-4o</code>")
        self.assertEqual(kwargs["parse_mode"], "HTML")

    async def test_send_renders_html_when_backend_html(self):
        bot = MagicMock()
        text = Message()
        text.add_line(bold("پیش‌تنظیم فعال:"), plain("gapgpt"))
        with patch(
            "services.send_pretty._send_with_retry", new=AsyncMock(return_value="sent")
        ) as send_retry:
            result = await send(123, text, bot=bot, backend=Backend.HTML)
        self.assertEqual(result, "sent")
        args, kwargs = send_retry.call_args
        self.assertEqual(args[2], "<b>پیش‌تنظیم فعال:</b>gapgpt")
        self.assertEqual(kwargs["parse_mode"], "HTML")

    async def test_say_default_backend_is_markdown_v2(self):
        """Default remains MarkdownV2 so existing learner call sites are untouched."""
        update = MagicMock()
        update.callback_query = None
        update.effective_chat.id = 123
        update.message = None
        ctx = MagicMock()
        text = Message()
        text.add_line(bold("واژه"))
        with patch(
            "services.send_pretty._send_with_retry", new=AsyncMock(return_value="sent")
        ) as send_retry:
            await say(update, ctx, text)
        args, kwargs = send_retry.call_args
        self.assertEqual(args[2], "*واژه*")
        self.assertEqual(kwargs["parse_mode"], "MarkdownV2")

    async def test_say_edit_not_found_falls_back_to_replacement_send(self):
        """Any BadRequest other than 'message is not modified' (e.g. message to
        edit not found) must send a replacement message, not silently drop."""
        update = MagicMock()
        update.effective_chat.id = 123
        query = MagicMock()
        query.edit_message_text = AsyncMock(
            side_effect=BadRequest("message to edit not found")
        )
        update.callback_query = query
        ctx = MagicMock()
        text = Message()
        text.add_line(plain("hello"))
        with patch(
            "services.send_pretty._edit_with_retry",
            new=AsyncMock(side_effect=BadRequest("message to edit not found")),
        ):
            with patch(
                "services.send_pretty._send_with_retry",
                new=AsyncMock(return_value="replacement"),
            ) as send_retry:
                result = await say(update, ctx, text)
        self.assertEqual(result, "replacement")
        send_retry.assert_called_once()
        args, kwargs = send_retry.call_args
        self.assertEqual(args[1], 123)
        self.assertEqual(args[2], "hello")

    async def test_say_not_modified_does_not_send_replacement(self):
        update = MagicMock()
        update.effective_chat.id = 123
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock(
            side_effect=BadRequest("message is not modified")
        )
        update.callback_query = query
        ctx = MagicMock()
        text = Message()
        text.add_line(plain("hello"))
        with patch(
            "services.send_pretty._edit_with_retry",
            new=AsyncMock(side_effect=BadRequest("message is not modified")),
        ):
            with patch(
                "services.send_pretty.notify_callback",
                new=AsyncMock(return_value="acked"),
            ) as notify:
                with patch(
                    "services.send_pretty._send_with_retry",
                    new=AsyncMock(return_value="should-not-send"),
                ) as send_retry:
                    result = await say(update, ctx, text)
        self.assertEqual(result, "acked")
        notify.assert_called_once()
        send_retry.assert_not_called()

    async def test_edit_routes_through_message_edit_seam(self):
        """edit() targets an explicit message_id via the retry/slot seam."""
        bot = MagicMock()
        text = Message()
        text.add_line(bold("واژه"))
        with patch(
            "services.send_pretty._edit_message_with_retry",
            new=AsyncMock(return_value="edited"),
        ) as edit_retry:
            result = await edit(123, 99, text, bot=bot)
        self.assertEqual(result, "edited")
        edit_retry.assert_called_once()
        args, kwargs = edit_retry.call_args
        self.assertIs(args[0], bot)
        self.assertEqual(args[1], 123)
        self.assertEqual(args[2], 99)
        self.assertEqual(args[3], "*واژه*")
        self.assertEqual(kwargs["parse_mode"], "MarkdownV2")
        self.assertNotIn("reply_markup", kwargs)

    async def test_edit_raw_mdv2_string_with_keyboard(self):
        """edit() accepts a pre-formatted MDV2 string via raw= and passes markup."""
        bot = MagicMock()
        kbd = MagicMock()
        with patch(
            "services.send_pretty._edit_message_with_retry",
            new=AsyncMock(return_value="edited"),
        ) as edit_retry:
            result = await edit(
                123, 99, "*س*", bot=bot, raw=RawFormat.MDV2, keyboard=kbd
            )
        self.assertEqual(result, "edited")
        edit_retry.assert_called_once()
        args, kwargs = edit_retry.call_args
        self.assertIs(args[0], bot)
        self.assertEqual(args[3], "*س*")
        self.assertEqual(kwargs["parse_mode"], "MarkdownV2")
        self.assertIs(kwargs["reply_markup"], kbd)

    async def test_edit_backfills_keyboard_from_message_when_omitted(self):
        """edit() omitting keyboard inherits the Message's own keyboard."""
        bot = MagicMock()
        kbd = MagicMock()
        text = Message()
        text.add_line(plain("س"))
        text.set_keyboard(kbd)
        with patch(
            "services.send_pretty._edit_message_with_retry",
            new=AsyncMock(return_value="edited"),
        ) as edit_retry:
            await edit(123, 99, text, bot=bot)
        self.assertIs(edit_retry.call_args.kwargs["reply_markup"], kbd)

    async def test_edit_explicit_none_strips_keyboard_from_message(self):
        """edit(keyboard=None) deliberately clears a Message-carried keyboard
        rather than re-applying it (Kilo review sentinel)."""
        bot = MagicMock()
        kbd = MagicMock()
        text = Message()
        text.add_line(plain("س"))
        text.set_keyboard(kbd)
        with patch(
            "services.send_pretty._edit_message_with_retry",
            new=AsyncMock(return_value="edited"),
        ) as edit_retry:
            await edit(123, 99, text, bot=bot, keyboard=None)
        self.assertNotIn("reply_markup", edit_retry.call_args.kwargs)

    async def test_edit_markup_routes_through_markup_edit_seam(self):
        """edit_markup() edits only the reply markup of an existing message."""
        bot = MagicMock()
        kbd = MagicMock()
        with patch(
            "services.send_pretty._edit_markup_with_retry",
            new=AsyncMock(return_value="edited"),
        ) as markup_retry:
            result = await edit_markup(123, 99, kbd, bot=bot)
        self.assertEqual(result, "edited")
        markup_retry.assert_called_once()
        args, kwargs = markup_retry.call_args
        self.assertIs(args[0], bot)
        self.assertEqual(args[1], 123)
        self.assertEqual(args[2], 99)
        self.assertIs(args[3], kbd)

    async def test_edit_markup_explicit_none_clears_keyboard(self):
        """edit_markup(reply_markup=None) passes None through to clear it."""
        bot = MagicMock()
        with patch(
            "services.send_pretty._edit_markup_with_retry",
            new=AsyncMock(return_value="edited"),
        ) as markup_retry:
            result = await edit_markup(123, 99, None, bot=bot)
        self.assertEqual(result, "edited")
        self.assertIs(markup_retry.call_args.args[3], None)


def _one_line(span, backend=Backend.MDV2) -> str:
    msg = Message()
    msg.add_line(span)
    return msg.render(backend)


def _resolve_raw(text, fmt):
    from services.send_pretty import _resolve_content

    return _resolve_content(text, fmt)


if __name__ == "__main__":
    unittest.main()