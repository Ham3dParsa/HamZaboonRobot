"""Study session handler — pulls from session engine, renders cards in-place.

Handles the golden '📚 شروع مطالعه امروز' button callback.
Phase 1e implementation — FSRS-6 4-grade session flow.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from config import (
    OWNER_BYPASS_LIMITS,
    cards_per_session_for_plan,
    is_owner,
)
from config.keyboards import (
    get_first_exposure_keyboard,
    get_review_keyboard,
    get_srs_front_keyboard,
    study_inactive_keyboard,
)
from services import db
from services.session import SessionNode, build_session_list, generate_tier3_node
from services.scheduling import consume_session_slot, release_session_slot
from services.utils.formatting import (
    NEW_CARD_BADGE,
    _phonetic_lines,
    _saved_word_card,
    days_since_review,
    escape_mdv2,
    format_card,
    format_review_badge,
    format_srs_front_stage,
    select_srs_prompt_type,
    to_persian_digits,
)
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback

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
    intent: CallbackNoticeIntent = CallbackNoticeIntent.INFO,
) -> None:
    """Reply to a study-session message regardless of entry point.

    Inline button presses are acknowledged via the callback answer; text-menu
    presses have no callback_query, so they get a normal text reply instead.
    """
    if update.callback_query is not None:
        await notify_callback(
            update.callback_query,
            text,
            intent=intent,
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
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return

    plan = row["plan"] or "free"

    # --- resume existing session (Decision 30: don't double-count slots) ---
    existing = context.user_data.get("current_session")
    if existing is not None and existing.nodes:
        await _reply_or_answer(
            update,
            context,
            "جلسه‌ی قبلی ادامه داده می‌شه.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        state = existing
        try:
            node = state.nodes[0]
            user_id = node.activity_meta.get("user_id", 0)
            text, keyboard = _build_card_text_and_keyboard(
                node, state, user_id, user_data=context.user_data,
            )

            # Deactivate the previous card message (if it still exists) so its
            # grade buttons are replaced by a single "not active" button. If
            # the message was already deleted/lost, this fails harmlessly.
            if state.study_msg_id:
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=update.effective_chat.id,
                        message_id=state.study_msg_id,
                        reply_markup=study_inactive_keyboard(),
                    )
                except BadRequest:
                    # Stale message already gone — nothing to inactivate.
                    logger.info(
                        "resume: prior study message gone; sending fresh card user_id=%s",
                        user_id,
                    )
                except Exception:
                    logger.exception(
                        "handle_study_start inactivate-old-card failed user_id=%s",
                        user_id,
                    )

            # Always send a fresh, active card so the user can continue even if
            # the original card message was deleted or lost.
            msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            state.study_msg_id = msg.message_id
        except Exception:
            logger.exception(
                "handle_study_start resume render failed user_id=%s", user_id
            )
        return

    # --- quota check (Decision 30: once at top, before build) ---
    if not is_owner(user_id) or not OWNER_BYPASS_LIMITS:
        if not consume_session_slot(user_id, plan):
            await _reply_or_answer(
                update,
                context,
                "همه کارت‌های امروز تموم شده! فردا دوباره بیا.",
                intent=CallbackNoticeIntent.IMPORTANT_ERROR,
            )
            return

    # --- build session ---
    lang = row["target_lang"]
    goal = row["goal"]
    level = row["level"]
    max_nodes = cards_per_session_for_plan(plan)
    nodes, tier3_context = build_session_list(
        user_id, lang, goal, level, plan,
        max_nodes=max_nodes,
    )

    # --- empty session: release slot (Decision 33) ---
    if not nodes:
        release_session_slot(user_id)
        await _reply_or_answer(
            update,
            context,
            "📚 جلسه‌ای برای امروز نداری. واژه‌های جدید اضافه کن!",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
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
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
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
    text, keyboard = _build_card_text_and_keyboard(
        node, state, user_id, user_data=context.user_data,
    )
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    state.study_msg_id = msg.message_id


def _build_card_text_and_keyboard(
    node: SessionNode,
    state: SessionState,
    user_id: int,
    user_data: dict | None = None,
) -> tuple[str, object]:
    """Fetch card data, build formatted text + keyboard for a session node.

    ``user_data`` is the per-user context dict; when provided the render stashes
    the chosen prompt type and the front-stage shown-at timestamp so the Phase 3
    telemetry layer can record them at grade time (#338 R8/R12).
    """
    word_id = node.source_id or 0
    word_row = db.get_saved_word(word_id, user_id)
    card_data = _saved_word_card(word_row) if word_row else {}
    card_data.setdefault("word", node.card_data.get("word", ""))

    phonetic_lines = _phonetic_lines(card_data.get("phonetic", ""))
    remaining = len(state.nodes)
    n = state.total_cards - remaining + 1
    m = state.total_cards
    progress = (
        f"نشست {to_persian_digits(_session_number(user_id))}"
        f" | کارت {to_persian_digits(n)} از {to_persian_digits(m)}"
    )

    # keyboard + text by activity type
    if node.activity_type == "first_exposure":
        # Full card immediately, with the new-card badge (R5). No staging.
        keyboard = get_first_exposure_keyboard(user_id, word_id)
        text = format_card(
            card_data,
            footer=progress,
            phonetic_lines=phonetic_lines,
            badge=NEW_CARD_BADGE,
        )
        return text, keyboard

    # srs_review: staged reveal — hidden front stage + reveal action.
    toggles = db.get_display_toggles(user_id)
    prompt_type = select_srs_prompt_type(card_data, toggles)
    if user_data is not None:
        # Re-arm the reveal action: a fresh front-stage presentation (new
        # session, resume, or a repeated word) must accept reveal again even if
        # this word was revealed in an earlier presentation (#338 §2B idempotency).
        user_data.pop(f"revealed_{word_id}", None)
        user_data[f"prompt_type_{word_id}"] = prompt_type
        user_data[f"card_shown_at_{word_id}"] = time.time()
    days = days_since_review(
        word_row["last_review_at"] if word_row is not None else None
    )
    badge = format_review_badge(days) if days is not None else ""
    show_pronounce = db.should_show_pronounce(user_id)
    keyboard = get_srs_front_keyboard(user_id, word_id)
    text = format_srs_front_stage(
        card_data,
        prompt_type,
        toggles=toggles,
        phonetic_lines=phonetic_lines,
        badge=badge,
        footer=progress,
    )
    return text, keyboard


def _session_number(user_id: int) -> int:
    """Current session number today (1-based)."""
    from services.scheduling import _get_used
    return _get_used(user_id)


async def handle_study_inactive(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle a stale study-card "not active" button press.

    Informs the learner that this card is superseded by a newer session card,
    then deletes the stale message so its now-broken buttons disappear.
    """
    note = (
        "این پیام غیرفعال شده، لطفاً از آخرین پیام جلسه استفاده کن یا "
        "دکمهٔ «شروع مطالعه امروز» را بزن."
    )
    await notify_callback(
        update.callback_query,
        note,
        intent=CallbackNoticeIntent.IMPORTANT_ERROR,
    )

    try:
        if update.callback_query is not None and update.callback_query.message is not None:
            await update.callback_query.message.delete()
    except BadRequest:
        # Already deleted by the user.
        pass
    except Exception:
        logger.exception("handle_study_inactive delete failed")


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
            text, keyboard = _build_card_text_and_keyboard(
                node, state, user_id, user_data=context.user_data,
            )
            await context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=state.study_msg_id,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        # Tiers 1+2 exhausted — attempt Tier 3 (Decision 26: stub returns None).
        # Only when tier3_context is populated (i.e. there were remaining slots);
        # otherwise the session is simply complete.
        if state.tier3_context:
            tier3_node = generate_tier3_node(**state.tier3_context)
            if tier3_node is not None:
                state.nodes.append(tier3_node)
                state.total_cards += 1
                user_id = tier3_node.activity_meta.get("user_id", 0)
                text, keyboard = _build_card_text_and_keyboard(
                    tier3_node, state, user_id, user_data=context.user_data,
                )
                await context.bot.edit_message_text(
                    text=text,
                    chat_id=chat_id,
                    message_id=state.study_msg_id,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                return

        # session complete
        completion = escape_mdv2("جلسه مطالعه تموم شد! 🎉")
        await context.bot.edit_message_text(
            text=f"*{completion}*",
            chat_id=chat_id,
            message_id=state.study_msg_id,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        context.user_data.pop("current_session", None)

    except Exception:
        logger.exception("advance_session failed user_id=%s chat_id=%s", user_id if state.nodes else "?", chat_id)
        try:
            error_msg = escape_mdv2("خطا در بارگذاری کارت بعدی — لطفاً جلسه‌ی مطالعه را دوباره شروع کنید")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"*{error_msg}*",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            logger.exception("advance_session error fallback also failed")
