import asyncio
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from config import OWNER_ID, TELEGRAM_MAX_CONCURRENCY
from keyboards import main_menu, awaiting_inline_keyboard, BTN_CANCEL, BTN_BACK

logger = logging.getLogger(__name__)

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
        except BadRequest:
            logger.info("cancel callback edit failed; continuing with menu message")
        await update.callback_query.message.reply_text("لغو شد.", reply_markup=reply_markup)
        await update.callback_query.answer("لغو شد.", show_alert=False)
        return
    await update.message.reply_text("لغو شد.", reply_markup=reply_markup)


async def _edit_or_send(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    try:
        return await update.callback_query.edit_message_text(text, **kwargs)
    except BadRequest:
        logger.info("callback edit failed; sending replacement message")
        return await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            **kwargs,
        )


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
                return await bot.send_message(**send_kwargs)
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
                return await query.edit_message_text(text, **kwargs)
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
                return await bot.delete_message(chat_id=chat_id, message_id=message_id, **kwargs)
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
                return await bot.send_voice(chat_id=chat_id, voice=voice, **kwargs)
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
