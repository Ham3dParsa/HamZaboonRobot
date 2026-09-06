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

``send_pretty`` OWNS the Telegram send retry/slot seam (``_telegram_slots``,
``_send_media_with_retry`` + byte capture + allowlist): the single retry core
for all sends — RetryAfter-only retries, 30s clamp, Forbidden→set_user_blocked
(R3 policy, unchanged). ``services/utils/helpers.py`` keeps a thin re-export
shim for one PR plus the edit/delete retry loops; escaping comes from
(``services/utils/formatting.py``). It is a peer of ``helpers.py`` — a
domain-owning module, consistent with semantic centralization; it is NOT inside
``services/utils/``.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from enum import Enum

from telegram import InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut
from telegram.ext import ContextTypes

from config import TELEGRAM_MAX_CONCURRENCY
from config.custom_emoji import resolve_emoji
from services import db, telegram_rich
from services.utils import helpers as _helpers
from services.utils.callback_notifications import notify_callback
from services.utils.formatting import escape_mdv2, escape_mdv2_code, html_escape

import re as _re_rich

_RICH_ESCAPE_RE = _re_rich.compile(r"([\\*_~|`\[\]()#><=\-+.!])")


def _escape_rich(text: str) -> str:
    """Escape dynamic text for Rich Markdown so it cannot inject markup."""
    if not text:
        return ""
    # Escape backslash first is handled by the pattern (\\ is in set)
    return _RICH_ESCAPE_RE.sub(r"\\\1", text)


def _escape_rich_code(text: str) -> str:
    if not text:
        return ""
    return text.replace("\\", "\\\\").replace("`", "\\`")
from services.utils.helpers import (
    _RETRY_BACKOFF_SLEEP_MAX,
    _edit_markup_with_retry,
    _edit_message_with_retry,
    _edit_with_retry,
    _send_with_retry,
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
    "Underline",
    "Strikethrough",
    "Marked",
    "TgSpoiler",
    "Link",
    "Quote",
    "Newline",
    "CustomEmoji",
    "Heading",
    "Table",
    "List",
    "ListItem",
    "TaskListItem",
    "Details",
    "Math",
    "Raw",
    "plain",
    "bold",
    "italic",
    "code",
    "spoiler",
    "underline",
    "strike",
    "mark",
    "tg_spoiler",
    "emoji",
    "heading",
    "table",
    "rich_list",
    "details",
    "math",
    "raw_rich",
    "link",
    "quote",
    "nl",
    "line",
    "send",
    "say",
    "edit",
    "edit_markup",
]

# ---------------------------------------------------------------------------
# Telegram send retry/slot seam (R2 owner — phase-03 retry seam move).
#
# Single retry core for ALL Telegram sends. Policy (R3, unchanged from the
# helpers.py original): sends are non-idempotent — TimedOut/NetworkError are
# never retried; clamped RetryAfter (30s) is the only retried error;
# Forbidden marks the user blocked. ``services/utils/helpers.py`` re-exports
# these names for one PR so existing callers (tts_service, archive) keep
# working untouched; new code must import from here directly.
# ---------------------------------------------------------------------------

_telegram_slots = asyncio.Semaphore(TELEGRAM_MAX_CONCURRENCY)


async def _rich_api_request(bot, method: str, payload: dict[str, object]):
    """Slot-protected raw Bot API call for Rich Messages.

    Lives here (not in helpers) so the slot never leaves its owner module.
    ``services/telegram_rich.py`` imports it from here (lazily — this module
    imports telegram_rich at top level, so a top-level import there would
    cycle).
    """
    async with _telegram_slots:
        return await bot.do_api_request(method, api_kwargs=payload, return_type=None)


