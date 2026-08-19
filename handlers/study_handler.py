"""Study session handler — pulls from session engine, renders cards in-place.

Handles the golden '📚 شروع مطالعه امروز' button callback.
Phase 1e implementation — FSRS-6 4-grade session flow.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from config import (
    APP_TZ,
    OWNER_BYPASS_LIMITS,
    cards_per_session_for_plan,
    is_owner,
)
from config.keyboards import (
    get_first_exposure_keyboard,
    get_review_keyboard,
    get_srs_front_keyboard,
    session_summary_detail_keyboard,
    session_summary_keyboard,
    session_summary_legend_keyboard,
    study_inactive_keyboard,
)
from config.plan_identity import has_feature
from services import db, send_pretty
from services.session import SessionNode, build_session_list, generate_tier3_node
from services.session.summary import WordReviewRecord, build_report
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
    format_session_detail_page,
    format_session_summary,
    format_summary_legend,
    format_srs_back_stage,
    format_srs_front_stage,
    select_srs_prompt_type,
    to_persian_digits,
)
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.routing import register

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
    # Pre-grade stability per word_id, captured on first render so the
    # session summary can show the before->after stability delta (Phase 2).
    before_stability: dict[int, float] = field(default_factory=dict)


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
            "before_stability": state.before_stability,
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
        graded_word_ids=data.get("graded_word_ids") or [],
        before_stability={
            int(k): float(v)
            for k, v in (data.get("before_stability") or {}).items()
        },
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
    await send_pretty.send(
        update.effective_chat.id,
        text,
        bot=context.bot,
        raw=send_pretty.RawFormat.PLAIN,
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
    # Reset the durable grade ledger: this is a brand-new session, so any word
    # can legitimately be graded again (e.g. an "Again" card that comes due the
    # same day). Resume paths above leave the ledger intact (Bug report 2026-08-19).
    db.clear_session_grades(user_id)
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
                await send_pretty.edit_markup(
                    update.effective_chat.id,
                    state.study_msg_id,
                    study_inactive_keyboard(),
                    bot=context.bot,
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
        msg = await send_pretty.send(
            update.effective_chat.id,
            text,
            bot=context.bot,
            raw=send_pretty.RawFormat.MDV2,
            keyboard=keyboard,
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
    msg = await send_pretty.send(
        chat_id,
        text,
        bot=context.bot,
        raw=send_pretty.RawFormat.MDV2,
        keyboard=keyboard,
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

    # Snapshot the pre-grade stability the first time a card is rendered
    # (before any grade lands), so the session summary can report the
    # before->after stability delta (Phase 2). Existing snapshots are kept.
    if word_id and state is not None and word_id not in state.before_stability:
        stability = word_row["stability"] if word_row is not None else None
        if stability is not None:
            state.before_stability[word_id] = float(stability)

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
        keyboard = get_review_keyboard(user_id, word_id)
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

def _is_message_not_modified(exc: Exception) -> bool:
    """True when a Telegram edit ``BadRequest`` means the target content is
    already on screen, i.e. the edit effectively succeeded (kilo W2). Telegram
    returns "message is not modified" when retrying an already-applied edit
    (e.g. a first attempt timed out server-side); treating it as failure would
    roll the node back and leave the screen showing a card the state disagrees
    with, dead-ending the next tap.

    python-telegram-bot exposes no stable error code for this case (it is a
    generic 400 ``BadRequest`` with freeform text), so the message text is the
    only signal — the same pattern ``services/send_pretty.say`` uses.
    """
    return isinstance(exc, BadRequest) and "not modified" in str(exc).lower()


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
        # Advance only mutates session state AFTER the Telegram edit that
        # renders the next card / report succeeds. On any edit failure the
        # popped node is rolled back so the visible card stays the active one
        # and a re-tap hits the idempotent re-grade guard, which retries the
        # advance (self-healing under weak network, Bug report 2026-08-19).
        popped = state.nodes.pop(0) if state.nodes else None

        # try next node
        if state.nodes:
            node = state.nodes[0]
            text, keyboard = _build_card_text_and_keyboard(
                node, state, user_id, user_data=context.user_data,
            )
            try:
                await send_pretty.edit(
                    chat_id,
                    state.study_msg_id,
                    text,
                    bot=context.bot,
                    raw=send_pretty.RawFormat.MDV2,
                    keyboard=keyboard,
                )
            except BadRequest as exc:
                if not _is_message_not_modified(exc):
                    if popped is not None:
                        state.nodes.insert(0, popped)
                    raise
            except Exception:
                if popped is not None:
                    state.nodes.insert(0, popped)
                raise
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
                try:
                    await send_pretty.edit(
                        chat_id,
                        state.study_msg_id,
                        text,
                        bot=context.bot,
                        raw=send_pretty.RawFormat.MDV2,
                        keyboard=keyboard,
                    )
                except BadRequest as exc:
                    if not _is_message_not_modified(exc):
                        state.nodes.pop()
                        state.total_cards -= 1
                        if popped is not None:
                            state.nodes.insert(0, popped)
                        raise
                except Exception:
                    state.nodes.pop()
                    state.total_cards -= 1
                    if popped is not None:
                        state.nodes.insert(0, popped)
                    raise
                _persist_session(user_id, state)
                return

        completion = escape_mdv2("جلسه مطالعه تموم شد! 🎉")
        text = f"*{completion}*"
        keyboard = None

        # Bronze+ (session_summary feature) get the post-session report; free
        # keeps the minimal completion message (R4). The owner always gets the
        # report (admin variant) regardless of plan. The report is ephemeral in
        # user_data (R7) and drives the detail pagination callbacks.
        is_admin = is_owner(user_id)
        if has_feature(state.plan, "session_summary") or is_admin:
            try:
                records = _gather_word_records(state, user_id)
                report = build_report(records)
                # Nonce embeds the report identity in the callback data so a
                # stale button from an OLDER message can't render the current
                # report: it fails gracefully instead. Back-navigation within
                # the current message keeps working (payload is not popped).
                nonce = uuid4().hex
                context.user_data["session_summary"] = {
                    "report": report,
                    "is_admin": is_admin,
                    "nonce": nonce,
                }
                text = format_session_summary(
                    report, is_admin=is_admin
                ).render(send_pretty.Backend.MDV2)
                # A completed session always has >=1 graded word, but guard the
                # impossible zero-total case so a detail button can never lead
                # to an empty "صفحه ۱ از ۰" page.
                keyboard = (
                    session_summary_keyboard(nonce) if report.total else None
                )
            except Exception:
                logger.exception(
                    "session summary build failed user_id=%s", user_id
                )
                text = f"*{completion}*"
                keyboard = None

# Render the completion/report FIRST; only after it succeeds is the
        # session cleared. If this edit fails transiently (weak network), the
        # session stays intact so a re-tap of the already-graded last card
        # retries this edit and the session still completes + shows the report
        # (Bug report 2026-08-19). Replaces the old clear-before-edit ordering.
        try:
            await send_pretty.edit(
                chat_id,
                state.study_msg_id,
                text,
                bot=context.bot,
                raw=send_pretty.RawFormat.MDV2,
                keyboard=keyboard,
            )
        except BadRequest as exc:
            if _is_message_not_modified(exc):
                # The completion/report is already on screen — treat as success
                # (same as the card-advance paths): clear the session with no
                # misleading warning and no duplicate fallback message.
                pass
            else:
                # Permanent edit failure (message not found / a MarkdownV2 parse
                # error in the report text): the report cannot be rendered via
                # this message. Never trap the learner for the rest of the
                # app-day — end the session — but always surface a minimal
                # plain-text completion so the learner still sees a finish
                # signal (the report itself is still lost on a parse error).
                logger.warning(
                    "completion edit permanent failure user_id=%s chat_id=%s err=%s",
                    user_id, chat_id, exc,
                )
                try:
                    await send_pretty.send(
                        chat_id,
                        f"*{completion}*",
                        bot=context.bot,
                        raw=send_pretty.RawFormat.MDV2,
                    )
                except Exception:
                    logger.exception(
                        "completion fallback send failed user_id=%s chat_id=%s",
                        user_id, chat_id,
                    )
        except Exception:
            if popped is not None:
                state.nodes.insert(0, popped)
            raise

        context.user_data.pop("current_session", None)
        _clear_persisted_session(user_id)

    except Exception:
        logger.exception("advance_session failed user_id=%s chat_id=%s", user_id, chat_id)
        try:
            error_msg = escape_mdv2("خطا در بارگذاری کارت بعدی — دوباره تلاش کنید")
            await send_pretty.send(
                chat_id,
                f"*{error_msg}*",
                bot=context.bot,
                raw=send_pretty.RawFormat.MDV2,
            )
        except Exception:
            logger.exception("advance_session error fallback also failed")


# ---------------------------------------------------------------------------
# Session summary report — data gathering + detail pagination callback (R1-R7)
# ---------------------------------------------------------------------------

def _parse_iso_utc(value: str):
    """Parse an ISO-8601 UTC timestamp, tolerating a trailing ``Z`` suffix.

    Python 3.10's ``datetime.fromisoformat`` rejects ``Z`` (3.11+ accepts it),
    so normalize it to ``+00:00`` first to keep behavior identical across the
    supported Python versions.
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _to_app_tz_date(iso_utc: str | None) -> str | None:
    """Convert a stored UTC ISO timestamp to the app-tz ``YYYY-MM-DD`` date.

    Summary relative-date labels compare against the app day, so the per-word
    ``prior``/``next`` dates must be app-tz dates too — otherwise the labels
    flip a day off near local midnight. Returns None for a missing/unparseable
    timestamp.
    """
    if not iso_utc:
        return None
    try:
        dt = _parse_iso_utc(iso_utc)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(APP_TZ).date().isoformat()


