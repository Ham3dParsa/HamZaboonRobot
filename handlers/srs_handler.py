import json
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from services import db, send_pretty
from services import word_query
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.activity_log import log_user_activity
from services.session import resolve_grade, SessionNode
from services.routing import register
from services.utils.formatting import (
    _saved_word_card,
    phonetic_lines,
    format_next_review_text,
    format_srs_back_stage,
)
from config.keyboards import (
    query_result_keyboard,
    get_first_exposure_keyboard,
    get_review_keyboard,
    get_srs_delete_confirm_keyboard,
)
from handlers.study_handler import (
    advance_session,
    get_active_study_session,
    session_progress_footer,
    _persist_session,
)

logger = logging.getLogger(__name__)


def _grade_error_text(reason: str) -> str:
    """Persian copy for a failed GradeResult (Rule 8: expected errors alert)."""
    if reason == "not_found":
        return "این واژه در مرور شما پیدا نشد."
    if reason == "wrong_state":
        return "این واژه در وضعیت مرور نیست؛ دوباره از جلسهٔ مطالعه شروع کنید."
    return "ثبت نشد؛ دوباره تلاش کنید."


def _record_event_guarded(*args, **kwargs):
    """Persist a review event without blocking learning progress (Rule 10).

    Scheduling has already committed before this call. A telemetry failure
    (e.g. a DB lock burst) is logged and swallowed so the streak, success toast,
    and session advance still run — the card is not re-shown merely because
    analytics persistence failed.
    """
    try:
        db.record_review_event(*args, **kwargs)
    except Exception:
        logger.exception("record_review_event failed word_id=%s user_id=%s", kwargs.get("word_id"), kwargs.get("user_id"))


