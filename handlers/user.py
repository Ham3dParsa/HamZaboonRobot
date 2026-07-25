import asyncio
import json
import logging
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from services.ai import ai
from services import db
from services.ai import prompts
from config.catalog import (
    GOALS,
    LANGUAGES,
    LEVELS,
    goal_label,
    language_label,
    level_cefr,
    level_label,
)
from config import (
    APP_TIMEZONE,
    AI_CARD_OUTPUT_FORMAT,
    DEFAULT_PRESENTATION,
    OWNER_BYPASS_LIMITS,
    PLANS,
    PREMIUM_PLANS,
    USER_ACTIVITY,
    _app_today,
    _user_presentation,
    _user_plan,
    _user_plan_label,
    daily_word_query_limit_for_plan,
    effective_daily_allowance,
    is_owner,
)
from services.utils.formatting import (
    CardPreparationError,
    escape_mdv2,
    escape_mdv2_code,
    format_card,
    format_srs_prompt,
    _phonetic_lines,
)
from services.utils.helpers import (
    _answer_callback_safely,
    _edit_or_send,
    _edit_with_retry,
    _exit_awaiting_flow,
    _finish_llm_wait_state,
    _is_cancel_input,
    _message_has_prepared_translations,
    _normalize_custom_word_input,
    _send_with_retry,
    _start_llm_wait_state,
    _user_activity_line,
    _CANCEL_INPUTS,
    _CUSTOM_WORD_MAX_CHARS,
    _CUSTOM_WORD_MAX_WORDS,
)
from config.keyboards import (
    main_menu,
    lang_inline_keyboard,
    goal_inline_keyboard,
    level_inline_keyboard,
    presentation_settings_keyboard,
    settings_inline_keyboard,
    awaiting_reply_keyboard,
    awaiting_inline_keyboard,
    daily_review_dates_keyboard,
    daily_review_menu_keyboard,
    query_result_keyboard,
    daily_card_keyboard,
    srs_hidden_keyboard,
    BTN_TODAY_CARD,
    BTN_ASK_WORD,
    BTN_GRAMMAR,
    BTN_ADMIN,
    BTN_SRS_REVIEW,
    BTN_SETTINGS,
    BTN_CANCEL,
    BTN_BACK,
)
from services.ai.llm_services import _call_ai_limited, _prepare_cached_card
from handlers.srs_handler import _saved_word_card

logger = logging.getLogger(__name__)


def _log_user_activity(update: Update, *, action: str, outcome: str):
    """Log a USER_ACTIVITY line if the feature is enabled."""
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


def _word_query_usage(row) -> tuple[int, int]:
    used = row["words_asked_today"] or 0
    if row["words_asked_date"] != _app_today():
        used = 0
    return used, daily_word_query_limit_for_plan(row["plan"] or "free")


def _word_query_usage_text(row) -> str:
    used, limit = _word_query_usage(row)
    if limit < 0:
        return f"📊 استفاده امروز: {used} / نامحدود"
    remaining = max(limit - used, 0)
    return f"📊 استفاده امروز: {used}/{limit} · باقی‌مانده: {remaining}"


def _grammar_tip_usage(row) -> tuple[int, int]:
    used = row["grammar_tips_asked_today"] or 0
    if row["grammar_tips_asked_date"] != _app_today():
        used = 0
    return used, daily_word_query_limit_for_plan(row["plan"] or "free")


def _grammar_tip_usage_text(row) -> str:
    used, limit = _grammar_tip_usage(row)
    if limit < 0:
        return f"📊 استفاده امروز از نکات گرامری: {used} / نامحدود"
    remaining = max(limit - used, 0)
    return f"📊 استفاده امروز از نکات گرامری: {used}/{limit} · باقی‌مانده: {remaining}"


