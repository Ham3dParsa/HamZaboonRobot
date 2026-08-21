import asyncio
import logging
import math
import os
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from config import OWNER_ID, TELEGRAM_MAX_CONCURRENCY, USER_ACTIVITY
from config.keyboards import main_menu, awaiting_inline_keyboard, BTN_CANCEL, BTN_BACK
from services import db
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback

logger = logging.getLogger(__name__)

_RETRY_BACKOFF_BASE_DEFAULT = 1.0
_RETRY_BACKOFF_BASE_MAX = 60.0
_RETRY_BACKOFF_SLEEP_MAX = 30.0


def _retry_backoff_base() -> float:
    """Scale factor for the Telegram retry backoff (2**attempt) wall-clock wait.

    Production default is 1.0 (unchanged). Tests may shrink the wait via
    HAMZABAN_RETRY_BACKOFF_BASE (0.1 in the suite; 0.05 reserved for explicit
    performance benchmarks) while still exercising the real retry sequence:
    attempt count, ordering, retry conditions, final failure and success-after-
    retry are all untouched — only the elapsed waiting time scales.

    Invalid, NaN, infinite or non-positive values are warned and fall back to
    1.0; values above 60 are clamped.
    """
    raw = os.environ.get("HAMZABAN_RETRY_BACKOFF_BASE")
    if raw is None:
        return _RETRY_BACKOFF_BASE_DEFAULT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid HAMZABAN_RETRY_BACKOFF_BASE=%r, using default 1.0", raw)
        return _RETRY_BACKOFF_BASE_DEFAULT
    if not math.isfinite(value) or value <= 0:
        logger.warning("Invalid HAMZABAN_RETRY_BACKOFF_BASE=%r, using default 1.0", raw)
        return _RETRY_BACKOFF_BASE_DEFAULT
    if value > _RETRY_BACKOFF_BASE_MAX:
        logger.warning(
            "HAMZABAN_RETRY_BACKOFF_BASE=%r exceeds max %.1f, clamping",
            raw,
            _RETRY_BACKOFF_BASE_MAX,
        )
        value = _RETRY_BACKOFF_BASE_MAX
    return value


def _retry_sleep(attempt: int) -> float:
    """Computed backoff sleep for *attempt*, capped to 30s."""
    return min(_retry_backoff_base() * (2**attempt), _RETRY_BACKOFF_SLEEP_MAX)


def apply_log_level(level_name: str) -> None:
    """Set root logger level and quieter external loggers accordingly."""
    level = getattr(logging, level_name.upper(), None)
    if level is None:
        return
    logging.getLogger().setLevel(level)
    for name in ("apscheduler", "httpcore", "httpx", "telegram"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))
    logger.info("log level set to %s", level_name.upper())


def _user_activity_line(
    *,
    user_id: int,
    full_name: str | None = None,
    username: str | None = None,
    action: str,
    outcome: str,
    plan: str | None = None,
    lang: str | None = None,
    goal: str | None = None,
    level: str | None = None,
) -> str | None:
    """Build a USER_ACTIVITY log line if the feature is enabled; return None otherwise."""
    if db.get_setting("user_activity_log", "off") != "on":
        return None
    uname = f"@{username}" if username else "—"
    return (
        f"{action:<18s} │ {str(user_id):<12s} │ {uname:<16s} │ "
        f"{(plan or '—'):<8s} │ {(lang or '—'):<6s} │ "
        f"{(goal or '—'):<12s} │ {(level or '—'):<8s} │ "
        f"{outcome:<22s} │ {full_name or '—'}"
    )

_telegram_slots = asyncio.Semaphore(TELEGRAM_MAX_CONCURRENCY)


async def _rich_api_request(bot, method: str, payload: dict[str, object]):
    """Slot-protected raw Bot API call for Rich Messages (keeps slot ownership in helpers).

    Centralizes ``_telegram_slots`` so ``services/telegram_rich.py`` does not
    directly reference the slot (wiring guard allows only helpers + send_pretty).
    """
    async with _telegram_slots:
        return await bot.do_api_request(method, api_kwargs=payload, return_type=None)
_CANCEL_INPUTS = {
    "cancel",
    "back",
    "لغو",
    "بازگشت",
    "انصراف",
    BTN_CANCEL.casefold(),
    BTN_BACK.casefold(),
}


def _normalize_custom_word_input(text: str) -> str:
    text = re.sub(r'[\s\u200c\u200b]+', ' ', text.strip())
    text = re.sub(r' +', ' ', text)
    return text.strip()


def _is_cancel_input(text: str) -> bool:
    return _normalize_custom_word_input(text).casefold() in _CANCEL_INPUTS


