"""Study session handler — pulls from session engine, renders cards in-place.

Handles the golden '📚 شروع مطالعه امروز' button callback.
Phase 1e implementation — FSRS-6 4-grade session flow.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field

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
from services.scheduling import (
    consume_session_slot,
    release_session_slot,
    _today_str,
)
from services.utils.formatting import (
    NEW_CARD_BADGE,
    _phonetic_lines,
    _saved_word_card,
    days_since_review,
    escape_mdv2,
    format_review_badge,
    format_srs_back_stage,
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
    graded_word_ids: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Persistence helpers — restart-safe session recovery (Bug 1)
# ---------------------------------------------------------------------------

def _state_to_json(state: SessionState) -> str:
    """Serialize a session state to a JSON string for the study_sessions row."""
    return json.dumps(
        {
            "nodes": [asdict(node) for node in state.nodes],
            "total_cards": state.total_cards,
            "tier3_context": state.tier3_context,
            "study_msg_id": state.study_msg_id,
            "plan": state.plan,
            "graded_word_ids": state.graded_word_ids,
        }
    )


def _state_from_json(raw: str) -> SessionState:
    """Rebuild a SessionState from its JSON serialization."""
    data = json.loads(raw)
    return SessionState(
        nodes=[SessionNode(**node) for node in data["nodes"]],
        total_cards=data["total_cards"],
        tier3_context=data["tier3_context"],
        study_msg_id=data["study_msg_id"],
        plan=data["plan"],
        graded_word_ids=data.get("graded_word_ids", []),
    )


def _persist_session(user_id: int, state: SessionState) -> None:
    """Persist the active session keyed by the user's app-day (Rule 1/2)."""
    db.save_study_session(user_id, _app_day_str(), _state_to_json(state))


def _clear_persisted_session(user_id: int) -> None:
    db.clear_study_session(user_id)


def _restore_persisted_session(user_id: int) -> SessionState | None:
    """Load a same-day persisted session after a restart, or None.

    Rule 2: a persisted session whose date is not today is discarded (the row
    is cleared) so the user starts a fresh session with normal quota flow.
    """
    row = db.load_study_session(user_id)
    if row is None:
        return None
    session_date, state_json = row
    if session_date != _app_day_str():
        _clear_persisted_session(user_id)
        return None
    try:
        state = _state_from_json(state_json)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.exception(
            "corrupt persisted study session user_id=%s", user_id
        )
        _clear_persisted_session(user_id)
        return None
    if not state.nodes:
        _clear_persisted_session(user_id)
        return None
    return state


def get_active_study_session(
    user_id: int, context: ContextTypes.DEFAULT_TYPE
) -> SessionState | None:
    """Resolve the active study session from memory, falling back to the
    DB-persisted same-day session after a restart. Stashes the restored session
    back into user_data so subsequent advances reuse it (R1/R3, Bug #401)."""
    state = context.user_data.get("current_session")
    if state is None:
        state = _restore_persisted_session(user_id)
        if state is not None:
            context.user_data["current_session"] = state
    return state