def _interval_days(word_row) -> float | None:
    """Scheduled interval in days from next_review_at back to last_review_at.

    ``word_row`` is a subscriptable row (dict or sqlite3.Row) from
    saved_words; both timestamp columns may be NULL.
    """
    try:
        last = word_row["last_review_at"]
        nxt = word_row["next_review_at"]
    except (KeyError, IndexError, TypeError):
        return None
    if not last or not nxt:
        return None
    try:
        last_dt = _parse_iso_utc(last)
        nxt_dt = _parse_iso_utc(nxt)
    except (TypeError, ValueError):
        return None
    seconds = (nxt_dt - last_dt).total_seconds()
    return round(max(0.0, seconds) / 86400, 1)


def _gather_word_records(
    state: SessionState, user_id: int
) -> list[WordReviewRecord]:
    """Assemble WordReviewRecords for the session's graded words.

    Activity type + grade come from the newest review_events row per word
    (R3, seam-safe: no srs_handler edit); the prior review date is the
    second-newest row (R2). before-stability comes from the Phase-2 snapshot.
    """
    word_ids = list(state.graded_word_ids)
    if not word_ids:
        return []
    rows = {row["id"]: row for row in db.get_saved_words_by_ids(word_ids, user_id)}
    events = db.recent_events_for_words(word_ids, user_id, per_word=2)
    records: list[WordReviewRecord] = []
    for wid in word_ids:
        wr = rows.get(wid)
        if wr is None:
            continue
        evs = events.get(wid) or []
        current = evs[0] if evs else None
        prior = evs[1] if len(evs) > 1 else None
        records.append(
            WordReviewRecord(
                word_id=wid,
                word=wr["word"],
                activity_type=(
                    current["activity_type"] if current else "srs_review"
                ),
                stability_before=state.before_stability.get(wid),
                stability_after=(
                    wr["stability"] if wr["stability"] is not None else None
                ),
                prior_review_date=_to_app_tz_date(
                    prior["created_at"] if prior else None
                ),
                grade=current["grade"] if current else None,
                interval_days=_interval_days(wr),
                next_review_date=_to_app_tz_date(wr["next_review_at"]),
                difficulty=(
                    wr["difficulty"] if wr["difficulty"] is not None else None
                ),
            )
        )
    return records