def _capture_media_bytes(media, filename_hint: str | None = None) -> tuple[bytes | None, str | None, bool]:
    """Extract re-creatable bytes + filename from InputFile/BytesIO for RetryAfter retries.

    Returns (raw_bytes, filename, is_inputfile). raw_bytes is None when the
    media cannot be captured (file-id/path callers — not retried via bytes).
    Single source for both voice and document senders (R2).
    """
    filename: str | None = filename_hint
    raw_bytes: bytes | None = None
    is_inputfile = False
    try:
        if isinstance(media, InputFile):
            is_inputfile = True
            filename = getattr(media, "filename", None) or filename
            content = getattr(media, "input_file_content", None)
            if isinstance(content, (bytes, bytearray)):
                raw_bytes = bytes(content)
            elif hasattr(content, "getvalue"):
                try:
                    raw_bytes = content.getvalue()
                except Exception:
                    raw_bytes = None
            elif hasattr(content, "read"):
                try:
                    try:
                        content.seek(0)
                    except Exception:
                        pass
                    raw_bytes = content.read()
                    if isinstance(raw_bytes, bytearray):
                        raw_bytes = bytes(raw_bytes)
                except Exception:
                    raw_bytes = None
        elif hasattr(media, "getvalue"):
            try:
                raw_bytes = media.getvalue()
            except Exception:
                raw_bytes = None
            if filename is None:
                filename = getattr(media, "name", None)
    except Exception:
        pass
    return raw_bytes, filename, is_inputfile


# Allowlist for _send_media_with_retry dispatch — caller-controlled method
# strings must never reach arbitrary Bot attributes (e.g. ban_chat_member).
_SEND_METHOD_ALLOWLIST: tuple[str, ...] = ("send_message", "send_voice", "send_document")

# method -> required media_kw (None = plain-text send). Hoisted to module
# const so the dispatch contract is inspectable without calling (phase-03 R2).
_SEND_MEDIA_EXPECTED: dict[str, str | None] = {
    "send_message": None,
    "send_voice": "voice",
    "send_document": "document",
}


async def _send_media_with_retry(
    bot,
    chat_id: int,
    *,
    method: str,
    media_kw: str | None = None,
    media=None,
    filename: str | None = None,
    reset_telegram_cb: bool = True,
    **kwargs,
):
    """Single retry core for all Telegram sends (R1).

    Sends are non-idempotent: TimedOut/NetworkError are never retried — the
    message may already be delivered and a retry would duplicate. Clamped
    RetryAfter (30s) is the only retried error for sends. ``_telegram_slots``
    is the shared concurrency limiter owned by this module.
    """
    if method not in _SEND_METHOD_ALLOWLIST:
        raise ValueError(f"unsupported send method: {method!r}")
    if media_kw not in (None, "voice", "document"):
        raise ValueError(f"unsupported media_kw: {media_kw!r}")
    if _SEND_MEDIA_EXPECTED[method] != media_kw:
        raise ValueError(f"media_kw/method mismatch: {media_kw!r} with {method!r}")
    # Pre-capture bytes once so RetryAfter retries can rebuild InputFile
    raw_bytes: bytes | None = None
    fname: str | None = filename
    is_inputfile = False
    if media_kw is not None and media is not None:
        raw_bytes, fname, is_inputfile = _capture_media_bytes(media, filename)
    for attempt in range(3):
        try:
            async with _telegram_slots:
                if media_kw is not None:
                    to_send = media
                    if raw_bytes is not None:
                        if is_inputfile:
                            to_send = InputFile(io.BytesIO(raw_bytes), filename=fname or ("voice.mp3" if media_kw == "voice" else "file.db"))
                        else:
                            if fname:
                                to_send = InputFile(io.BytesIO(raw_bytes), filename=fname)
                            else:
                                to_send = io.BytesIO(raw_bytes)
                    result = await getattr(bot, method)(chat_id=chat_id, **{media_kw: to_send}, **kwargs)
                else:
                    result = await getattr(bot, method)(chat_id=chat_id, text=media, **kwargs)
                if reset_telegram_cb:
                    # Dynamic lookup: tests patch helpers._reset_telegram_cb and
                    # must observe the call through this owner module.
                    _helpers._reset_telegram_cb()
                return result
        except Forbidden:
            if chat_id > 0:
                try:
                    db.set_user_blocked(chat_id)
                except Exception:
                    pass
            raise
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            logger.warning(
                "send RetryAfter %s attempt %s/3 chat_id=%s method=%s",
                exc.retry_after, attempt + 1, chat_id, method,
            )
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            raise
        except BaseException:
            logger.exception("send failed chat_id=%s method=%s", chat_id, method)
            raise


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
class Underline(Span):
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Strikethrough(Span):
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Marked(Span):
    children: tuple["Span", ...]


