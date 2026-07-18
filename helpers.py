import logging
import re

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from config import OWNER_ID
from keyboards import main_menu, awaiting_inline_keyboard, BTN_CANCEL, BTN_BACK

logger = logging.getLogger(__name__)

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


async def _finish_llm_wait_state(wait_message):
    if not wait_message:
        return
    try:
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