# ---------------- /start و onboarding ----------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.reset_user_blocked(user.id)
    db.create_user_if_needed(user.id, user.username or user.first_name or "")
    row = db.get_user(user.id)

    _ua_line = _user_activity_line(
        user_id=user.id, full_name=user.full_name, username=user.username,
        action="start", outcome="onboarded" if row and row["onboarded"] else "new",
        plan=row["plan"] if row else None,
    )
    if _ua_line:
        logger.log(USER_ACTIVITY, "%s", _ua_line)

    if row and row["onboarded"]:
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            "خوش برگشتی به هم‌زبان 👋",
            reply_markup=main_menu(is_owner(user.id)),
        )
        return

    welcome_text = "سلام! 👋 به *هم‌زبان* خوش اومدی.\nاول بگو داری چه زبونی یاد می‌گیری؟"
    welcome_text = escape_mdv2(welcome_text)

    await _send_with_retry(
        context.bot,
        update.effective_chat.id,
        welcome_text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=lang_inline_keyboard(),
    )


async def on_lang_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    _log_user_activity(update, action="onboard_lang", outcome=f"lang={lang}")
    context.user_data["pending_lang"] = lang
    lang_name = language_label(lang)
    text = f"زبان انتخابی: *{lang_name}* ✅\nحالا هدفت از یادگیری چیه؟"
    text = escape_mdv2(text)

    await _edit_or_send(
        update,
        context,
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=goal_inline_keyboard(),
    )


async def on_goal_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, goal: str):
    _log_user_activity(update, action="onboard_goal", outcome=f"goal={goal}")
    user_id = update.effective_user.id
    lang = context.user_data.get("pending_lang", "en")
    db.set_user_lang_goal(user_id, lang, goal)

    await _edit_or_send(
        update,
        context,
        "حالا سطح فعلی زبانت را انتخاب کن:",
        reply_markup=level_inline_keyboard(),
    )


async def on_level_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, level: str):
    _log_user_activity(update, action="onboard_level", outcome=f"level={level}")
    user_id = update.effective_user.id
    db.set_user_level(user_id, level)
    row = db.get_user(user_id)
    lang_name = language_label(row["target_lang"])
    goal_name = goal_label(row["goal"])
    level_name = level_label(level)
    cefr = level_cefr(level)

    text = f"عالی! سطح تو *{level_name}* ({cefr}) ثبت شد."
    text_to_send = text.replace("*", "@@@")
    text_to_send = escape_mdv2(text_to_send)
    text_to_send = text_to_send.replace("@@@", "*")

    logger.debug(f"Sending message: {text_to_send}")

    await _edit_or_send(
        update,
        context,
        text_to_send,
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await _send_with_retry(
        context.bot,
        user_id,
        f"زبان: {lang_name} · هدف: {goal_name}\n"
        "از منوی پایین استفاده کن:",
        reply_markup=main_menu(is_owner(user_id)),
    )


async def change_lang_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_user_activity(update, action="lang_change", outcome="started")
    await _send_with_retry(
        context.bot,
        update.effective_chat.id,
        "زبان جدید خود را انتخاب کنید:",
        reply_markup=lang_inline_keyboard(),
    )


async def change_goal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_user_activity(update, action="goal_change", outcome="started")
    await _send_with_retry(
        context.bot,
        update.effective_chat.id,
        "هدف جدید خود را انتخاب کنید:",
        reply_markup=goal_inline_keyboard(),
    )


async def change_level_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_user_activity(update, action="level_change", outcome="started")
    await _send_with_retry(
        context.bot,
        update.effective_chat.id,
        "سطح جدید خود را انتخاب کنید:",
        reply_markup=level_inline_keyboard(),
    )


async def change_presentation_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        return
    current = _user_presentation(row)
    if (row["plan"] or "free") not in PREMIUM_PLANS:
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            f"نمایش فعلی کارت‌ها: {'خلاصه' if current == 'brief' else 'کامل'}.\n"
            "انتخاب دائمی نمایش کارت فقط برای کاربران پریمیوم فعال است.",
        )
        return
    await _send_with_retry(
        context.bot,
        update.effective_chat.id,
        f"نمایش فعلی کارت‌ها: {'خلاصه' if current == 'brief' else 'کامل'}.\n"
        "نمایش موردنظر را انتخاب کنید:",
        reply_markup=presentation_settings_keyboard(current),
    )