@dataclass(frozen=True)
class TgSpoiler(Span):
    """Table-safe spoiler via ``<tg-spoiler>`` (Rich Markdown can contain HTML).
    Unlike ``||`` it renders inside table cells."""

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


@dataclass(frozen=True)
class CustomEmoji(Span):
    custom_emoji_id: str
    fallback: str


@dataclass(frozen=True)
class Heading(Span):
    level: int
    children: tuple["Span", ...]

    def __post_init__(self):
        object.__setattr__(self, "children", _as_tuple(self.children))


@dataclass(frozen=True)
class Table(Span):
    header: tuple["Span", ...] | None
    rows: tuple[tuple["Span", ...], ...]


@dataclass(frozen=True)
class ListItem(Span):
    children: tuple["Span", ...]

    def __post_init__(self):
        object.__setattr__(self, "children", _as_tuple(self.children))


@dataclass(frozen=True)
class TaskListItem(Span):
    checked: bool
    children: tuple["Span", ...]

    def __post_init__(self):
        object.__setattr__(self, "children", _as_tuple(self.children))


@dataclass(frozen=True)
class List(Span):
    ordered: bool
    items: tuple["Span", ...]


@dataclass(frozen=True)
class Details(Span):
    summary: "Span"
    children: tuple["Span", ...]
    open: bool = False

    def __post_init__(self):
        object.__setattr__(self, "children", _as_tuple(self.children))
        object.__setattr__(self, "summary", _as_tuple(self.summary))


@dataclass(frozen=True)
class Math(Span):
    expr: str
    block: bool = False


@dataclass(frozen=True)
class Raw(Span):
    """Verbatim Rich-markup injection (e.g. an HTML ``<table>`` inside a
    ``<details>`` that the span tree cannot express).  Rich-only: renders the text
    as-is; other backends degrade it to plain text."""

    text: str


def _span(value) -> Span:
    """Coerce a bare string into a ``Plain`` span; pass spans through."""
    if isinstance(value, Span):
        return value
    return Plain(str(value))


def _as_tuple(value) -> tuple[Span, ...]:
    """Normalize a single span or an iterable of spans into a tuple."""
    if isinstance(value, Span):
        return (value,)
    return tuple(value)


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


def underline(*children) -> Span:
    return Underline(tuple(_span(c) for c in children))


def strike(*children) -> Span:
    return Strikethrough(tuple(_span(c) for c in children))


def mark(*children) -> Span:
    return Marked(tuple(_span(c) for c in children))


def tg_spoiler(*children) -> Span:
    return TgSpoiler(tuple(_span(c) for c in children))


def link(url: str, *children) -> Span:
    return Link(url, tuple(_span(c) for c in children))


def quote(*children) -> Span:
    return Quote(tuple(_span(c) for c in children))


def nl() -> Span:
    return Newline()


def raw_rich(text: str) -> Span:
    """Wrap verbatim Rich markup as a ``Raw`` span (Rich-only, injected as-is)."""
    return Raw(text)


def emoji(key_or_id: str, *, fallback: str | None = None) -> Span:
    """A custom emoji resolved via ``config.custom_emoji.resolve_emoji``.

    Pass a registry key (e.g. ``"book"``) or a raw ``custom_emoji_id``. The
    ``fallback`` is the plain emoji shown where custom emoji can't render.
    """
    cid, fb = resolve_emoji(key_or_id, fallback=fallback)
    return CustomEmoji(cid, fb)


def _plain_text(value) -> str:
    if isinstance(value, Span):
        if isinstance(value, Plain):
            return value.text
        if isinstance(value, CustomEmoji):
            return value.fallback
        return "".join(_plain_text(c) for c in value.children)
    return str(value)


def heading(level: int, *children) -> Span:
    return Heading(level, tuple(_span(c) for c in children))


