"""Study session handler — pulls from session engine, renders cards in-place.

Handles the golden '📚 شروع مطالعه امروز' button callback.
Phase 1e implementation — FSRS-6 4-grade session flow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_BYPASS_LIMITS, PREMIUM_PLANS, is_owner
from config.keyboards import get_first_exposure_keyboard, get_review_keyboard
from services import db
from services.session import SessionNode, build_session_list, generate_tier3_node
from services.scheduling import consume_session_slot, release_session_slot
from services.utils.formatting import (
    _phonetic_lines,
    _saved_word_card,
    escape_mdv2,
    format_card,
    to_persian_digits,
)
from services.utils.helpers import _answer_callback_safely

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session state — stored in context.user_data['current_session']
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    nodes: list[SessionNode]
    total_cards: int
    tier3_context: dict
    study_msg_id: int | None
    plan: str


# ---------------------------------------------------------------------------
# Reply helper — works from both inline (callback_query) and text-menu entry
# ---------------------------------------------------------------------------

async def _reply_or_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    show_alert: bool = False,
) -> None:
    """Reply to a study-session message regardless of entry point.

    Inline button presses are acknowledged via the callback answer; text-menu
    presses have no callback_query, so they get a normal text reply instead.
    """
    if update.callback_query is not None:
        await _answer_callback_safely(
            update.callback_query,
            text,
            show_alert=show_alert,
        )
        return
    if update.message is not None:
        await update.message.reply_text(text)
        return
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def handle_study_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the '📚 شروع مطالعه امروز' golden button callback."""
    user_id = update.effective_user.id
    row = db.get_user(user_id)

    if not row or not row["onboarded"]:
        await _reply_or_answer(
            update,
            context,
            "ابتدا /start را بزنید.",
            show_alert=True,
        )
        return

    plan = row["plan"] or "free"

    # --- quota check (Decision 30: once at top, before build) ---
    if not is_owner(user_id) or not OWNER_BYPASS_LIMITS:
        if not consume_session_slot(user_id, plan):
            await _reply_or_answer(
                update,
                context,
                "همه کارت‌های امروز تموم شده! فردا دوباره بیا.",
                show_alert=True,
            )
            return

    # --- build session ---
    lang = row["target_lang"]
    goal = row["goal"]
    level = row["level"]
    nodes, tier3_context = build_session_list(
        user_id, lang, goal, level, plan,
    )

    # --- empty session: release slot (Decision 33) ---
    if not nodes:
        release_session_slot(user_id)
        await _reply_or_answer(
            update,
            context,
            "📚 جلسه‌ای برای امروز نداری. واژه‌های جدید اضافه کن!",
            show_alert=True,
        )
        return

    # --- create session state ---
    state = SessionState(
        nodes=nodes,
        total_cards=len(nodes),
        tier3_context=tier3_context,
        study_msg_id=None,
        plan=plan,
    )
    context.user_data["current_session"] = state

    # --- render first card ---
    try:
        await _render_and_send_first_card(state, update, context)
    except Exception:
        logger.exception(
            "handle_study_start render failed user_id=%s", user_id
        )
        release_session_slot(user_id)
        context.user_data.pop("current_session", None)
        await _reply_or_answer(
            update,
            context,
            "خطا در آماده‌سازی جلسه — دوباره امتحان کن.",
            show_alert=True,
        )


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------

async def _render_and_send_first_card(
    state: SessionState,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Render and send the first card as a new message."""
    node = state.nodes[0]
    chat_id = update.effective_chat.id
    user_id = node.activity_meta.get("user_id", 0)
    text, keyboard = _build_card_text_and_keyboard(node, state, user_id)
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
    )
    state.study_msg_id = msg.message_id


def _build_card_text_and_keyboard(
    node: SessionNode,
    state: SessionState,
    user_id: int,
) -> tuple[str, object]:
    """Fetch card data, build formatted text + keyboard for a session node."""
    word_id = node.source_id or 0
    word_row = db.get_saved_word(word_id, user_id)
    card_data = _saved_word_card(word_row) if word_row else {}
    card_data.setdefault("word", node.card_data.get("word", ""))

    # keyboard from activity type
    if node.activity_type == "first_exposure":
        keyboard = get_first_exposure_keyboard(user_id, word_id)
    else:
        show_pronounce = _show_pronounce(user_id)
        keyboard = get_review_keyboard(user_id, word_id, show_pronounce=show_pronounce)

    # format text — full card content via the shared formatter
    phonetic_lines = _phonetic_lines(card_data.get("phonetic", ""))
    remaining = len(state.nodes)
    n = state.total_cards - remaining + 1
    m = state.total_cards
    progress = (
        f"نشست {to_persian_digits(_session_number(user_id))}"
        f" | کارت {to_persian_digits(n)} از {to_persian_digits(m)}"
    )
    text = format_card(
        card_data,
        footer=progress,
        phonetic_lines=phonetic_lines,
    )

    return text, keyboard


def _show_pronounce(user_id: int) -> bool:
    row = db.get_user(user_id)
    if not row:
        return False
    plan = row["plan"] or "free"
    tts_setting = db.get_setting("tts_access", "premium")
    if tts_setting == "none":
        return False
    if plan in PREMIUM_PLANS:
        return True
    return tts_setting == "all"


def _session_number(user_id: int) -> int:
    """Current session number today (1-based)."""
    from services.scheduling import _get_used
    return _get_used(user_id)


# ---------------------------------------------------------------------------
# Auto-advance — called from grade handlers after grading
# ---------------------------------------------------------------------------

async def advance_session(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Pop next node from session, render in-place, or show completion.

    Called from _handle_srs_review and _handle_first_exposure_grade after
    grading is complete. Wraps all fallible work in try/except (Decision 32).
    """
    state: SessionState | None = context.user_data.get("current_session")
    if state is None:
        return

    chat_id = update.effective_chat.id

    try:
        # pop next node
        if state.nodes:
            state.nodes.pop(0)

        # try next node
        if state.nodes:
            node = state.nodes[0]
            user_id = node.activity_meta.get("user_id", 0)
            text, keyboard = _build_card_text_and_keyboard(node, state, user_id)
            await context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=state.study_msg_id,
                reply_markup=keyboard,
            )
            return

        # Tiers 1+2 exhausted — attempt Tier 3 (Decision 26: stub returns None)
        tier3_node = generate_tier3_node(**state.tier3_context)
        if tier3_node is not None:
            state.nodes.append(tier3_node)
            state.total_cards += 1
            user_id = tier3_node.activity_meta.get("user_id", 0)
            text, keyboard = _build_card_text_and_keyboard(
                tier3_node, state, user_id,
            )
            await context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=state.study_msg_id,
                reply_markup=keyboard,
            )
            return

        # session complete
        completion = escape_mdv2("جلسه مطالعه تموم شد! 🎉")
        await context.bot.edit_message_text(
            text=f"*{completion}*",
            chat_id=chat_id,
            message_id=state.study_msg_id,
        )
        context.user_data.pop("current_session", None)

    except Exception:
        logger.exception("advance_session failed user_id=%s chat_id=%s", user_id if state.nodes else "?", chat_id)
        try:
            error_msg = escape_mdv2("خطا در بارگذاری کارت بعدی — لطفاً /study را دوباره بزنید")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"*{error_msg}*",
            )
        except Exception:
            logger.exception("advance_session error fallback also failed")