def _app_day_str() -> str:
    """Today's app-day string (shared with scheduling quota keys)."""
    return _today_str()


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
        await _resume_existing_session(update, context, existing, user_id)
        return

    # --- restart recovery: a same-day session persisted to the DB (Bug 1) ---
    restored = _restore_persisted_session(user_id)
    if restored is not None:
        context.user_data["current_session"] = restored
        await _resume_existing_session(update, context, restored, user_id)
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
        graded_word_ids=[],
    )
    context.user_data["current_session"] = state

    # --- render first card ---
    try:
        # Persist BEFORE rendering so a DB failure is surfaced before any card
        # reaches the screen (owner decision 2026-08-15). The first card has no
        # study_msg_id yet; the next advance persists the updated id. On failure
        # the row is cleared and the slot released.
        _persist_session(user_id, state)
        await _render_and_send_first_card(state, update, context)
    except Exception:
        logger.exception(
            "handle_study_start render failed user_id=%s", user_id
        )
        release_session_slot(user_id)
        context.user_data.pop("current_session", None)
        _clear_persisted_session(user_id)
        await _reply_or_answer(
            update,
            context,
            "خطا در آماده‌سازی جلسه — دوباره امتحان کن.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )


async def _resume_existing_session(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state: SessionState,
    user_id: int,
) -> None:
    """Re-render the active session's first card (in-memory or restored).

    Deactivates the previous card message (if still present), sends a fresh
    active card, and re-persists the session with the new message id.
    """
    await _reply_or_answer(
        update,
        context,
        "جلسه‌ی قبلی ادامه داده می‌شه.",
        intent=CallbackNoticeIntent.IMPORTANT_ERROR,
    )
    try:
        node = state.nodes[0]
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
        _persist_session(user_id, state)
    except Exception:
        logger.exception(
            "handle_study_start resume render failed user_id=%s", user_id
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


def session_progress_footer(state, user_id: int) -> str:
    """Progress footer for a session card — single source of truth shared by
    the study render and the reveal/back-stage render (Kilo review #3)."""
    remaining = len(state.nodes)
    n = state.total_cards - remaining + 1
    m = state.total_cards
    return (
        f"نشست {to_persian_digits(_session_number(user_id))}"
        f" | کارت {to_persian_digits(n)} از {to_persian_digits(m)}"
    )


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
    progress = session_progress_footer(state, user_id)

    # keyboard + text by activity type
    if node.activity_type == "first_exposure":
        return _render_first_exposure(
            word_id, card_data, phonetic_lines, progress, user_id, user_data,
        )

    # srs_review: mode-aware render.
    if db.resolve_card_mode(user_id, "review") == "immediate":
        # Immediate: full card + review grade grid directly (no front/reveal,
        # no prompt stash) — CARD-MODES Rule 2.
        toggles = db.get_display_toggles(user_id)
        keyboard = get_review_keyboard(
            user_id, word_id, show_pronounce=db.should_show_pronounce(user_id),
        )
        text = format_srs_back_stage(
            card_data,
            toggles=toggles,
            phonetic_lines=phonetic_lines,
            footer=progress,
        )
        return text, keyboard

    # Staged (default): hidden front stage + reveal action.
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


def _render_first_exposure(
    word_id: int,
    card_data: dict,
    phonetic_lines: list[str],
    progress: str,
    user_id: int,
    user_data: dict | None,
) -> tuple[str, object]:
    """Render a first-exposure card per the resolved card mode (CARD-MODES T2).

    ``staged`` (default, Rule 1): hidden front stage via the shared randomized
    prompt engine + «کارت جدید ✨» badge + reveal action, stashing the prompt
    telemetry keys just like the review front stage.
    ``immediate``: full card + badge + the FE grade grid directly (owner lock
    2026-08-15: the badge stays visible in immediate mode).
    """
    if db.resolve_card_mode(user_id, "first_exposure") == "staged":
        toggles = db.get_display_toggles(user_id)
        prompt_type = select_srs_prompt_type(card_data, toggles)
        if user_data is not None:
            user_data.pop(f"revealed_{word_id}", None)
            user_data[f"prompt_type_{word_id}"] = prompt_type
            user_data[f"card_shown_at_{word_id}"] = time.time()
        keyboard = get_srs_front_keyboard(user_id, word_id)
        text = format_srs_front_stage(
            card_data,
            prompt_type,
            toggles=toggles,
            phonetic_lines=phonetic_lines,
            badge=NEW_CARD_BADGE,
            footer=progress,
        )
        return text, keyboard

    keyboard = get_first_exposure_keyboard(user_id, word_id)
    toggles = db.get_display_toggles(user_id)
    text = format_srs_back_stage(
        card_data,
        toggles=toggles,
        phonetic_lines=phonetic_lines,
        badge=NEW_CARD_BADGE,
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
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    state: SessionState | None = context.user_data.get("current_session")
    if state is None:
        # Restart recovery: a same-day session may still be persisted in the DB
        # even though the in-memory session was lost (Bug #401 / R1).
        state = _restore_persisted_session(user_id)
        if state is not None:
            context.user_data["current_session"] = state
        else:
            return

    try:
        # pop next node
        if state.nodes:
            state.nodes.pop(0)

        # try next node
        if state.nodes:
            node = state.nodes[0]
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
            _persist_session(user_id, state)
            return

        # Tiers 1+2 exhausted — attempt Tier 3 (Decision 26: stub returns None).
        # Only when tier3_context is populated (i.e. there were remaining slots);
        # otherwise the session is simply complete.
        if state.tier3_context:
            tier3_node = generate_tier3_node(**state.tier3_context)
            if tier3_node is not None:
                state.nodes.append(tier3_node)
                state.total_cards += 1
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
                _persist_session(user_id, state)
                return

        # session complete — clear the persisted row BEFORE sending the
        # completion message so a crash/timeout in this window can't leave a
        # re-gradable last node behind (owner decision 2026-08-15).
        context.user_data.pop("current_session", None)
        _clear_persisted_session(user_id)
        completion = escape_mdv2("جلسه مطالعه تموم شد! 🎉")
        await context.bot.edit_message_text(
            text=f"*{completion}*",
            chat_id=chat_id,
            message_id=state.study_msg_id,
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    except Exception:
        logger.exception("advance_session failed user_id=%s chat_id=%s", user_id, chat_id)
        try:
            error_msg = escape_mdv2("خطا در بارگذاری کارت بعدی — لطفاً جلسه‌ی مطالعه را دوباره شروع کنید")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"*{error_msg}*",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            logger.exception("advance_session error fallback also failed")