def table(header: tuple | None, *rows) -> Span:
    hdr = None if header is None else tuple(_span(c) for c in header)
    return Table(hdr, tuple(tuple(_span(c) for c in r) for r in rows))


def rich_list(ordered: bool, *items) -> Span:
    return List(ordered, tuple(_span(c) for c in items))


def details(summary, *children, open: bool = False) -> Span:
    return Details(_span(summary), tuple(_span(c) for c in children), open=open)


def math(expr: str, *, block: bool = False) -> Span:
    return Math(expr, block)


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
            renderer = _render_rich
        elif backend is Backend.HTML:
            renderer = _render_html
        elif backend is Backend.PLAIN:
            renderer = _render_plain
        else:
            renderer = _render_mdv2
        if backend is Backend.RICH:
            # Telegram's Rich markdown (CommonMark-like) treats a single \n as a
            # soft break, so adjacent blocks collapse onto one line. Separate
            # blocks with a blank line so each add_line is a distinct block.
            return "\n\n".join(renderer(line) for line in self._lines)
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
        elif isinstance(span, TgSpoiler):
            parts.append("||" + _render_mdv2(span.children) + "||")
        elif isinstance(span, Underline):
            parts.append("__" + _render_mdv2(span.children) + "__")
        elif isinstance(span, Strikethrough):
            parts.append("~" + _render_mdv2(span.children) + "~")
        elif isinstance(span, Marked):
            parts.append("*" + _render_mdv2(span.children) + "*")
        elif isinstance(span, Link):
            inner = _render_mdv2(span.children)
            parts.append("[" + inner + "](" + escape_mdv2(span.url) + ")")
        elif isinstance(span, Quote):
            inner = _render_mdv2(span.children)
            parts.append("> " + inner.replace("\n", "\n> "))
        elif isinstance(span, Newline):
            parts.append("\n")
        elif isinstance(span, CustomEmoji):
            parts.append(
                "![" + escape_mdv2(span.fallback) + "](tg://emoji?id=" + span.custom_emoji_id + ")"
            )
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
        elif isinstance(span, TgSpoiler):
            parts.append(
                '<span class="tg-spoiler">' + _render_html(span.children) + "</span>"
            )
        elif isinstance(span, Underline):
            parts.append("<u>" + _render_html(span.children) + "</u>")
        elif isinstance(span, Strikethrough):
            parts.append("<s>" + _render_html(span.children) + "</s>")
        elif isinstance(span, Marked):
            parts.append("<mark>" + _render_html(span.children) + "</mark>")
        elif isinstance(span, Link):
            parts.append(
                '<a href="' + html_escape(span.url) + '">' + _render_html(span.children) + "</a>"
            )
        elif isinstance(span, Quote):
            parts.append("<blockquote>" + _render_html(span.children) + "</blockquote>")
        elif isinstance(span, Newline):
            parts.append("\n")
        elif isinstance(span, CustomEmoji):
            parts.append(
                '<tg-emoji emoji-id="' + span.custom_emoji_id + '">'
                + html_escape(span.fallback)
                + "</tg-emoji>"
            )
        else:  # pragma: no cover - defensive
            raise TypeError(f"Unsupported span type for HTML: {type(span).__name__}")
    return "".join(parts)


def _plain_table(
    header: tuple["Span", ...] | None,
    rows: tuple[tuple["Span | tuple[Span, ...]", ...], ...],
) -> str:
    """Degrade a Table to plain text: header + rows, cells joined by ' | '."""
    def _cell(cell: "Span | tuple[Span, ...]") -> str:
        if isinstance(cell, tuple):
            return _render_plain(cell)
        return _render_plain((cell,))

    lines: list[str] = []
    if header:
        lines.append(" | ".join(_cell(c) for c in header))
    for row in rows:
        lines.append(" | ".join(_cell(c) for c in row))
    return "\n".join(lines)


