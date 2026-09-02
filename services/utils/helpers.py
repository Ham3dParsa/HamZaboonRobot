import asyncio
import io
import logging
import math
import os
import re

from telegram import InputFile, Update
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
    await _clear_awaiting_prompt(context)
    context.user_data.pop("awaiting", None)
    user_id = update.effective_user.id
    reply_markup = main_menu(user_id == OWNER_ID)
    if via_callback:
        try:
            await update.callback_query.edit_message_text("لغو شد.")
        except BadRequest as exc:
            cb_data = getattr(getattr(update, "callback_query", None), "data", None)
            chat_id = getattr(getattr(update, "effective_chat", None), "id", None)
            logger.info("cancel callback edit failed user_id=%s chat_id=%s callback_data=%r: %s", user_id, chat_id, cb_data, exc, exc_info=True)
            await notify_callback(update.callback_query)
            await update.callback_query.message.reply_text("لغو شد.", reply_markup=reply_markup)
            return
        cb_data = getattr(getattr(update, "callback_query", None), "data", None)
        chat_id = getattr(getattr(update, "effective_chat", None), "id", None)
        logger.debug("cancel callback succeeded user_id=%s chat_id=%s callback_data=%r via_callback=%s", user_id, chat_id, cb_data, via_callback)
        await notify_callback(
            update.callback_query,
            "لغو شد.",
            intent=CallbackNoticeIntent.INFO,
        )
        return
    chat_id = getattr(getattr(update, "effective_chat", None), "id", None)
    logger.debug("cancel via message user_id=%s chat_id=%s via_callback=%s", user_id, chat_id, via_callback)
    await update.message.reply_text("لغو شد.", reply_markup=reply_markup)


async def exit_admin_awaiting_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin text-cancel path: clear all pending admin state and return to panel."""
    clear_admin_pending_state(context)
    await _clear_awaiting_prompt(context)
    # Lazy import to avoid circular dependency with config.keyboards
    from config.keyboards import admin_panel_keyboard

    await _edit_or_send(update, context, "لغو شد.", reply_markup=admin_panel_keyboard())


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


async def _send_media_with_retry(
    bot,
    chat_id: int,
    *,
    method: str,
    media_kw: str | None = None,
    media=None,
    filename: str | None = None,
    reset_telegram_cb: bool = True,
    idempotent: bool = False,
    **kwargs,
):
    """Single retry core for all Telegram sends (R1).

    ``idempotent`` controls whether TimedOut/NetworkError is retried.
    For sends (non-idempotent) these are never retried — the message may
    already be delivered and a retry would duplicate. Clamped RetryAfter
    (30s) is the only retried error for sends. ``_telegram_slots`` is the
    shared concurrency limiter; long-term it should move to services/telegram
    (documented here, move deferred to keep this phase low-risk).
    """
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
                    _reset_telegram_cb()
                return result
        except Forbidden:
            if chat_id > 0:
                db.set_user_blocked(chat_id)
            raise
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), _RETRY_BACKOFF_SLEEP_MAX))
        except (TimedOut, NetworkError):
            if not idempotent:
                raise
            if attempt == 2:
                raise
            await asyncio.sleep(_retry_sleep(attempt))


async def _send_with_retry(
    bot,
    chat_id: int,
    text: str,
    *,
    reset_telegram_cb: bool = True,
    **kwargs,
):
    return await _send_media_with_retry(
        bot, chat_id, method="send_message", media_kw=None, media=text, reset_telegram_cb=reset_telegram_cb, idempotent=False, **kwargs
    )


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
            if chat_id > 0:
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
            if chat_id > 0:
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
    """Backward-compat wrapper — delegates to unified _send_media_with_retry."""
    # Parity: _voice_is_inputfile / InputFile(io.BytesIO(_voice_bytes) handled via _capture_media_bytes
    filename = kwargs.pop("filename", None)
    return await _send_media_with_retry(bot, chat_id, method="send_voice", media_kw="voice", media=voice, filename=filename, idempotent=False, **kwargs)


_ADMIN_PENDING_KEYS: tuple[str, ...] = (
    "pending_dm",
    "pending_plan",
    "pending_block",
    "pending_broadcast",
    "full_edit",
    "plan_full_edit",
    "preset_edits",
)

_AWAITING_PENDING_KEY = "_awaiting_pending"


def clear_admin_pending_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all admin pending state keys (single source for cancel/back cleanup)."""
    for _k in _ADMIN_PENDING_KEYS:
        context.user_data.pop(_k, None)
    context.user_data.pop(_AWAITING_PENDING_KEY, None)
    context.user_data.pop("awaiting", None)
    # _awaiting_msg is cleared by _clear_awaiting_prompt, not here