async def _handle_query_add(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    user_id = update.effective_user.id
    log_user_activity(update, action="query_add", outcome="started")
    result = await word_query.toggle_save(token, user_id)
    if result.kind == "expired":
        await notify_callback(update.callback_query, "این نتیجه منقضی شده یا در دسترس نیست.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    if result.saved:
        logger.info("query result saved user_id=%s word_id_token=%s", user_id, token)
    else:
        logger.info("query result removed user_id=%s word_id_token=%s", user_id, token)

    markup = query_result_keyboard(
        result.token,
        result.lang,
        saved=result.saved,
    )
    try:
        await send_pretty.edit_markup(
            update.effective_chat.id,
            update.effective_message.message_id,
            markup,
            bot=context.bot,
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).casefold():
            raise
    await notify_callback(update.callback_query, result.message, intent=CallbackNoticeIntent.SUCCESS_TOAST)


async def _handle_srs_reveal(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id_text: str,
    word_id_text: str,
) -> None:
    """Reveal the front stage: turn the same message into the back stage with
    the 4-grade review keyboard (#338 §2B). Idempotent per card presentation."""
    try:
        target_user_id = int(target_user_id_text)
        word_id = int(word_id_text)
    except ValueError:
        await notify_callback(
            update.callback_query, "دکمه‌ی نامعتبر است.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
    user_id = update.effective_user.id
    if user_id != target_user_id:
        await notify_callback(
            update.callback_query, "این مرور برای کاربر دیگری است.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
    # Frozen reveal is authoritative; check both ephemeral and persisted.
    state_early = get_active_study_session(user_id, context)
    if state_early is not None and state_early.revealed and state_early.active_prompt_word_id == word_id:
        await notify_callback(update.callback_query)
        return
    if context.user_data.get(f"revealed_{word_id}"):
        await notify_callback(update.callback_query)
        return

    # Restart recovery: a same-day persisted session may exist even though the
    # in-memory session was lost (mirrors the grade handlers, Bug #401).
    state = state_early
    node = state.nodes[0] if state and state.nodes else None
    if (
        node is None
        or node.activity_type not in ("srs_review", "first_exposure")
        or node.source_id != word_id
    ):
        # Stale reveal button (superseded session or message): never render a
        # different card onto the active session message (Kilo review #1).
        await notify_callback(
            update.callback_query, "این پیام دیگر معتبر نیست.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return

    word_row = db.get_saved_word(word_id, user_id)
    card_data = _saved_word_card(word_row) if word_row else {}
    toggles = db.get_display_toggles(user_id)
    phon_lines = phonetic_lines(card_data.get("phonetic", ""))
    footer = session_progress_footer(state, user_id)
    text = format_srs_back_stage(
        card_data,
        toggles=toggles,
        phonetic_lines=phon_lines,
        footer=footer,
    )
    if node.activity_type == "first_exposure":
        # CARD-MODES Rule 1: a staged first-exposure card reveals onto the FE
        # familiarity grade grid, not the recall-based review grid.
        keyboard = get_first_exposure_keyboard(user_id, word_id)
    else:
        keyboard = get_review_keyboard(user_id, word_id)

    msg_id = state.study_msg_id
    if not msg_id:
        await notify_callback(
            update.callback_query, "این پیام دیگر معتبر نیست.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
    try:
        await send_pretty.edit(
            update.effective_chat.id,
            msg_id,
            text,
            bot=context.bot,
            raw=send_pretty.RawFormat.MDV2,
            keyboard=keyboard,
        )
    except BadRequest as exc:
        # Message already gone or unchanged — give feedback instead of crashing
        # the callback (Kilo review #2).
        if "not modified" in str(exc).casefold():
            await notify_callback(update.callback_query)
            return
        logger.warning(
            "srs reveal edit failed user_id=%s word_id=%s: %s",
            user_id, word_id, exc,
        )
        await notify_callback(
            update.callback_query, "این پیام دیگر معتبر نیست.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
    except Exception:
        logger.exception("srs reveal edit failed user_id=%s word_id=%s", user_id, word_id)
        await notify_callback(
            update.callback_query, "این پیام دیگر معتبر نیست.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
    # Freeze revealed so resume/restart shows back stage (R2) — only commit
    # to memory after DB confirms, otherwise a failed write would diverge
    # memory (back) from DB (front) and re-introduce the flip exploit (kilo 200).
    old_revealed = state.revealed
    old_prompt_wid = state.active_prompt_word_id
    state.revealed = True
    if state.active_prompt_word_id != word_id:
        state.active_prompt_word_id = word_id
    try:
        _persist_session(user_id, state)
    except Exception:
        # Roll back so memory and DB stay in sync (front) until next reveal.
        state.revealed = old_revealed
        state.active_prompt_word_id = old_prompt_wid
        logger.exception("reveal persist failed user_id=%s word_id=%s", user_id, word_id)
        # Still keep ephemeral flag so the current message stays as back; DB
        # will be corrected on next successful reveal. Don't clear user_data.
        context.user_data[f"revealed_{word_id}"] = True
        await notify_callback(update.callback_query)
        return
    context.user_data[f"revealed_{word_id}"] = True
    await notify_callback(update.callback_query)


async def _handle_srs_review(
    update: Update,
    grade: int,
    target_user_id_text: str,
    word_id_text: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    try:
        target_user_id = int(target_user_id_text)
        word_id = int(word_id_text)
    except ValueError:
        await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    user_id = update.effective_user.id
    if user_id != target_user_id:
        await notify_callback(update.callback_query, "این مرور برای کاربر دیگری است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    session = get_active_study_session(user_id, context)
    already_graded = (
        (session is not None and word_id in session.graded_word_ids)
        or db.is_word_graded(user_id, word_id, "srs_review")
    )
    if session is not None:
        active = (
            bool(session.nodes)
            and session.nodes[0].source_id == word_id
            and session.nodes[0].activity_type == "srs_review"
        )
        if already_graded and (active or not session.nodes):
            # Duplicate grade of a done card: the DB write landed but its
            # advance was lost to a restart/network error, a genuine double
            # tap, or a stuck completion whose report edit failed. Never
            # re-grade (FSRS corruption) and never soft-lock (R3, Bug #401):
            # advance_session self-heals — it rolls back on a failed edit and
            # completes + renders the report when the last card was graded.
            context.user_data.pop(f"card_shown_at_{word_id}", None)
            log_user_activity(update, action="srs_review", outcome="grade_already_recorded")
            await notify_callback(
                update.callback_query,
                "قبلاً ثبت شد.",
                intent=CallbackNoticeIntent.INFO,
            )
            # Backfill the in-session graded list: a durable ledger row can exist
            # while the session's graded_word_ids missed it (grade persisted, but
            # the session-save failed). Advancing without backfilling would make
            # the end-of-session report undercount this word (kilo S1).
            if word_id not in session.graded_word_ids:
                session.graded_word_ids.append(word_id)
            await advance_session(update, context)
            return
        if not active:
            # Stale/out-of-session button (e.g. a pre-restart message, or an old
            # first-exposure card whose word resurfaced as a review node): never
            # grade a card that is not the active review card (R2, Bug #401).
            await notify_callback(
                update.callback_query,
                "این پیام دیگر معتبر نیست.",
                intent=CallbackNoticeIntent.IMPORTANT_ERROR,
            )
            return
    else:
        if already_graded:
            # No session at all (memory + persisted gone) but the durable
            # ledger says this word was already graded in the current session.
            # Block the re-grade; there is no session left to advance.
            context.user_data.pop(f"card_shown_at_{word_id}", None)
            log_user_activity(update, action="srs_review", outcome="grade_already_recorded")
            await notify_callback(
                update.callback_query,
                "قبلاً ثبت شد.",
                intent=CallbackNoticeIntent.INFO,
            )
            return
    resolved = resolve_grade("srs_review", grade)
    result = db.grade_word_review(word_id, resolved, user_id)
    if result.ok:
        if session is not None:
            session.graded_word_ids.append(word_id)
            # Persist durable IMMEDIATELY (before advance_session) so a restart
            # or lost advance still records this card as graded for the
            # idempotent re-grade guard (R3, Bug #401).
            _persist_session(user_id, session)
        shown_at = context.user_data.pop(f"card_shown_at_{word_id}", None)
        response_time_ms = None
        if shown_at is not None:
            elapsed = time.time() - shown_at
            response_time_ms = max(0, int(elapsed * 1000))
        _record_event_guarded(
            word_id=word_id,
            user_id=user_id,
            grade=resolved,
            activity_type="srs_review",
            grade_source="direct_button",
            raw_signal=json.dumps({"button_value": grade}),
            response_time_ms=response_time_ms,
        )
        db.touch_streak(user_id)
        await notify_callback(
            update.callback_query,
            format_next_review_text(result.interval_seconds),
            intent=CallbackNoticeIntent.SUCCESS,
        )
        log_user_activity(update, action="srs_review", outcome=f"grade_{grade}")
        logger.info(
            "srs review user_id=%s word_id=%s grade=%s rt=%s",
            user_id,
            word_id,
            resolved,
            response_time_ms,
        )
        await advance_session(update, context)
    else:
        # Genuine error (e.g. wrong_state: no first exposure / no last_review_at).
        # Do NOT record telemetry, touch streak, or advance.
        await notify_callback(
            update.callback_query,
            _grade_error_text(result.reason),
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return


async def _handle_first_exposure_grade(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    grade_str: str,
    target_user_id_text: str,
    word_id_text: str,
) -> None:
    try:
        target_user_id = int(target_user_id_text)
        word_id = int(word_id_text)
        grade = int(grade_str)
    except ValueError:
        await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    user_id = update.effective_user.id
    if user_id != target_user_id:
        await notify_callback(update.callback_query, "این مرور برای کاربر دیگری است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    session = get_active_study_session(user_id, context)
    already_graded = (
        (session is not None and word_id in session.graded_word_ids)
        or db.is_word_graded(user_id, word_id, "first_exposure")
    )
    if session is not None:
        active = (
            bool(session.nodes)
            and session.nodes[0].source_id == word_id
            and session.nodes[0].activity_type == "first_exposure"
        )
        if already_graded and (active or not session.nodes):
            # Duplicate grade of a done card (lost advance, double tap, or a
            # stuck completion whose report edit failed). Never re-grade and
            # never soft-lock (R3, Bug #401): advance self-heals and completes.
            context.user_data.pop(f"card_shown_at_{word_id}", None)
            log_user_activity(update, action="first_exposure", outcome="grade_already_recorded")
            await notify_callback(
                update.callback_query,
                "قبلاً ثبت شد.",
                intent=CallbackNoticeIntent.INFO,
            )
            # Backfill the in-session graded list (kilo S1) — see the review
            # handler for the same reasoning.
            if word_id not in session.graded_word_ids:
                session.graded_word_ids.append(word_id)
            await advance_session(update, context)
            return
        if not active:
            # Stale/out-of-session button (e.g. a pre-restart message, or an old
            # review card whose word resurfaced as a first-exposure node): never
            # grade a card that is not the active first-exposure card (R2, #401).
            await notify_callback(
                update.callback_query,
                "این پیام دیگر معتبر نیست.",
                intent=CallbackNoticeIntent.IMPORTANT_ERROR,
            )
            return
    else:
        if already_graded:
            # No session left but the durable ledger says this word was already
            # graded in the current session. Block the re-grade.
            context.user_data.pop(f"card_shown_at_{word_id}", None)
            log_user_activity(update, action="first_exposure", outcome="grade_already_recorded")
            await notify_callback(
                update.callback_query,
                "قبلاً ثبت شد.",
                intent=CallbackNoticeIntent.INFO,
            )
            return
    resolved = resolve_grade("first_exposure", grade)
    result = db.grade_first_exposure(word_id, resolved, user_id)
    if result.ok:
        if session is not None:
            session.graded_word_ids.append(word_id)
            # Persist durable IMMEDIATELY (before advance_session) so a restart
            # or lost advance still records this card as graded for the
            # idempotent re-grade guard (R3, Bug #401).
            _persist_session(user_id, session)
        # response_time_ms intentionally omitted for first-exposure:
        # there is no recall attempt, just a familiarity rating, so
        # the signal is not comparable to regular-review response time.
        _record_event_guarded(
            word_id=word_id,
            user_id=user_id,
            grade=resolved,
            activity_type="first_exposure",
            grade_source="direct_button",
            raw_signal=json.dumps({"button_value": grade}),
            response_time_ms=None,
        )
        db.touch_streak(user_id)
        await notify_callback(
            update.callback_query,
            format_next_review_text(result.interval_seconds),
            intent=CallbackNoticeIntent.SUCCESS,
        )
        log_user_activity(update, action="first_exposure", outcome=f"grade_{grade}")
        await advance_session(update, context)
    else:
        await notify_callback(
            update.callback_query,
            _grade_error_text(result.reason),
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return


# ---------- حذف کارت از جعبه مرور (P3-T2) ----------

def _split_delete_action(action: str) -> tuple[int, int] | None:
    parts = action.split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _active_node_for_word(state, word_id: int):
    node = state.nodes[0] if state and state.nodes else None
    if node is None or node.source_id != word_id:
        return None
    return node


async def _resolve_delete_context(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str
) -> tuple[int, int, object, object] | None:
    """Shared guard for the srs:delete* handlers: parse action, enforce the
    caller owns the word, and reject stale/non-active sessions. Returns
    (user_id, word_id, state, node) or None after notifying an error."""
    parsed = _split_delete_action(action)
    if parsed is None:
        await notify_callback(
            update.callback_query, "دکمه‌ی نامعتبر است.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return None
    user_id = update.effective_user.id
    target_user_id, word_id = parsed
    if user_id != target_user_id:
        await notify_callback(
            update.callback_query, "این مرور برای کاربر دیگری است.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return None
    state = get_active_study_session(user_id, context)
    node = _active_node_for_word(state, word_id)
    if node is None or not state or not state.study_msg_id:
        await notify_callback(
            update.callback_query, "این پیام دیگر معتبر نیست.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return None
    return user_id, word_id, state, node


# Tier-3 generation (generate_tier3_node) is not yet live; the refill search in
# _next_due_node covers tier-1 due and tier-2 pre-first-exposure only, and is
# where a future tier-3 source would be appended.


def _next_due_node(
    user_id: int, target_lang: str | None, state
) -> SessionNode | None:
    """Return the highest-priority not-yet-in-session due card, or None.

    Refill priority (owner decision, Kilo review #406): tier 1 (due review)
    first, then tier 2 (first exposure). A future tier-3 source is appended
    to this search when Tier-3 generation (generate_tier3_node) lands.
    """
    session_ids = {n.source_id for n in state.nodes if n.source_id is not None}

    def _candidates():
        for row in (db.due_words_for_user(user_id, target_lang) or []):
            if row["id"] not in session_ids:
                yield row, "srs_review", 1, "srs_review"
        for row in (db.get_pre_first_exposure_words(user_id, target_lang) or []):
            if row["id"] not in session_ids:
                yield row, "first_exposure", 2, "first_exposure"

    for row, activity_type, source_tier, grade_policy in _candidates():
        return SessionNode(
            activity_type=activity_type,
            source_tier=source_tier,
            card_data={"word": row["word"]},
            source_id=row["id"],
            activity_meta={"user_id": user_id, "target_lang": target_lang},
            grade_policy_ref=grade_policy,
        )
    return None


def _refill_session_from_due(user_id: int, state) -> None:
    """Rule 10: after a delete, append the next highest-priority due tier-1/2
    card so the session keeps its planned size, unless the due queues are
    exhausted."""
    node = state.nodes[0] if state and state.nodes else None
    if node is None:
        return
    target_lang = (node.activity_meta or {}).get("target_lang")
    new_node = _next_due_node(user_id, target_lang, state)
    if new_node is not None:
        state.nodes.append(new_node)


async def _handle_srs_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str
) -> None:
    resolved = await _resolve_delete_context(update, context, action)
    if resolved is None:
        return
    user_id, word_id, state, _node = resolved
    try:
        await send_pretty.edit_markup(
            update.effective_chat.id,
            state.study_msg_id,
            get_srs_delete_confirm_keyboard(user_id, word_id),
            bot=context.bot,
        )
    except (TimedOut, NetworkError, RetryAfter):
        # The seam retries with bounded backoff before re-raising; answer the
        # callback so the user is not left with a stuck spinner (Kilo review).
        logger.warning("srs delete confirm edit failed user_id=%s", user_id)
        await notify_callback(
            update.callback_query, "اتصال برقرار نشد؛ دوباره تلاش کنید.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
    except BadRequest as exc:
        if "not modified" not in str(exc).casefold():
            raise
    await notify_callback(update.callback_query)


async def _handle_srs_delete_yes(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str
) -> None:
    resolved = await _resolve_delete_context(update, context, action)
    if resolved is None:
        return
    user_id, word_id, state, _node = resolved
    try:
        deleted = db.delete_saved_word(word_id, user_id)
        _refill_session_from_due(user_id, state)
        _persist_session(user_id, state)
    except Exception:
        logger.exception("srs delete failed user_id=%s word_id=%s", user_id, word_id)
        await notify_callback(
            update.callback_query, "حذف انجام نشد؛ دوباره تلاش کنید.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
    log_user_activity(update, action="srs_delete", outcome="deleted")
    message = "کارت حذف شد." if deleted else "این کارت قبلاً حذف شده بود."
    await notify_callback(
        update.callback_query, message, intent=CallbackNoticeIntent.SUCCESS,
    )
    await advance_session(update, context)


async def _handle_srs_delete_no(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str
) -> None:
    resolved = await _resolve_delete_context(update, context, action)
    if resolved is None:
        return
    user_id, word_id, state, node = resolved
    if node.activity_type == "first_exposure":
        keyboard = get_first_exposure_keyboard(user_id, word_id)
    else:
        keyboard = get_review_keyboard(user_id, word_id)
    try:
        await send_pretty.edit_markup(
            update.effective_chat.id,
            state.study_msg_id,
            keyboard,
            bot=context.bot,
        )
    except (TimedOut, NetworkError, RetryAfter):
        logger.warning("srs delete-cancel edit failed user_id=%s", user_id)
        await notify_callback(
            update.callback_query, "اتصال برقرار نشد؛ دوباره تلاش کنید.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
    except BadRequest as exc:
        if "not modified" not in str(exc).casefold():
            raise
    await notify_callback(update.callback_query)


register("srs:delete", _handle_srs_delete)
register("srs:delete:yes", _handle_srs_delete_yes)
register("srs:delete:no", _handle_srs_delete_no)