def _plain_list(span: "Span") -> str:
    """Degrade a List / ListItem / TaskListItem to plain text lines."""
    if isinstance(span, List):
        ordered, items = span.ordered, span.items
    else:
        ordered, items = False, (span,)
    lines: list[str] = []
    for i, it in enumerate(items, 1):
        if isinstance(it, TaskListItem):
            marker = "[x] " if it.checked else "[ ] "
            body = _render_plain(it.children)
        elif isinstance(it, ListItem):
            marker = (f"{i}. " if ordered else "- ")
            body = _render_plain(it.children)
        else:
            marker = (f"{i}. " if ordered else "- ")
            body = _render_plain((it,))
        lines.append(marker + body)
    return "\n".join(lines)


def _render_plain(children: tuple[Span, ...]) -> str:
    parts: list[str] = []
    for span in children:
        if isinstance(span, Plain):
            parts.append(span.text)
        elif isinstance(span, (Bold, Italic, Spoiler, TgSpoiler, Underline, Strikethrough, Marked, Quote)):
            parts.append(_render_plain(span.children))
        elif isinstance(span, Code):
            parts.append(span.text)
        elif isinstance(span, Link):
            parts.append(_render_plain(span.children))
        elif isinstance(span, Newline):
            parts.append("\n")
        elif isinstance(span, CustomEmoji):
            parts.append(span.fallback)
        elif isinstance(span, Heading):
            parts.append("#" * span.level + " " + _render_plain(span.children))
        elif isinstance(span, Math):
            parts.append(span.expr)
        elif isinstance(span, Raw):
            parts.append(span.text)
        elif isinstance(span, (List, ListItem, TaskListItem)):
            parts.append(_plain_list(span))
        elif isinstance(span, Table):
            parts.append(_plain_table(span.header, span.rows))
        elif isinstance(span, Details):
            parts.append(
                _render_plain(span.summary) + ": " + _render_plain(span.children)
            )
        else:  # pragma: no cover - defensive
            raise TypeError(f"Unsupported span type for PLAIN: {type(span).__name__}")
    return "".join(parts)


def _rich_quote(children: tuple[Span, ...]) -> str:
    """Render a blockquote for Rich markdown.

    Telegram's Rich markdown treats a bare ``\\n`` inside a quote as a soft
    break, so two quoted lines collapse onto one. To put the translation on its
    own line *inside* the same quote, a ``Newline`` becomes an empty ``>`` line,
    which is a CommonMark paragraph break within the blockquote.
    """
    rendered = _render_rich(children)
    lines = rendered.split("\n")
    return "> " + "\n>\n> ".join(lines)


def _render_rich(children: tuple[Span, ...]) -> str:
    """Render spans to a Bot API 10.1 ``InputRichMessage`` markdown string."""
    parts: list[str] = []
    for span in children:
        if isinstance(span, Plain):
            parts.append(_escape_rich(span.text))
        elif isinstance(span, Bold):
            parts.append("**" + _render_rich(span.children) + "**")
        elif isinstance(span, Italic):
            parts.append("*" + _render_rich(span.children) + "*")
        elif isinstance(span, Code):
            parts.append("`" + _escape_rich_code(span.text) + "`")
        elif isinstance(span, Spoiler):
            parts.append("||" + _render_rich(span.children) + "||")
        elif isinstance(span, TgSpoiler):
            parts.append("<tg-spoiler>" + _render_rich(span.children) + "</tg-spoiler>")
        elif isinstance(span, Underline):
            parts.append("__" + _render_rich(span.children) + "__")
        elif isinstance(span, Strikethrough):
            parts.append("~~" + _render_rich(span.children) + "~~")
        elif isinstance(span, Marked):
            parts.append("==" + _render_rich(span.children) + "==")
        elif isinstance(span, Link):
            safe_url = span.url.replace("\\", "\\\\").replace(")", "\\)")
            parts.append("[" + _render_rich(span.children) + "](" + safe_url + ")")
        elif isinstance(span, Quote):
            parts.append(_rich_quote(span.children))
        elif isinstance(span, Newline):
            parts.append("\n")
        elif isinstance(span, CustomEmoji):
            parts.append("![](tg://emoji?id=" + span.custom_emoji_id + ")")
        elif isinstance(span, Heading):
            parts.append(("#" * span.level) + " " + _render_rich(span.children))
        elif isinstance(span, Math):
            parts.append(
                ("$$" + span.expr + "$$") if span.block else ("$" + span.expr + "$")
            )
        elif isinstance(span, Raw):
            parts.append(span.text)
        elif isinstance(span, Details):
            summary = _render_rich(span.summary)
            body = _render_rich(span.children).rstrip("\n")
            parts.append(
                "<details"
                + (" open" if span.open else "")
                + "><summary>"
                + summary
                + "</summary>"
                + body
                + "</details>"
            )
        elif isinstance(span, Table):
            parts.append(_rich_table(span.header, span.rows))
        elif isinstance(span, (List, ListItem, TaskListItem)):
            parts.append(_rich_list(span))
        else:  # pragma: no cover - defensive
            raise TypeError(f"Unsupported span type for RICH: {type(span).__name__}")
    return "".join(parts)