async def on_lang_changed(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    user_id = update.effective_user.id
    _log_user_activity(update, action="lang_change", outcome=f"saved: {lang}")
    db.set_user_lang(user_id, lang)

    lang_name = language_label(lang)
    text = f"✅ زبان با موفقیت به *{lang_name}* تغییر کرد."
    text = escape_mdv2(text)

    await _edit_or_send(
        update,
        context,
        text,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await _send_with_retry(
        context.bot,
        user_id,
        "از منوی پایین استفاده کنید:",
        reply_markup=main_menu(is_owner(user_id)),
    )


async def on_goal_changed(update: Update, context: ContextTypes.DEFAULT_TYPE, goal: str):
    user_id = update.effective_user.id
    _log_user_activity(update, action="goal_change", outcome=f"saved: {goal}")
    db.set_user_goal(user_id, goal)

    goal_name = goal_label(goal)
    text = f"✅ هدف با موفقیت به *{goal_name}* تغییر کرد."
    text = escape_mdv2(text)

    await _edit_or_send(
        update,
        context,
        text,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await _send_with_retry(
        context.bot,
        user_id,
        "از منوی پایین استفاده کنید:",
        reply_markup=main_menu(is_owner(user_id)),
    )


async def on_level_changed(update: Update, context: ContextTypes.DEFAULT_TYPE, level: str):
    user_id = update.effective_user.id
    _log_user_activity(update, action="level_change", outcome=f"saved: {level}")
    db.set_user_level(user_id, level)
    level_name = level_label(level)
    cefr = level_cefr(level)
    text = f"✅ سطح با موفقیت به *{level_name}* ({cefr}) تغییر کرد."
    await _edit_or_send(
        update,
        context,
        escape_mdv2(text),
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await _send_with_retry(
        context.bot,
        user_id,
        "از منوی پایین استفاده کنید:",
        reply_markup=main_menu(is_owner(user_id)),
    )


# ---------------- دکمه‌های اصلی ----------------


async def send_grammar_tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    _log_user_activity(update, action="grammar_tip", outcome="requested")
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        return

    limit = daily_word_query_limit_for_plan(row["plan"] or "free")
    usage_before_text = _grammar_tip_usage_text(row)
    if not db.reserve_grammar_tip(
        user_id,
        limit,
        bypass_limits=OWNER_BYPASS_LIMITS and is_owner(user_id),
    ):
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            f"{usage_before_text}\n\nسقف روزانه‌ی نکته‌ی گرامری تموم شده.",
        )
        return
    usage_text = _grammar_tip_usage_text(db.get_user(user_id) or row)
    wait_message = await _start_llm_wait_state(
        update,
        context,
        "⏳ دارم نکته‌ی گرامری رو آماده می‌کنم…",
    )
    try:
        recent_topics = db.recent_grammar_tip_titles(
            user_id,
            row["target_lang"],
        )
        try:
            data = await asyncio.to_thread(
                _call_ai_limited,
                ai.ask_json,
                prompts.grammar_tip_system_prompt(
                    row["target_lang"],
                    row["goal"],
                    row["level"],
                    avoid_topics=recent_topics,
                ),
                request_kind="grammar_tip",
                user_id=user_id,
                plan=row["plan"] or "free",
            )
        except Exception:
            db.release_grammar_tip(user_id)
            logger.exception("AI error")
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
                "مشکلی در ارتباط با هوش مصنوعی پیش اومد، دوباره امتحان کن.",
            )
            return
        title = escape_mdv2(data.get('title', ''))
        explanation = escape_mdv2(data.get('explanation', ''))
        example = escape_mdv2_code(data.get('example', ''))

        text = f"✍️ *{title}*\n\n{explanation}\n\n`{example}`\n\n{escape_mdv2(usage_text)}"

        db.touch_streak(user_id)
        db.add_grammar_tip(
            user_id,
            data.get("title", ""),
            row["target_lang"],
            row["goal"],
            row["level"],
            data,
        )
        _log_user_activity(update, action="grammar_tip", outcome="success")
        logger.info("grammar tip delivered user_id=%s lang=%s", user_id, row["target_lang"])
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            text,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception:
        _log_user_activity(update, action="grammar_tip", outcome="error")
        logger.exception("Grammar tip delivery failed")
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            "مشکلی در ارسال نکته‌ی گرامری پیش اومد.",
        )
    finally:
        await _finish_llm_wait_state(wait_message, bot=context.bot)


async def ask_for_ask_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    _log_user_activity(update, action="word_query", outcome="requested")
    row = db.get_user(user_id)
    plan = row["plan"] if row else "free"
    limit = daily_word_query_limit_for_plan(plan)
    usage_text = _word_query_usage_text(row) if row else f"📊 استفاده امروز: 0/{limit}"
    if not db.can_ask_word(
        user_id,
        limit,
        bypass_limits=OWNER_BYPASS_LIMITS and is_owner(user_id),
    ):
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            f"{usage_text}\n\nسقف روزانه‌ی پرسش واژه‌ی پلن شما تموم شده.",
        )
        return
    context.user_data["awaiting"] = "ask_word"
    await _send_with_retry(
        context.bot,
        update.effective_chat.id,
        f"{usage_text}\n\nچه واژه یا عبارتی رو می‌خوای معنی/توضیح بدم؟",
        reply_markup=awaiting_reply_keyboard(),
    )


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        return
    due = db.due_words_for_user(user_id)
    text = (
        f"🌐 زبان: {language_label(row['target_lang'])}\n"
        f"🎯 هدف: {goal_label(row['goal'])}\n"
        f"📚 سطح: {level_label(row['level'])}\n"
        f"💳 پلن: {_user_plan_label(row)}\n"
        f"🔥 استریک: {row['streak'] or 0} روز\n"
        f"⏰ واژه‌های آماده‌ی مرور: {len(due)}"
    )
    await _send_with_retry(context.bot, update.effective_chat.id, text)