def _store_awaiting_msg(context: ContextTypes.DEFAULT_TYPE, update: Update, msg) -> None:
    """Store the prompt message id so its keyboard can be cleared on consume/cancel.

    Single source of truth — imported by handlers/admin.py and handlers/admin_users.py.

    Primary source is the Message returned by ``say``/``_edit_or_send`` (``msg``);
    ``update`` is only used as fallback for the edit-path where the helper returns
    ``True``/``None`` (the prompt is the edited message). In PTB
    ``effective_message`` and ``callback_query.message`` alias the same object, so
    we only read ``effective_message`` as fallback — never ``callback_query.message``
    directly — and we always prefer ``msg.message_id`` when ``msg`` carries one.
    """
    # Callback updates: effective_message aliases callback_query.message in PTB,
    # so say()/_edit_or_send returning None/True (edit not-modified) would write
    # the button message_id into _awaiting_msg and later _clear_awaiting_prompt
    # would strip the admin menu instead of the prompt. On callback updates with
    # no real Message (None/bool) we skip the store — awaiting text stays in
    # user_data["awaiting"] and will be cleared via clear_admin_pending_state.
    if (msg is None or isinstance(msg, bool)) and getattr(update, "callback_query", None) is not None:
        return
    try:
        mid = None
        cid = None
        if msg is not None and not isinstance(msg, bool):
            mid = getattr(msg, "message_id", None)
            chat = getattr(msg, "chat", None)
            if chat is not None:
                cid = getattr(chat, "id", None)
            # Some send helpers return int message_id directly
            if mid is None and isinstance(msg, int):
                mid = msg
        # Only fallback to effective_message (prompt-related), not callback_query.message
        if mid is None:
            try:
                em = getattr(update, "effective_message", None)
                if em is not None:
                    em_mid = getattr(em, "message_id", None)
                    if em_mid is not None:
                        mid = em_mid
                        if cid is None:
                            chat = getattr(em, "chat", None)
                            if chat is not None:
                                cid = getattr(chat, "id", None)
            except Exception:
                pass
        if cid is None and getattr(update, "effective_chat", None) is not None:
            try:
                cid = update.effective_chat.id  # type: ignore[union-attr]
            except Exception:
                pass
        if mid is None or cid is None:
            return
        context.user_data["_awaiting_msg"] = {"chat_id": cid, "message_id": mid}
    except Exception:
        pass


async def _clear_awaiting_prompt(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the stored awaiting prompt's keyboard, swallowing BadRequest.

    Single source of truth — imported by handlers/admin.py and handlers/admin_users.py.
    """
    data = context.user_data.pop("_awaiting_msg", None)
    if not data:
        return
    try:
        await _edit_markup_with_retry(context.bot, data["chat_id"], data["message_id"], None)
    except BadRequest:
        pass
    except Exception:
        logger.exception("Failed to clear awaiting prompt")


async def _send_document_with_retry(bot, chat_id: int, document, **kwargs):
    """Backward-compat wrapper — delegates to unified _send_media_with_retry."""
    filename = kwargs.pop("filename", None)
    return await _send_media_with_retry(bot, chat_id, method="send_document", media_kw="document", media=document, filename=filename, idempotent=False, **kwargs)