def _render_cell(cell: "Span | tuple[Span, ...]") -> str:
    """Render one table cell: a single span or a tuple of spans (e.g. a sentence
    with a bolded keyword)."""
    if isinstance(cell, tuple):
        return _render_rich(cell)
    return _render_rich((cell,))


def _rich_table(
    header: tuple["Span", ...] | None,
    rows: tuple[tuple["Span | tuple[Span, ...]", ...], ...],
) -> str:
    """Render a GFM pipe table (header row + alignment row + body rows)."""
    lines: list[str] = []
    if header:
        lines.append("| " + " | ".join(_render_cell(c) for c in header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_render_cell(c) for c in row) + " |")
    return "\n".join(lines)


def _rich_list(span: "Span") -> str:
    """Render a ``List`` / ``ListItem`` / ``TaskListItem`` as markdown lines."""
    if isinstance(span, List):
        ordered, items = span.ordered, span.items
    else:
        ordered, items = False, (span,)
    lines: list[str] = []
    for i, it in enumerate(items, 1):
        if isinstance(it, TaskListItem):
            marker = "- [" + ("x" if it.checked else " ") + "] "
            body = _render_rich(it.children)
        elif isinstance(it, ListItem):
            marker = (f"{i}. " if ordered else "- ")
            body = _render_rich(it.children)
        else:
            marker = (f"{i}. " if ordered else "- ")
            body = _render_rich((it,))
        lines.append(marker + body)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Delivery verbs — the only Telegram-touching seam
# ---------------------------------------------------------------------------