async def _show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        return
    lang_name = language_label(row["target_lang"])
    goal_name = goal_label(row["goal"])
    level_name = level_label(row["level"])
    await _send_with_retry(
        context.bot,
        update.effective_chat.id,
        "⚙️ تنظیمات و پروفایل من:\nاز دکمه‌های زیر یکی را انتخاب کن.",
        reply_markup=settings_inline_keyboard(lang_name, goal_name, level_name),
    )


async def start_srs_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        return
    due = db.due_words_for_user(user_id)
    if not due:
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            "🎉 واژه‌ای برای مرور نداری! هر روز فلش‌کارت بگیر و واژه‌های جدید را به مرور اضافه کن.",
        )
        return
    word = due[0]
    try:
        card = await asyncio.to_thread(
            _prepare_cached_card,
            _saved_word_card(word),
            lang=word["lang"],
            user_id=user_id,
            plan=row["plan"] or "free",
            source="srs",
            persist_patch=lambda patch, word_id=word["id"]: db.update_saved_word_fields(word_id, user_id, patch),
        )
    except CardPreparationError:
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            "این کارت فعلاً با اطمینان آماده نشد؛ بعداً دوباره امتحان کن.",
        )
        return
    phon_lines = _phonetic_lines(card.get("phonetic", ""))
    show_pronounce = db.get_setting("tts_access", "premium") != "none" and ((row["plan"] or "free") in PREMIUM_PLANS or db.get_setting("tts_access", "premium") == "all")
    await _send_with_retry(
        context.bot,
        update.effective_chat.id,
        format_srs_prompt(card, phonetic_lines=phon_lines),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=srs_hidden_keyboard(user_id, word["id"], show_pronounce=show_pronounce),
    )


# ---------------- Callback handlers ----------------


def _review_history_page(dates: list[str], page: int, page_size: int = 7) -> tuple[list[str], int, int]:
    import math
    total_pages = max(1, math.ceil(len(dates) / page_size))
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = start + page_size
    return dates[start:end], page, total_pages


def _custom_word_input_error(text: str, target_lang: str) -> str | None:
    normalized = _normalize_custom_word_input(text)
    if not normalized:
        return "یک واژه یا عبارت کوتاه بفرست."

    if len(normalized) > _CUSTOM_WORD_MAX_CHARS:
        return f"حداکثر {_CUSTOM_WORD_MAX_CHARS} کاراکتر مجاز است."

    words = normalized.split()
    if len(words) > _CUSTOM_WORD_MAX_WORDS:
        return f"فقط یک واژه یا عبارت کوتاهِ حداکثر {_CUSTOM_WORD_MAX_WORDS} کلمه‌ای بفرست."

    if any(len(word) > 25 for word in words):
        return "واژه یا عبارتت خیلی بلند است؛ کوتاه‌تر بفرست."

    if not re.fullmatch(r"[\w\s\u0600-\u06FF'’\-ـ.,؟«»؛،؟]+", normalized):
        return "لطفاً فقط واژه یا عبارت ساده بفرست (علائم محدود مجاز است)."

    has_persian = bool(re.search(r"[\u0600-\u06FF]", normalized))
    has_latin = bool(re.search(r"[A-Za-z]", normalized))

    if not has_persian and not has_latin:
        return "یک واژه یا عبارت واقعی بفرست."

    latin_target = target_lang in {"en", "es", "fr", "de"}

    if latin_target and has_persian and len(words) >= 4:
        return "برای این زبان، عبارت کوتاه‌تری بفرست (حداکثر ۳-۴ کلمه)."

    if latin_target and not has_latin and len(words) > 3:
        return "برای این زبان، عبارت کوتاه‌تری بفرست (حداکثر ۳ کلمه)."

    return None


async def _handle_daily_prepare(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
    *,
    review_mode: bool,
):
    parts = data.split(":")
    if len(parts) != 5:
        await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
        return
    try:
        target_user_id = int(parts[2])
        card_index = int(parts[4])
    except ValueError:
        await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
        return
    user_id = update.effective_user.id
    if user_id != target_user_id:
        await update.callback_query.answer("این کارت برای کاربر دیگری است.", show_alert=True)
        return
    if _message_has_prepared_translations(update):
        await update.callback_query.answer("ترجمه‌ها آماده شده‌اند.")
        return
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.callback_query.answer("ابتدا /start را بزنید.", show_alert=True)
        return
    card_date = parts[3]
    cards = db.get_daily_cards(user_id, card_date)
    if card_index < 0 or card_index >= len(cards):
        await update.callback_query.answer("این کارت دیگر در دسترس نیست.", show_alert=True)
        return
    session = db.get_daily_card_session(user_id, card_date)
    try:
        card = await asyncio.to_thread(
            _prepare_cached_card,
            cards[card_index],
            lang=(session["target_lang"] if session else row["target_lang"]),
            user_id=user_id,
            plan=row["plan"] or "free",
            source="daily_review" if review_mode else "daily",
            persist_patch=lambda patch: db.update_daily_card_fields(
                user_id,
                card_date,
                card_index,
                patch,
            ),
        )
    except CardPreparationError:
        await update.callback_query.answer(
            "این کارت فعلاً با اطمینان آماده نشد؛ بعداً دوباره امتحان کنید.",
            show_alert=True,
        )
        return
    footer = f"📖 کارت {card_index + 1} از {len(cards)} برای {card_date}"
    if review_mode:
        footer = f"📚 مرور کارت {card_index + 1} از {len(cards)} برای {card_date}"
    is_premium = _user_plan(row) in PREMIUM_PLANS
    markup = daily_card_keyboard(
        user_id,
        card_date,
        card_index,
        card_index + 1 < len(cards),
        callback_prefix="review:next" if review_mode else "daily:next",
        show_translations=False,
        show_pronounce=is_premium,
    )
    phon_lines = _phonetic_lines(card.get("phonetic", ""))
    try:
        await _edit_with_retry(
            update.callback_query,
            format_card(
                card,
                footer=footer,
                presentation=_user_presentation(row),
                translations_prepared=True,
                phonetic_lines=phon_lines,
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=markup,
        )
    except BadRequest as exc:
        if "not modified" in str(exc).casefold():
            await _answer_callback_safely(
                update.callback_query,
                "ترجمه‌ها قبلاً آماده شده‌اند.",
            )
        else:
            logger.exception("failed to edit prepared daily card")
            await _answer_callback_safely(
                update.callback_query,
                "نمایش ترجمه‌ها انجام نشد؛ لطفاً دوباره امتحان کنید.",
                show_alert=True,
            )
        return
    await _answer_callback_safely(update.callback_query, "ترجمه‌ها آماده شدند.")


async def _handle_query_prepare(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    token: str,
):
    user_id = update.effective_user.id
    _log_user_activity(update, action="query_translate", outcome="requested")
    if _message_has_prepared_translations(update):
        await update.callback_query.answer("ترجمه‌ها آماده شده‌اند.")
        return
    row = db.get_query_result(token, user_id=user_id)
    if not row:
        await update.callback_query.answer("این نتیجه منقضی شده یا در دسترس نیست.", show_alert=True)
        return
    try:
        card = json.loads(row["result_json"])
    except (TypeError, json.JSONDecodeError):
        card = None
    user_row = db.get_user(user_id)
    if not user_row:
        await update.callback_query.answer("کاربر پیدا نشد.", show_alert=True)
        return
    try:
        card = await asyncio.to_thread(
            _prepare_cached_card,
            card,
            lang=row["lang"],
            user_id=user_id,
            plan=user_row["plan"] or "free",
            source="custom_word",
            persist_patch=lambda patch: db.update_query_result_fields(
                token,
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
        f"{_word_query_usage_text(user_row)}\n\n"
        "برای افزودن این واژه به مرور، از دکمه‌ی زیر استفاده کن."
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
            reply_markup=query_result_keyboard(
                row["token"], row["lang"],
                show_translations=False,
                show_pronounce=_user_plan(user_row) in PREMIUM_PLANS,
            ),
        )
    except BadRequest as exc:
        if "not modified" in str(exc).casefold():
            await _answer_callback_safely(
                update.callback_query,
                "ترجمه‌ها قبلاً آماده شده‌اند.",
            )
        else:
            logger.exception("failed to edit prepared query card")
            await _answer_callback_safely(
                update.callback_query,
                "نمایش ترجمه‌ها انجام نشد؛ لطفاً دوباره امتحان کنید.",
                show_alert=True,
            )
        return
    await _answer_callback_safely(update.callback_query, "ترجمه‌ها آماده شدند.")


async def _show_review_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.callback_query.answer("ابتدا /start را بزنید.", show_alert=True)
        return
    dates = db.get_recent_daily_card_dates(user_id, limit=90)
    if not dates:
        await update.callback_query.answer("هنوز کارتی برای مرور ندارید.", show_alert=True)
        return
    page_dates, page, total_pages = _review_history_page(dates, page)
    await _edit_or_send(
        update,
        context,
        (
            "کدوم روز رو می‌خوای مرور کنی؟"
            if total_pages == 1
            else f"کدوم روز رو می‌خوای مرور کنی؟\nصفحه {page + 1} از {total_pages}"
        ),
        reply_markup=daily_review_dates_keyboard(page_dates, page=page, total_pages=total_pages),
    )
