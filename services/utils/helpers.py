import asyncio
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from config import OWNER_ID, TELEGRAM_MAX_CONCURRENCY, USER_ACTIVITY
from config.keyboards import main_menu, awaiting_inline_keyboard, BTN_CANCEL, BTN_BACK
from services import db

logger = logging.getLogger(__name__)


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
    cost_usd: float | None = None,
) -> str | None:
    """Build a USER_ACTIVITY log line if the feature is enabled; return None otherwise."""
    if db.get_setting("user_activity_log", "off") != "on":
        return None
    uname = f"@{username}" if username else "—"
    cost_str = f"${cost_usd:.6f}" if cost_usd is not None and cost_usd > 0 else "—"
    line1 = f"{action:<18s} │ {str(user_id):<12s} │ {uname:<18s} │ {full_name or '—'}"
    line2 = (
        f"    ╰ plan={(plan or '—'):<8s}  lang={(lang or '—'):<6s}  "
        f"goal={(goal or '—'):<12s}  level={(level or '—'):<8s}  "
        f"outcome={outcome:<22s}  cost={cost_str}"
    )
    return line1 + "\n" + line2

_telegram_slots = asyncio.Semaphore(TELEGRAM_MAX_CONCURRENCY)
_CUSTOM_WORD_MAX_CHARS = 50
_CUSTOM_WORD_MAX_WORDS = 4
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
            await update.callback_query.answer("لغو شد.", show_alert=False)
            return
        except BadRequest:
            logger.info("cancel callback edit failed; sending new message")
            await update.callback_query.answer()
        await update.callback_query.message.reply_text("لغو شد.", reply_markup=reply_markup)
        return
    await update.message.reply_text("لغو شد.", reply_markup=reply_markup)


async def _edit_or_send(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    if update.callback_query:
        try:
            return await update.callback_query.edit_message_text(text, **kwargs)
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return await update.callback_query.answer()
            logger.info("callback edit failed; sending replacement message")
            return await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                **kwargs,
            )
    return await update.message.reply_text(text, **kwargs)


def _message_has_prepared_translations(update: Update) -> bool:
    message = update.callback_query.message
    return bool(message and "ترجمه‌ی مثال‌ها" in (message.text or ""))


async def _answer_callback_safely(query, *args, **kwargs) -> None:
    try:
        await query.answer(*args, **kwargs)
    except BadRequest as exc:
        message = str(exc).casefold()
        if "query is too old" in message or "query id is invalid" in message:
            logger.debug("skipped stale callback answer: %s", exc)
        else:
            raise
    except (TimedOut, NetworkError):
        logger.warning("callback answer failed due to network error")


def _reset_telegram_cb():
    import bot
    bot._telegram_offline = False
    bot._consecutive_health_failures = 0


async def _send_with_retry(
    bot,
    chat_id: int,
    text: str,
    **kwargs,
):
    for attempt in range(3):
        try:
            async with _telegram_slots:
                send_kwargs = {"chat_id": chat_id, "text": text, **kwargs}
                result = await bot.send_message(**send_kwargs)
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
            await asyncio.sleep(min(float(exc.retry_after), 30))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(2**attempt)


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
            await asyncio.sleep(min(float(exc.retry_after), 30))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(2**attempt)


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
            await asyncio.sleep(min(float(exc.retry_after), 30))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(2**attempt)


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
            await asyncio.sleep(min(float(exc.retry_after), 30))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(2**attempt)