class _Unset:
    """Sentinel distinguishing "keyboard not supplied" from an explicit None.

    A caller that deliberately passes ``keyboard=None`` wants to strip the
    buttons off a rendered ``Message``; without this sentinel it is
    indistinguishable from omitting the argument, and the message's own
    keyboard would be silently re-applied (Kilo review, RT-B2).
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


_UNSET = _Unset()


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
    keyboard: InlineKeyboardMarkup | None | _Unset = _UNSET,
    raw: RawFormat | None = None,
    backend: Backend = Backend.MDV2,
    is_rtl: bool = True,
    **kwargs,
):
    """Send a new message, routing through the shared retry/slot seam."""
    if keyboard is _UNSET:
        markup = content.keyboard if isinstance(content, Message) else None
    else:
        markup = keyboard
    if backend is Backend.RICH:
        if raw is not None:
            if isinstance(content, Message):
                raise TypeError("raw= is for pre-formatted strings; pass a Message without raw=")
            rich_text = str(content)
            mdv2_text = str(content)
            return await telegram_rich.send_rich_message(
                bot,
                chat_id,
                rich_text,
                mdv2_text,
                is_rtl=is_rtl,
                keyboard=markup,
                reply_parameters=kwargs.get("reply_parameters"),
            )
        rich_text = content.render(Backend.RICH) if isinstance(content, Message) else str(content)
        try:
            mdv2_text = content.render(Backend.MDV2) if isinstance(content, Message) else str(content)
        except TypeError:
            # Rich-only spans (Heading, Table, etc.) can't render to MDV2.
            # Degrade to plain text and escape it so the MDV2 fallback path
            # can't raise a parse error on the degraded content.
            mdv2_text = escape_mdv2(content.render(Backend.PLAIN)) if isinstance(content, Message) else str(content)
        return await telegram_rich.send_rich_message(
            bot,
            chat_id,
            rich_text,
            mdv2_text,
            is_rtl=is_rtl,
            keyboard=markup,
            reply_parameters=kwargs.get("reply_parameters"),
        )
    text, parse_mode = _resolve_content(content, raw, backend)
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
    keyboard: InlineKeyboardMarkup | None | _Unset = _UNSET,
    raw: RawFormat | None = None,
    backend: Backend = Backend.MDV2,
    is_rtl: bool = True,
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
    if keyboard is _UNSET:
        markup = content.keyboard if isinstance(content, Message) else None
    else:
        markup = keyboard
    if backend is Backend.RICH and isinstance(content, Message):
        rich_text = content.render(Backend.RICH)
        try:
            mdv2_text = content.render(Backend.MDV2)
        except TypeError:
            mdv2_text = escape_mdv2(content.render(Backend.PLAIN))
        query = update.callback_query
        if query is not None and mode != "send":
            return await telegram_rich.edit_rich_message(
                context.bot,
                update.effective_chat.id,
                query.message.message_id,
                rich_text,
                mdv2_text,
                is_rtl=is_rtl,
                keyboard=markup,
            )
        return await telegram_rich.send_rich_message(
            context.bot,
            update.effective_chat.id,
            rich_text,
            mdv2_text,
            is_rtl=is_rtl,
            keyboard=markup,
            reply_parameters=kwargs.get("reply_parameters"),
        )
    text, parse_mode = _resolve_content(content, raw, backend)
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


async def edit(
    chat_id: int,
    message_id: int,
    content,
    *,
    bot,
    keyboard: InlineKeyboardMarkup | None | _Unset = _UNSET,
    raw: RawFormat | None = None,
    backend: Backend = Backend.MDV2,
    **kwargs,
):
    """Edit an existing message by id, routing through the shared retry/slot seam.

    RT-B2: handler flows that keep an explicit ``message_id`` (e.g. the study
    card in ``state.study_msg_id``) edit that message rather than the callback
    message; ``say`` cannot express that, so this verb composes the same
    retry/slot primitives for a bot-side message-id edit. Content is a
    ``Message`` or a pre-formatted string whose ``raw`` format is declared
    (never guessed), exactly like ``send``/``say``.
    """
    if keyboard is _UNSET:
        markup = content.keyboard if isinstance(content, Message) else None
    else:
        markup = keyboard
    if backend is Backend.RICH:
        if raw is not None:
            if isinstance(content, Message):
                raise TypeError("raw= is for pre-formatted strings; pass a Message without raw=")
            rich_text = str(content)
            mdv2_text = str(content)
            return await telegram_rich.edit_rich_message(
                bot, chat_id, message_id, rich_text, mdv2_text, keyboard=markup
            )
        rich_text = content.render(Backend.RICH) if isinstance(content, Message) else str(content)
        try:
            mdv2_text = content.render(Backend.MDV2) if isinstance(content, Message) else str(content)
        except TypeError:
            mdv2_text = escape_mdv2(content.render(Backend.PLAIN)) if isinstance(content, Message) else str(content)
        return await telegram_rich.edit_rich_message(
            bot, chat_id, message_id, rich_text, mdv2_text, keyboard=markup
        )
    text, parse_mode = _resolve_content(content, raw, backend)
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if markup is not None:
        kwargs["reply_markup"] = markup
    return await _edit_message_with_retry(bot, chat_id, message_id, text, **kwargs)


async def edit_markup(
    chat_id: int,
    message_id: int,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    bot,
    **kwargs,
):
    """Edit only the reply markup of an existing message (no text change),
    routing through the shared retry/slot seam.

    RT-B2: covers the handler ``edit_message_reply_markup`` bypass sites (card
    deactivation, SRS delete confirm / keyboard restore) that ``say`` cannot
    express because it only edits text.
    """
    return await _edit_markup_with_retry(bot, chat_id, message_id, reply_markup, **kwargs)
