from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import _user_presentation, _user_plan
from services import db
from services.srs_engine import generate_v3_session
from services.utils.helpers import _answer_callback_safely
from services.utils.formatting import format_card

logger = logging.getLogger(__name__)


async def handle_study_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    row = db.get_user(user_id)

    if not row or not row["onboarded"]:
        msg = "ابتدا /start را بزنید."
        if update.callback_query:
            await _answer_callback_safely(update.callback_query, msg, show_alert=True)
        elif update.message:
            await update.message.reply_text(msg)
        return

    if update.callback_query:
        await _answer_callback_safely(update.callback_query)

    plan = _user_plan(row)
    session = await generate_v3_session(
        user_id=user_id,
        target_lang=row["target_lang"],
        goal=row["goal"],
        level=row["level"],
        plan=plan,
    )

    if not session["nodes"]:
        text = (
            "شما امروز تمام تمرین‌هایتان را انجام داده‌اید!\n"
            "فردا منتظرتان هستیم 🌟"
        )
        if update.callback_query:
            await update.callback_query.message.reply_text(text)
        elif update.message:
            await update.message.reply_text(text)
        return

    context.user_data["study_session"] = {
        "nodes": session["nodes"],
        "current_index": 0,
    }

    await _send_session_card(
        update, context, session["nodes"][0], 0, len(session["nodes"]), row
    )


async def _send_session_card(update, context, node, index: int, total: int, row) -> None:
    card_text = format_card(
        node.card_data,
        presentation=_user_presentation(row),
    )
    target = (
        update.callback_query.message
        if update.callback_query
        else update.message
    )
    await target.reply_text(
        card_text,
        parse_mode=ParseMode.MARKDOWN_V2,
    )
