from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import _user_presentation, _user_plan, PREMIUM_PLANS
from services import db
from services.srs_engine import generate_v3_session
from services.utils.helpers import _answer_callback_safely
from services.utils.formatting import format_card
from config.keyboards import study_session_keyboard

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
        "user_id": user_id,
    }

    await _send_session_card(
        update, context, session["nodes"][0], 0, len(session["nodes"]), row
    )


async def _handle_study_remember(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    word_id: str, index: str, total: str,
) -> None:
    node = _get_current_node(context)
    if node and node.source_id is not None:
        db.advance_word_review(int(word_id))
    await _advance_session(update, context, int(index), int(total))


async def _handle_study_again(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    word_id: str, index: str, total: str,
) -> None:
    node = _get_current_node(context)
    if node and node.source_id is not None:
        db.defer_word_review(int(word_id))
    await _advance_session(update, context, int(index), int(total))


async def _handle_study_next(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    index: str, total: str,
) -> None:
    await _advance_session(update, context, int(index), int(total))


def _get_current_node(context):
    session = context.user_data.get("study_session")
    if not session:
        return None
    idx = session.get("current_index", 0)
    nodes = session.get("nodes", [])
    if idx < len(nodes):
        return nodes[idx]
    return None


async def _advance_session(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    current_index: int, total: int,
) -> None:
    await _answer_callback_safely(update.callback_query)
    session = context.user_data.get("study_session")
    if not session:
        await update.callback_query.message.reply_text("جلسه‌ای فعال نیست.")
        return

    next_index = current_index + 1
    nodes = session["nodes"]

    if next_index >= len(nodes):
        context.user_data.pop("study_session", None)
        text = (
            "این آخرین کارت جلسه بود!\n"
            "امروز عالی بود. فردا منتظرت هستیم 🌟"
        )
        await update.callback_query.message.reply_text(text)
        return

    session["current_index"] = next_index
    row = db.get_user(session["user_id"])
    await _send_session_card(update, context, nodes[next_index], next_index, len(nodes), row)


async def _send_session_card(update, context, node, index: int, total: int, row) -> None:
    card_text = format_card(
        node.card_data,
        presentation=_user_presentation(row),
    )
    is_premium = _user_plan(row) in PREMIUM_PLANS
    keyboard = study_session_keyboard(
        node.source_id or 0,
        index,
        total,
        show_pronounce=is_premium,
    )
    target = (
        update.callback_query.message
        if update.callback_query
        else update.message
    )
    await target.reply_text(
        card_text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )
