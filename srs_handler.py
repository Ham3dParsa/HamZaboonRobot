import asyncio
import json
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest

import db
from config import _user_presentation
from formatting import (
    CardPreparationError,
    SRS_REVEAL_QUESTION,
    format_card,
    _phonetic_lines,
)
from helpers import _answer_callback_safely, _message_has_prepared_translations
from keyboards import srs_revealed_keyboard, srs_review_keyboard
from llm_services import _prepare_cached_card

logger = logging.getLogger("hamzaban")


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


async def _handle_srs_review(update: Update, action: str, target_user_id_text: str, word_id_text: str):
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
    if action in {"remember", "confirm"}:
        if not db.advance_word_review(word_id):
            await update.callback_query.answer("این مرور قبلاً ثبت شده است.", show_alert=True)
            return
        db.touch_streak(user_id)
        revealed = action == "confirm"
        db.record_review_event(
            word_id,
            user_id,
            revealed_before_answer=revealed,
            outcome="recalled_after_peek" if revealed else "recalled",
        )
        await update.callback_query.answer("ثبت شد؛ مرور بعدی زمان‌بندی شد.", show_alert=True)
        logger.info(
            "srs review advanced user_id=%s word_id=%s revealed=%s",
            user_id,
            word_id,
            revealed,
        )
        return
    if action == "again":
        if not db.defer_word_review(word_id):
            await update.callback_query.answer("این مرور قبلاً ثبت شده است.", show_alert=True)
            return
        db.touch_streak(user_id)
        db.record_review_event(
            word_id,
            user_id,
            revealed_before_answer=True,
            outcome="again",
        )
        await update.callback_query.answer("باشه؛ فردا دوباره یادآوری می‌کنم.", show_alert=True)
        logger.info("srs review deferred user_id=%s word_id=%s", user_id, word_id)
        return
    await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)


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
        await update.callback_query.edit_message_text(
            format_card(
                card,
                footer=SRS_REVEAL_QUESTION,
                presentation=_user_presentation(user_row),
                phonetic_lines=phon_lines,
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=srs_revealed_keyboard(user_id, word_id),
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
        await update.callback_query.edit_message_text(
            format_card(
                card,
                footer=footer,
                presentation=_user_presentation(user_row),
                translations_prepared=True,
                phonetic_lines=phon_lines,
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=srs_review_keyboard(user_id, word_id, show_translations=False),
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
