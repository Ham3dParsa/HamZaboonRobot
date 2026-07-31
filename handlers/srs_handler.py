import asyncio
import json
import logging
import time

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest, NetworkError, TimedOut

from services import db
from config import _user_presentation, _user_plan, PREMIUM_PLANS, USER_ACTIVITY
from services.utils.helpers import _user_activity_line
from services.utils.formatting import (
    CardPreparationError,
    SRS_REVEAL_QUESTION,
    format_card,
    _phonetic_lines,
)
from services.utils.helpers import _answer_callback_safely, _edit_with_retry, _message_has_prepared_translations
from config.keyboards import srs_revealed_keyboard, srs_review_keyboard
from services.ai.llm_services import _prepare_cached_card
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


def _saved_word_card(row) -> dict:
    if row["card_data"]:
        try:
            data = json.loads(row["card_data"])
        except (TypeError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            return data
    return {
        "word": row["word"],
        "phonetic": "",
        "fa_meaning": "این واژه قبلاً بدون کارت کامل ذخیره شده است.",
        "fa_explanation": "معنی و مثال کامل در داده‌های قدیمی موجود نیست؛ خودت معنی را یادآوری کن.",
        "synonyms": [],
        "antonyms": [],
        "examples": [],
        "example_translations": [],
        "grammar_tip": "",
    }


async def _handle_query_add(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    user_id = update.effective_user.id
    _log_ua(update, action="query_add", outcome="started")
    row = db.get_query_result(token, user_id=user_id)
    if not row:
        await update.callback_query.answer("این نتیجه منقضی شده یا در دسترس نیست.", show_alert=True)
        return
    if row["saved_at"]:
        await update.callback_query.answer("این واژه قبلاً به مرور اضافه شده است.", show_alert=True)
        return

    result_data = json.loads(row["result_json"])
    added = db.add_saved_word(user_id, row["word"], row["lang"], result_data)
    db.mark_query_result_saved(token)
    if added:
        message = "واژه به مرور شما اضافه شد. ✅"
        logger.info("query result saved user_id=%s word_id_token=%s", user_id, token)
    else:
        message = "این واژه از قبل در مرور شما ثبت شده بود."
    await update.callback_query.answer(message, show_alert=True)


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
        await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
        return
    user_id = update.effective_user.id
    if user_id != target_user_id:
        await update.callback_query.answer("این مرور برای کاربر دیگری است.", show_alert=True)
        return
    row = db.get_saved_word(word_id, user_id=user_id)
    if not row:
        await update.callback_query.answer("این واژه در مرور شما پیدا نشد.", show_alert=True)
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
    await _answer_callback_safely(
        update.callback_query,
        "ثبت شد؛ مرور بعدی زمان‌بندی شد.",
        show_alert=True,
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
        await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
        return
    user_id = update.effective_user.id
    if user_id != target_user_id:
        await update.callback_query.answer("این مرور برای کاربر دیگری است.", show_alert=True)
        return
    row = db.get_saved_word(word_id, user_id=user_id)
    if not row:
        await update.callback_query.answer("این واژه در مرور شما پیدا نشد.", show_alert=True)
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
    await update.callback_query.answer("ثبت شد.", show_alert=True)
    _log_ua(update, action="first_exposure", outcome=f"grade_{grade}")
    await advance_session(update, context)


async def _handle_srs_reveal(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id_text: str, word_id_text: str):
    try:
        target_user_id = int(target_user_id_text)
        word_id = int(word_id_text)
    except ValueError:
        await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
        return
    user_id = update.effective_user.id
    if user_id != target_user_id:
        await update.callback_query.answer("این مرور برای کاربر دیگری است.", show_alert=True)
        return
    row = db.get_saved_word(word_id, user_id=user_id)
    if not row:
        await update.callback_query.answer("این واژه در مرور شما پیدا نشد.", show_alert=True)
        return
    if row["review_status"] != "pending":
        await update.callback_query.answer("این مرور دیگر باز نیست.", show_alert=True)
        return
    user_row = db.get_user(user_id)
    try:
        card = await asyncio.to_thread(
            _prepare_cached_card,
            _saved_word_card(row),
            lang=row["lang"],
            user_id=user_id,
            plan=(user_row["plan"] if user_row else "free") or "free",
            source="srs",
            persist_patch=lambda patch: db.update_saved_word_fields(
                word_id,
                user_id,
                patch,
            ),
        )
    except CardPreparationError:
        await update.callback_query.answer(
            "این کارت فعلاً با اطمینان آماده نشد؛ بعداً دوباره امتحان کنید.",
            show_alert=True,
        )
        return
    phon_lines = _phonetic_lines(card.get("phonetic", ""))
    try:
        is_premium = _user_plan(user_row) in PREMIUM_PLANS if user_row else False
        await _edit_with_retry(
            update.callback_query,
            format_card(
                card,
                footer=SRS_REVEAL_QUESTION,
                presentation=_user_presentation(user_row),
                phonetic_lines=phon_lines,
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=srs_revealed_keyboard(user_id, word_id, show_pronounce=is_premium),
        )
    except BadRequest as exc:
        if "not modified" in str(exc).casefold():
            await _answer_callback_safely(update.callback_query, "کارت قبلاً افشا شده است.")
        else:
            logger.exception("failed to reveal SRS card")
            await _answer_callback_safely(
                update.callback_query,
                "افشای کارت انجام نشد؛ لطفاً دوباره امتحان کنید.",
                show_alert=True,
            )
        return
    context.user_data[f"card_shown_at_{word_id}"] = time.time()
    await _answer_callback_safely(update.callback_query, "کارت افشا شد.")


async def _handle_srs_prepare(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id_text: str,
    word_id_text: str,
):
    try:
        target_user_id = int(target_user_id_text)
        word_id = int(word_id_text)
    except ValueError:
        await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
        return
    user_id = update.effective_user.id
    if user_id != target_user_id:
        await update.callback_query.answer("این مرور برای کاربر دیگری است.", show_alert=True)
        return
    _log_ua(update, action="srs_review", outcome="started")
    if _message_has_prepared_translations(update):
        await update.callback_query.answer("ترجمه‌ها آماده شده‌اند.")
        return
    row = db.get_saved_word(word_id, user_id=user_id)
    if not row:
        await update.callback_query.answer("این واژه در مرور شما پیدا نشد.", show_alert=True)
        return
    user_row = db.get_user(user_id)
    try:
        card = await asyncio.to_thread(
            _prepare_cached_card,
            _saved_word_card(row),
            lang=row["lang"],
            user_id=user_id,
            plan=(user_row["plan"] if user_row else "free") or "free",
            source="srs",
            persist_patch=lambda patch: db.update_saved_word_fields(
                word_id,
                user_id,
                patch,
            ),
        )
    except CardPreparationError:
        await update.callback_query.answer(
            "این کارت فعلاً با اطمینان آماده نشد؛ بعداً دوباره امتحان کنید.",
            show_alert=True,
        )
        return
    footer = (
        "⏰ مرور فاصله‌دار: اول معنی، مثال و نکته را از حفظ "
        "یادآوری کن؛ بعد نتیجه را با دکمه‌ها ثبت کن."
    )
    phon_lines = _phonetic_lines(card.get("phonetic", ""))
    try:
        await _edit_with_retry(
            update.callback_query,
            format_card(
                card,
                footer=footer,
                presentation=_user_presentation(user_row),
                translations_prepared=True,
                phonetic_lines=phon_lines,
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=srs_review_keyboard(
                user_id, word_id,
                show_translations=False,
                show_pronounce=_user_plan(user_row) in PREMIUM_PLANS if user_row else False,
            ),
        )
    except BadRequest as exc:
        if "not modified" in str(exc).casefold():
            await _answer_callback_safely(
                update.callback_query,
                "ترجمه‌ها قبلاً آماده شده‌اند.",
            )
        else:
            logger.exception("failed to edit prepared SRS card")
            await _answer_callback_safely(
                update.callback_query,
                "نمایش ترجمه‌ها انجام نشد؛ لطفاً دوباره امتحان کنید.",
                show_alert=True,
            )
        return
    await _answer_callback_safely(update.callback_query, "ترجمه‌ها آماده شدند.")
