"""Rich Message delivery shim (R2/R3/R6) — the ONLY module touching the raw
Bot API 10.1 ``sendRichMessage`` / ``editMessageText(rich_message=...)`` call.

Official: https://core.telegram.org/bots/api#inputrichmessage
          https://core.telegram.org/bots/api#rich-message-formatting-options
PTB native (upcoming): https://github.com/python-telegram-bot/python-telegram-bot/pull/5263
  — InputRichMessage(html|markdown|blocks, is_rtl, skip_entity_detection, media)
    + Bot.send_rich_message / Bot.send_rich_message_draft

python-telegram-bot (22.8) does not natively support Rich Messages, so this
module uses PTB's forward-compatibility escape hatch ``bot.do_api_request``. It
is deliberately isolated so that when PTB v23 ships native
``bot.send_rich_message(...)`` the swap is a **one-function change here** —
``send_pretty`` and all callers stay untouched.

Shim payload (current): ``rich_message: {markdown, is_rtl, skip_entity_detection}``
NOT sent (tracked as Later in docs/research/rich-messages-shim.md):
  ``html``, ``blocks`` (Bot API 10.2 InputRichBlock*), ``media``, ``sendRichMessageDraft``.

Companion doc: docs/research/rich-messages-shim.md (Works / Partial / Later matrix + limits + 3-step migration).
Limits (official): 32768 chars, 500 blocks, 16 nesting levels, 50 media, 20 table columns.

Behavior:
- ``RICH_ENABLED`` (default ``False``) gates the whole path; off routes to MDV2.
- A capability latch disables Rich for a bot after a 404 (``EndPointNotFound``),
  so an old/local Bot API server is only probed once.
- Permanent errors fall back to MarkdownV2; transient errors (timeout/network)
  are NOT re-sent (the message may already be delivered — duplicate risk).
"""

from __future__ import annotations

import logging
from typing import Any

from telegram.constants import ParseMode
from telegram.error import BadRequest, EndPointNotFound, NetworkError, TimedOut

from services.utils.helpers import (
    _edit_message_with_retry,
    _rich_api_request,
    _send_with_retry,
)

logger = logging.getLogger(__name__)

# Feature flag — opt-in, default off (copy-as-plain-text / rollback safety).
RICH_ENABLED = False

# Bot instances (`id(bot)`) for which Rich Messages are known unsupported.
_rich_disabled: set[int] = set()


def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, (TimedOut, NetworkError))


def _fallback_hint(exc: Exception) -> str:
    """Human-readable reason for a Rich→MDV2 fallback, for logging."""
    msg = str(exc).lower()
    if "emoji" in msg or "premium" in msg:
        return (
            " custom emoji in the MESSAGE BODY needs the bot owner to hold "
            "Telegram Premium — using the 📖 fallback. (Inline-button custom "
            "emoji does NOT need Premium — see the emoji-buttons demo.)"
        )
    if "photo_url" in msg or "url" in msg:
        return " an invalid tg://emoji or photo URL was present in the rich text"
    if "entity" in msg:
        return " a span produced markup Telegram could not parse"
    return ""


async def _fallback_send(
    bot,
    chat_id: int,
    mdv2_markdown: str,
    *,
    keyboard=None,
    reply_parameters: dict[str, Any] | None = None,
) -> int:
    """Send the MarkdownV2 rendering instead of a Rich message."""
    kwargs: dict[str, Any] = {"parse_mode": ParseMode.MARKDOWN_V2}
    if keyboard is not None:
        kwargs["reply_markup"] = keyboard
    if reply_parameters is not None:
        kwargs["reply_parameters"] = reply_parameters
    result = await _send_with_retry(bot, chat_id, mdv2_markdown, **kwargs)
    return result.message_id if hasattr(result, "message_id") else result


async def send_rich_message(
    bot,
    chat_id: int,
    rich_markdown: str,
    mdv2_markdown: str,
    *,
    is_rtl: bool = False,
    skip_entity_detection: bool = False,
    keyboard=None,
    reply_parameters: dict[str, Any] | None = None,
) -> int:
    """Send ``rich_markdown`` via ``sendRichMessage``; fall back to MDV2.

    Returns the sent ``message_id``. ``mdv2_markdown`` is the same content
    rendered for ``Backend.MDV2`` and is used only on fallback.
    """
    if not RICH_ENABLED or id(bot) in _rich_disabled:
        return await _fallback_send(
            bot, chat_id, mdv2_markdown, keyboard=keyboard, reply_parameters=reply_parameters
        )

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "rich_message": {
            "markdown": rich_markdown,
            "is_rtl": is_rtl,
            "skip_entity_detection": skip_entity_detection,
        },
    }
    if keyboard is not None:
        payload["reply_markup"] = keyboard.to_dict()
    if reply_parameters is not None:
        payload["reply_parameters"] = reply_parameters

    try:
        result = await _rich_api_request(bot, "sendRichMessage", payload)
        if isinstance(result, dict):
            return result["message_id"]
        return getattr(result, "message_id", result)
    except EndPointNotFound:
        _rich_disabled.add(id(bot))
        logger.info("Rich Messages unsupported (404); disabled for this bot, falling back to MDV2")
        return await _fallback_send(
            bot, chat_id, mdv2_markdown, keyboard=keyboard, reply_parameters=reply_parameters
        )
    except BadRequest as exc:
        logger.info(
            "Rich send BadRequest; falling back to MDV2:%s — %s",
            _fallback_hint(exc),
            str(exc)[:200],
        )
        return await _fallback_send(
            bot, chat_id, mdv2_markdown, keyboard=keyboard, reply_parameters=reply_parameters
        )
    # Transient (TimedOut / NetworkError) intentionally propagates — no resend.


async def edit_rich_message(
    bot,
    chat_id: int,
    message_id: int,
    rich_markdown: str,
    mdv2_markdown: str,
    *,
    is_rtl: bool = False,
    keyboard=None,
) -> None:
    """Edit ``chat_id/message_id`` to ``rich_markdown`` via ``editMessageText``."""
    if not RICH_ENABLED or id(bot) in _rich_disabled:
        await _edit_message_with_retry(
            bot,
            chat_id,
            message_id,
            mdv2_markdown,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
        )
        return

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "rich_message": {"markdown": rich_markdown, "is_rtl": is_rtl},
    }
    try:
        await _rich_api_request(bot, "editMessageText", payload)
    except EndPointNotFound:
        _rich_disabled.add(id(bot))
        logger.info("Rich Messages unsupported (404); disabled for this bot, falling back to MDV2 edit")
        await _edit_message_with_retry(
            bot,
            chat_id,
            message_id,
            mdv2_markdown,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
        )
    except BadRequest as exc:
        logger.info(
            "Rich edit BadRequest; falling back to MDV2:%s — %s",
            _fallback_hint(exc),
            str(exc)[:200],
        )
        await _edit_message_with_retry(
            bot,
            chat_id,
            message_id,
            mdv2_markdown,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
        )
    # Transient errors propagate — no resend.
