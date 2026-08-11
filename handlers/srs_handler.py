import json
import logging
import time

from telegram import Update
from telegram.ext import ContextTypes

from services import db
from config import USER_ACTIVITY
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers import _user_activity_line
from services.session import resolve_grade
from handlers.study_handler import advance_session

logger = logging.getLogger(__name__)


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
    row = db.get_query_result(token, user_id=user_id)
    if not row:
        await notify_callback(update.callback_query, "این نتیجه منقضی شده یا در دسترس نیست.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if row["saved_at"]:
        await notify_callback(update.callback_query, "این واژه قبلاً به مرور اضافه شده است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    result_data = json.loads(row["result_json"])
    added = db.add_saved_word(user_id, row["word"], row["lang"], result_data, entry_source="manual")
    db.mark_query_result_saved(token)
    if added:
        message = "واژه به مرور شما اضافه شد. ✅"
        logger.info("query result saved user_id=%s word_id_token=%s", user_id, token)
    else:
        message = "این واژه از قبل در مرور شما ثبت شده بود."
    await notify_callback(update.callback_query, message, intent=CallbackNoticeIntent.IMPORTANT_ERROR)


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
    row = db.get_saved_word(word_id, user_id=user_id)
    if not row:
        await notify_callback(update.callback_query, "این واژه در مرور شما پیدا نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    resolved = resolve_grade("srs_review", grade)
    db.grade_word_review(word_id, resolved, user_id)
    shown_at = context.user_data.pop(f"card_shown_at_{word_id}", None)
    response_time_ms = None
    if shown_at is not None:
        elapsed = time.time() - shown_at
        response_time_ms = max(0, int(elapsed * 1000))
    db.record_review_event(
        word_id,
        user_id,
        resolved,
        "srs_review",
        grade_source="direct_button",
        raw_signal=json.dumps({"button_value": grade}),
        response_time_ms=response_time_ms,
    )
    db.touch_streak(user_id)
    await notify_callback(
        update.callback_query,
        "ثبت شد؛ مرور بعدی زمان‌بندی شد.",
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
    row = db.get_saved_word(word_id, user_id=user_id)
    if not row:
        await notify_callback(update.callback_query, "این واژه در مرور شما پیدا نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    resolved = resolve_grade("first_exposure", grade)
    db.grade_first_exposure(word_id, resolved, user_id)
    # response_time_ms intentionally omitted for first-exposure:
    # there is no recall attempt, just a familiarity rating, so
    # the signal is not comparable to regular-review response time.
    db.record_review_event(
        word_id,
        user_id,
        resolved,
        "first_exposure",
        grade_source="direct_button",
        raw_signal=json.dumps({"button_value": grade}),
        response_time_ms=None,
    )
    db.touch_streak(user_id)
    await notify_callback(update.callback_query, "ثبت شد.", intent=CallbackNoticeIntent.SUCCESS)
    _log_ua(update, action="first_exposure", outcome=f"grade_{grade}")
    await advance_session(update, context)
