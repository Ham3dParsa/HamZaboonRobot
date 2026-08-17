"""Deep outbound-message module (R3) — single owner of the outbound parse
standard, escaping, retry, concurrency slots, and the edit-vs-send decision.

The rest of the codebase currently disperses this across 3 parse standards
(MarkdownV2 / HTML / none), ~50 hand-picked ``ParseMode`` call sites, and the
``@@@`` / ``@@BOT@@`` / ``@@START@@`` sentinels. This module centralizes that
behind a recursive span tree: every span can nest other spans (bold can hold a
code span or a spoiler; a quote can hold bold), so nested formatting is
supported structurally and a future native-Markdown/"richmessages" standard is
a one-module swap (a new ``Backend`` + renderer clause).

Escaping is scoped to the *content of each leaf*; markup is emitted by the
renderer around the structure — never by the caller. So ``*``-loss, sentinels,
and unescaped dynamic values become structurally impossible. A malformed tree
fails at construction, not runtime.

``send_pretty`` composes the existing retry/slot helpers
(``services/utils/helpers.py`` ``_send_with_retry`` / ``_edit_with_retry`` /
``_telegram_slots``) and the escaping functions
(``services/utils/formatting.py``). It is a peer of ``helpers.py`` — a
domain-owning module, consistent with semantic centralization; it is NOT inside
``services/utils/``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from services.utils.callback_notifications import notify_callback
from services.utils.formatting import escape_mdv2, escape_mdv2_code, html_escape
from services.utils.helpers import (
    _edit_with_retry,
    _send_with_retry,
    _telegram_slots,
)

logger = logging.getLogger(__name__)

__all__ = [
    "Backend",
    "RawFormat",
    "Message",
    "Span",
    "Plain",
    "Bold",
    "Italic",
    "Code",
    "Spoiler",
    "Link",
    "Quote",
    "Newline",
    "plain",
    "bold",
    "italic",
    "code",
    "spoiler",
    "link",
    "quote",
    "nl",
    "line",
    "send",
    "say",
]

# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


class Backend(str, Enum):
    """The parse standard ``Message.render`` targets.

    The active backend is chosen by config/availability. MarkdownV2 is the
    default; ``RICH`` (native Markdown / Telegram entities) is the future
    one-module swap and is not yet implemented.
    """

    MDV2 = "mdv2"
    HTML = "html"
    PLAIN = "plain"
    RICH = "rich"  # reserved, not implemented


class RawFormat(str, Enum):
    """Declared parse format for the legacy ``raw=`` escape hatch.

    A caller passing a pre-formatted string via ``raw=`` MUST declare its
    format; the module never guesses. ``AUTO`` is deliberately absent.
    """

    HTML = "html"
    MDV2 = "mdv2"
    PLAIN = "plain"


def _parse_mode_for(backend: Backend):
    if backend is Backend.MDV2:
        return ParseMode.MARKDOWN_V2
    if backend is Backend.HTML:
        return ParseMode.HTML
    return None


def _parse_mode_for_raw(fmt: RawFormat):
    if fmt is RawFormat.HTML:
        return ParseMode.HTML
    if fmt is RawFormat.MDV2:
        return ParseMode.MARKDOWN_V2
    return None


# ---------------------------------------------------------------------------
# Content vocabulary — recursive spans (pure value types, no Telegram)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    """Base class for a content span. Subclasses carry children/leaf data."""


@dataclass(frozen=True)
class Plain(Span):
    text: str


@dataclass(frozen=True)
class Bold(Span):
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Italic(Span):
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Code(Span):
    text: str


@dataclass(frozen=True)
class Spoiler(Span):
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Link(Span):
    url: str
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Quote(Span):
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Newline(Span):
    pass


def _span(value) -> Span:
    """Coerce a bare string into a ``Plain`` span; pass spans through."""
    if isinstance(value, Span):
        return value
    return Plain(str(value))


def plain(x) -> Span:
    return _span(x)


def bold(*children) -> Span:
    return Bold(tuple(_span(c) for c in children))


def italic(*children) -> Span:
    return Italic(tuple(_span(c) for c in children))


def code(x) -> Span:
    return Code(_plain_text(x))


def spoiler(*children) -> Span:
    return Spoiler(tuple(_span(c) for c in children))


def link(url: str, *children) -> Span:
    return Link(url, tuple(_span(c) for c in children))


def quote(*children) -> Span:
    return Quote(tuple(_span(c) for c in children))


def nl() -> Span:
    return Newline()


def _plain_text(value) -> str:
    if isinstance(value, Span):
        if isinstance(value, Plain):
            return value.text
        return "".join(_plain_text(c) for c in value.children)
    return str(value)


# ---------------------------------------------------------------------------
# Message — a list of lines
# ---------------------------------------------------------------------------


@dataclass
class Message:
    """A list of lines; ``line(*spans)`` appends one line of spans.

    ``render(backend)`` walks the span tree and returns the formatted string
    for the given parse standard. ``keyboard`` is the optional reply markup
    carried on the message.
    """

    _lines: list[tuple[Span, ...]] = None  # type: ignore[assignment]
    keyboard: InlineKeyboardMarkup | None = None

    def __post_init__(self):
        if self._lines is None:
            object.__setattr__(self, "_lines", [])

    def add_line(self, *spans) -> None:
        self._lines.append(tuple(_span(c) for c in spans))

    def set_keyboard(self, keyboard: InlineKeyboardMarkup | None) -> None:
        self.keyboard = keyboard

    def render(self, backend: Backend = Backend.MDV2) -> str:
        if backend is Backend.RICH:
            raise NotImplementedError("Backend.RICH is reserved, not implemented")
        if backend is Backend.HTML:
            renderer = _render_html
        elif backend is Backend.PLAIN:
            renderer = _render_plain
        else:
            renderer = _render_mdv2
        return "\n".join(renderer(line) for line in self._lines)


def line(*spans) -> tuple[Span, ...]:
    return tuple(_span(c) for c in spans)


# ---------------------------------------------------------------------------
# Renderers — escape leaf content only; emit markup around structure
# ---------------------------------------------------------------------------


def _render_mdv2(children: tuple[Span, ...]) -> str:
    parts: list[str] = []
    for span in children:
        if isinstance(span, Plain):
            parts.append(escape_mdv2(span.text))
        elif isinstance(span, Bold):
            parts.append("*" + _render_mdv2(span.children) + "*")
        elif isinstance(span, Italic):
            parts.append("_" + _render_mdv2(span.children) + "_")
        elif isinstance(span, Code):
            parts.append("`" + escape_mdv2_code(span.text) + "`")
        elif isinstance(span, Spoiler):
            parts.append("||" + _render_mdv2(span.children) + "||")
        elif isinstance(span, Link):
            inner = _render_mdv2(span.children)
            parts.append("[" + inner + "](" + escape_mdv2(span.url) + ")")
        elif isinstance(span, Quote):
            inner = _render_mdv2(span.children)
            parts.append("> " + inner.replace("\n", "\n> "))
        elif isinstance(span, Newline):
            parts.append("\n")
        else:  # pragma: no cover - defensive
            raise TypeError(f"Unsupported span type for MDV2: {type(span).__name__}")
    return "".join(parts)


def _render_html(children: tuple[Span, ...]) -> str:
    parts: list[str] = []
    for span in children:
        if isinstance(span, Plain):
            parts.append(html_escape(span.text))
        elif isinstance(span, Bold):
            parts.append("<b>" + _render_html(span.children) + "</b>")
        elif isinstance(span, Italic):
            parts.append("<i>" + _render_html(span.children) + "</i>")
        elif isinstance(span, Code):
            parts.append("<code>" + html_escape(span.text) + "</code>")
        elif isinstance(span, Spoiler):
            parts.append(
                '<span class="tg-spoiler">' + _render_html(span.children) + "</span>"
            )
        elif isinstance(span, Link):
            parts.append(
                '<a href="' + html_escape(span.url) + '">' + _render_html(span.children) + "</a>"
            )
        elif isinstance(span, Quote):
            parts.append("<blockquote>" + _render_html(span.children) + "</blockquote>")
        elif isinstance(span, Newline):
            parts.append("<br/>")
        else:  # pragma: no cover - defensive
            raise TypeError(f"Unsupported span type for HTML: {type(span).__name__}")
    return "".join(parts)


def _render_plain(children: tuple[Span, ...]) -> str:
    parts: list[str] = []
    for span in children:
        if isinstance(span, Plain):
            parts.append(span.text)
        elif isinstance(span, (Bold, Italic, Spoiler, Quote)):
            parts.append(_render_plain(span.children))
        elif isinstance(span, Code):
            parts.append(span.text)
        elif isinstance(span, Link):
            parts.append(_render_plain(span.children))
        elif isinstance(span, Newline):
            parts.append("\n")
        else:  # pragma: no cover - defensive
            raise TypeError(f"Unsupported span type for PLAIN: {type(span).__name__}")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Delivery verbs — the only Telegram-touching seam
# ---------------------------------------------------------------------------


def _resolve_content(
    content, raw: RawFormat | None, backend: Backend = Backend.MDV2
):
    """Return (text, parse_mode) from a Message or a raw pre-formatted string.

    ``raw`` MUST be declared (never guessed). When ``raw`` is None, ``content``
    is a ``Message`` and is rendered with the active backend (default MDV2).
    ``raw`` is only valid for a pre-formatted string; passing it with a
    ``Message`` is a caller bug and fails loudly rather than emitting an object
    repr. ``backend`` is ignored when ``raw`` is supplied (the raw string
    declares its own format).
    """
    if raw is not None:
        if isinstance(content, Message):
            raise TypeError(
                "raw= is for pre-formatted strings; pass a Message without raw="
            )
        fmt = RawFormat(raw)
        return str(content), _parse_mode_for_raw(fmt)
    if not isinstance(content, Message):
        raise TypeError(
            "content must be a Message, or pass raw=<format> for a pre-formatted string"
        )
    return content.render(backend), _parse_mode_for(backend)


async def send(
    chat_id: int,
    content,
    *,
    bot,
    keyboard: InlineKeyboardMarkup | None = None,
    raw: RawFormat | None = None,
    backend: Backend = Backend.MDV2,
    **kwargs,
):
    """Send a new message, routing through the shared retry/slot seam."""
    text, parse_mode = _resolve_content(content, raw, backend)
    markup = keyboard
    if markup is None and isinstance(content, Message):
        markup = content.keyboard
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if markup is not None:
        kwargs["reply_markup"] = markup
    return await _send_with_retry(bot, chat_id, text, **kwargs)


async def say(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    content,
    *,
    mode: str = "auto",
    keyboard: InlineKeyboardMarkup | None = None,
    raw: RawFormat | None = None,
    backend: Backend = Backend.MDV2,
    **kwargs,
):
    """Edit the callback message when a callback is present, else send new.

    ``mode="auto"`` edits when ``update.callback_query`` is set, otherwise sends.
    ``mode="edit"`` forces an edit; ``mode="send"`` forces a new message.
    ``backend`` selects the render standard for ``Message`` content (default
    MDV2); ignored when ``raw`` is supplied.
    BadRequest fallback ("message is not modified" / "not found") reuses the
    existing edit-then-fall-back-to-send semantics, routing through the retry
    seam.
    """
    text, parse_mode = _resolve_content(content, raw, backend)
    markup = keyboard
    if markup is None and isinstance(content, Message):
        markup = content.keyboard
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if markup is not None:
        kwargs["reply_markup"] = markup

    query = update.callback_query
    if query is not None and mode != "send":
        try:
            return await _edit_with_retry(query, text, **kwargs)
        except BadRequest as exc:
            message = str(exc).lower()
            if "message is not modified" in message:
                return await notify_callback(query)
            # Any other BadRequest (e.g. "message to edit not found") falls back
            # to a replacement message, matching the legacy _edit_or_send
            # semantics so a deleted/expired message still yields output.
            logger.info("callback edit failed; sending replacement message")
            return await _send_with_retry(context.bot, update.effective_chat.id, text, **kwargs)
    # No callback: reply to the source message when present (preserves the
    # legacy _edit_or_send semantics for text-awaiting flows), still holding the
    # shared concurrency slot; otherwise send a plain new message.
    if update.message is not None and mode != "edit":
        async with _telegram_slots:
            return await update.message.reply_text(text, **kwargs)
    return await _send_with_retry(context.bot, update.effective_chat.id, text, **kwargs)