async def _start_llm_wait_state(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    chat = update.effective_chat
    if not chat:
        return None
    await chat.send_action("typing")
    try:
        return await context.bot.send_message(chat_id=chat.id, text=text)
    except Exception:
        logger.exception("Failed to send LLM wait-state message")
        return None


async def _finish_llm_wait_state(wait_message, bot=None):
    if not wait_message:
        return
    try:
        if bot is not None:
            await _delete_with_retry(bot, wait_message.chat_id, wait_message.message_id)
        else:
            await wait_message.delete()
    except Exception:
        logger.exception("Failed to delete LLM wait-state message")


async def _exit_awaiting_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, *, via_callback: bool = False):
    context.user_data.pop("awaiting", None)
    user_id = update.effective_user.id
    reply_markup = main_menu(user_id == OWNER_ID)
    if via_callback:
        try:
            await update.callback_query.edit_message_text("لغو شد.")
        except BadRequest:
            logger.info("cancel callback edit failed; sending new message")
            await notify_callback(update.callback_query)
            await update.callback_query.message.reply_text("لغو شد.", reply_markup=reply_markup)
            return
        await notify_callback(
            update.callback_query,
            "لغو شد.",
            intent=CallbackNoticeIntent.INFO,
        )
        return
    await update.message.reply_text("لغو شد.", reply_markup=reply_markup)


async def _edit_or_send(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Thin adapter (R3) routing through ``services.send_pretty.say``.

    The deep outbound module owns the parse-standard, retry, and concurrency
    slots. This adapter keeps the legacy ``(update, context, text, **kwargs)``
    signature so the existing call sites are untouched, and derives the ``raw``
    format from the caller's ``parse_mode`` (never guessed). Deletion of this
    adapter (and migration of all callers to ``say``) is deferred to a dedicated
    cleanup PR.
    """
    from services.send_pretty import RawFormat, say

    raw = RawFormat.PLAIN
    parse_mode = kwargs.pop("parse_mode", None)
    if parse_mode == ParseMode.HTML:
        raw = RawFormat.HTML
    elif parse_mode == ParseMode.MARKDOWN_V2:
        raw = RawFormat.MDV2
    return await say(update, context, text, raw=raw, **kwargs)


def _reset_telegram_cb():
    import bot
    bot._telegram_offline = False
    bot._consecutive_health_failures = 0


async def _send_with_retry(
    bot,
    chat_id: int,
    text: str,
    *,
    reset_telegram_cb: bool = True,
    **kwargs,
):
    for attempt in range(3):
        try:
            async with _telegram_slots:
                send_kwargs = {"chat_id": chat_id, "text": text, **kwargs}
                result = await bot.send_message(**send_kwargs)
                if reset_telegram_cb:
                    _reset_telegram_cb()
                return result
        except Forbidden:
            db.set_user_blocked(chat_id)
            raise
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            # Sending creates a NEW message each call, so a timeout/network
            # error is ambiguous (the message may already be delivered).
            # Re-sending would produce a duplicate, so never retry sends.
            raise


async def _edit_with_retry(query, text, **kwargs):
    for attempt in range(3):
        try:
            async with _telegram_slots:
                result = await query.edit_message_text(text, **kwargs)
                _reset_telegram_cb()
                return result
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(_retry_sleep(attempt))


async def _edit_message_with_retry(
    bot, chat_id: int, message_id: int, text: str, **kwargs
):
    """Edit an existing message by id, holding the shared concurrency slot.

    RT-B2: routes the handler ``context.bot.edit_message_text`` bypass sites
    (which target a stored ``message_id`` rather than the callback message)
    back onto the retry/slot seam.
    """
    for attempt in range(3):
        try:
            async with _telegram_slots:
                result = await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text, **kwargs
                )
                _reset_telegram_cb()
                return result
        except Forbidden:
            db.set_user_blocked(chat_id)
            raise
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(_retry_sleep(attempt))


async def _edit_markup_with_retry(
    bot, chat_id: int, message_id: int, reply_markup, **kwargs
):
    """Edit only the reply markup of an existing message (no text change),
    holding the shared concurrency slot.

    RT-B2: routes the handler ``context.bot.edit_message_reply_markup`` bypass
    sites back onto the retry/slot seam.
    """
    for attempt in range(3):
        try:
            async with _telegram_slots:
                result = await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                    **kwargs,
                )
                _reset_telegram_cb()
                return result
        except Forbidden:
            db.set_user_blocked(chat_id)
            raise
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(_retry_sleep(attempt))


async def _delete_with_retry(bot, chat_id: int, message_id: int, **kwargs):
    for attempt in range(3):
        try:
            async with _telegram_slots:
                result = await bot.delete_message(chat_id=chat_id, message_id=message_id, **kwargs)
                _reset_telegram_cb()
                return result
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(_retry_sleep(attempt))


async def _send_voice_with_retry(bot, chat_id: int, voice, **kwargs):
    for attempt in range(3):
        try:
            async with _telegram_slots:
                result = await bot.send_voice(chat_id=chat_id, voice=voice, **kwargs)
                _reset_telegram_cb()
                return result
        except Forbidden:
            db.set_user_blocked(chat_id)
            raise
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            # Sending creates a NEW message each call; a timeout/network error
            # is ambiguous (may already be delivered). Never re-send a voice.
            raise
