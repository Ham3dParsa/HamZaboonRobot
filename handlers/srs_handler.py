import json
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from services import db
from services import word_query
from config import USER_ACTIVITY
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers import _user_activity_line
from services.session import resolve_grade
from services.utils.formatting import format_next_review_text
from config.keyboards import query_result_keyboard
from handlers.study_handler import advance_session

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


def _log_ua(update: Update, action: str, outcome: str):
    user = update.effective_user
    if not user:
        return
    row = db.get_user(user.id) if user else None
    line = _user_activity_line(
        user_id=user.id, full_name=user.full_name, username=user.username,
        action=action, outcome=outcome,
        plan=row["plan"] if row else None,
        lang=row["target_lang"] if row else None,
        goal=row["goal"] if row else None,
        level=row["level"] if row else None,
    )
    if line:
        logger.log(USER_ACTIVITY, "%s", line)


async def _handle_query_add(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    user_id = update.effective_user.id
    _log_ua(update, action="query_add", outcome="started")
    result = await word_query.toggle_save(token, user_id)
    if result.kind == "expired":
        await notify_callback(update.callback_query, "این نتیجه منقضی شده یا در دسترس نیست.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    if result.saved:
        logger.info("query result saved user_id=%s word_id_token=%s", user_id, token)
    else:
        logger.info("query result removed user_id=%s word_id_token=%s", user_id, token)

    kb_state = context.user_data.get(f"query_kb_{token}", {}) if context and context.user_data else {}
    markup = query_result_keyboard(
        result.token,
        result.lang,
        show_translations=kb_state.get("show_translations", False),
        show_pronounce=kb_state.get("show_pronounce", False),
        saved=result.saved,
    )
    try:
        await update.effective_message.edit_reply_markup(reply_markup=markup)
    except BadRequest as exc:
        if "not modified" not in str(exc).casefold():
            raise
    await notify_callback(update.callback_query, result.message, intent=CallbackNoticeIntent.SUCCESS_TOAST)


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
    resolved = resolve_grade("srs_review", grade)
    result = db.grade_word_review(word_id, resolved, user_id)
    if not result.ok:
        # Expected failure: do NOT record telemetry, touch streak, or advance.
        await notify_callback(
            update.callback_query,
            _grade_error_text(result.reason),
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
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
    _log_ua(update, action="srs_review", outcome=f"grade_{grade}")
    logger.info(
        "srs review user_id=%s word_id=%s grade=%s rt=%s",
        user_id,
        word_id,
        resolved,
        response_time_ms,
    )
    await advance_session(update, context)


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
    resolved = resolve_grade("first_exposure", grade)
    result = db.grade_first_exposure(word_id, resolved, user_id)
    if not result.ok:
        # Expected failure (e.g. double tap): no telemetry, streak, or advance.
        await notify_callback(
            update.callback_query,
            _grade_error_text(result.reason),
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
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
    _log_ua(update, action="first_exposure", outcome=f"grade_{grade}")
    await advance_session(update, context)
