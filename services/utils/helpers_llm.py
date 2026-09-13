"""LLM-wait-state helpers leaf of the utils seam (REF2-T3, third).

Verbatim home of the LLM wait-state + awaiting-exit + ``say`` adapter split
out of ``services/utils/helpers.py``: :func:`_start_llm_wait_state`,
:func:`_finish_llm_wait_state`, :func:`_exit_awaiting_flow`,
:func:`exit_admin_awaiting_cancel` and :func:`_edit_or_send`.
``helpers.py`` keeps a re-export shim so every existing
``from services.utils.helpers import ...`` caller works unchanged.

No sibling-leaf imports at top level. Cross-leaf calls
(``_clear_awaiting_prompt``, ``clear_admin_pending_state``,
``_delete_with_retry``) and the notification call (``notify_callback`` /
``CallbackNoticeIntent``) resolve dynamically through the ``helpers``
facade at call time — tests patch ``services.utils.helpers.notify_callback``
and must observe it (send_pretty precedent). ``send_pretty``/``bot``
imports stay function-local (live cycle — never top-level).
"""

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from config import OWNER_ID
from config.keyboards import main_menu

logger = logging.getLogger(__name__)


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
            # Facade-dynamic (send_pretty precedent): the retry loop lives in
            # the retry leaf; resolve through the facade like any caller.
            from services.utils import helpers as _helpers_facade

            await _helpers_facade._delete_with_retry(bot, wait_message.chat_id, wait_message.message_id)
        else:
            await wait_message.delete()
    except Exception:
        logger.exception("Failed to delete LLM wait-state message")


async def _exit_awaiting_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, *, via_callback: bool = False):
    # Facade-dynamic (send_pretty precedent): awaiting + notification calls
    # resolve through the facade so facade-path patches observe them.
    from services.utils import helpers as _helpers_facade

    await _helpers_facade._clear_awaiting_prompt(context)
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
            await _helpers_facade.notify_callback(update.callback_query)
            await update.callback_query.message.reply_text("لغو شد.", reply_markup=reply_markup)
            return
        cb_data = getattr(getattr(update, "callback_query", None), "data", None)
        chat_id = getattr(getattr(update, "effective_chat", None), "id", None)
        logger.debug("cancel callback succeeded user_id=%s chat_id=%s callback_data=%r via_callback=%s", user_id, chat_id, cb_data, via_callback)
        await _helpers_facade.notify_callback(
            update.callback_query,
            "لغو شد.",
            intent=_helpers_facade.CallbackNoticeIntent.INFO,
        )
        return
    chat_id = getattr(getattr(update, "effective_chat", None), "id", None)
    logger.debug("cancel via message user_id=%s chat_id=%s via_callback=%s", user_id, chat_id, via_callback)
    await update.message.reply_text("لغو شد.", reply_markup=reply_markup)


async def exit_admin_awaiting_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin text-cancel path: clear all pending admin state and return to panel."""
    # Facade-dynamic (send_pretty precedent): awaiting calls resolve through
    # the facade so facade-path patches observe them.
    from services.utils import helpers as _helpers_facade

    _helpers_facade.clear_admin_pending_state(context)
    await _helpers_facade._clear_awaiting_prompt(context)
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