def _split_summary_action(action: str) -> tuple[str | None, str | None]:
    """Split a summary action into ``(base, nonce)``.

    Callbacks carry the report nonce as the trailing segment, e.g.
    ``page:1:<nonce>`` -> (``page:1``, ``<nonce>``). A legacy action with no
    colon returns ``(action, None)`` so the caller rejects it via the nonce
    mismatch.
    """
    head, sep, nonce = action.rpartition(":")
    if not sep:
        return action, None
    return head, nonce


async def _handle_session_summary_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
) -> None:
    """Handle session-summary detail/pagination callbacks (R1/R7).

    Renders from the ephemeral report stashed at completion. A button whose
    embedded nonce doesn't match the current report (i.e. from an older,
    superseded message) fails gracefully with an expired notice instead of
    rendering a newer report. Back-navigation within the current message is
    kept alive (the payload is not popped on back).
    """
    payload = context.user_data.get("session_summary")
    if not payload:
        await notify_callback(
            update.callback_query,
            "این گزارش منقضی شده است.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return

    base, nonce = _split_summary_action(action)
    if base is None or nonce != payload.get("nonce"):
        # Unknown action or a stale button from an older report message.
        await notify_callback(
            update.callback_query,
            "این گزارش منقضی شده است.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return

    report = payload["report"]
    is_admin = payload["is_admin"]
    total_pages = len(report.pages)

    if base == "back":
        message = format_session_summary(report, is_admin=is_admin)
        keyboard = session_summary_keyboard(nonce)
    elif base == "detail" or base.startswith("page:"):
        if base == "detail":
            page_index = 0
        else:
            try:
                page_index = int(base.split(":", 1)[1])
            except (ValueError, IndexError):
                page_index = 0
        if total_pages:
            page_index = max(0, min(page_index, total_pages - 1))
            page = report.pages[page_index]
        else:
            page = ()
        message = format_session_detail_page(
            page, page_index, total_pages, is_admin=is_admin
        )
        keyboard = session_summary_detail_keyboard(page_index, total_pages, nonce)
    elif base == "legend" or base.startswith("legend:"):
        # R8: the legend button on a detail page edits the message in place to
        # the symbol guide; its back button returns to the exact page.
        try:
            page_index = int(base.split(":", 1)[1])
        except (ValueError, IndexError):
            page_index = 0
        if total_pages:
            page_index = max(0, min(page_index, total_pages - 1))
        message = format_summary_legend()
        keyboard = session_summary_legend_keyboard(page_index, nonce)
    else:
        await notify_callback(update.callback_query)
        return

    # Route through send_pretty: ``say`` edits the callback message and inherits
    # the shared retry/concurrency seam plus the "not modified" / "not found ->
    # send replacement" fallbacks. Content is a structured Message, so each leaf
    # is escaped exactly once (no manual MarkdownV2 escaping here). ``say`` owns
    # the callback ack (it answers on "not modified"), matching the convention
    # of other ``say`` callers, so there is no trailing ack here.
    try:
        await send_pretty.say(update, context, message, keyboard=keyboard)
    except Exception:
        logger.exception(
            "session summary edit failed user_id=%s",
            update.effective_user.id,
        )


register("session:summary", _handle_session_summary_callback)
