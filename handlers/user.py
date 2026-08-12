import asyncio
import logging
import time

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from services.ai import ai
from services import db
from services import word_query
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
    ASK_WORD_AI_TIMEOUT_SECONDS,
    DEFAULT_PRESENTATION,
    OWNER_BYPASS_LIMITS,
    PLANS,
    PREMIUM_PLANS,
    USER_ACTIVITY,
    _app_today,
    _user_presentation,
    _user_plan_label,
    daily_word_query_limit_for_plan,
    effective_daily_allowance,
    is_owner,
)
from services.utils.formatting import (
    escape_mdv2,
    escape_mdv2_code,
    format_card,
    word_query_usage_text,
    _phonetic_lines,
)
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers import (
    _edit_or_send,
    _edit_with_retry,
    _exit_awaiting_flow,
    _finish_llm_wait_state,
    _is_cancel_input,
    _message_has_prepared_translations,
    _send_with_retry,
    _start_llm_wait_state,
    _user_activity_line,
    _CANCEL_INPUTS,
)
from config.keyboards import (
    main_menu,
    lang_inline_keyboard,
    goal_inline_keyboard,
    level_inline_keyboard,
    presentation_settings_keyboard,
    settings_inline_keyboard,
    settings_back_keyboard,
    awaiting_reply_keyboard,
    awaiting_inline_keyboard,
    query_result_keyboard,
    BTN_ASK_WORD,
    BTN_ADMIN,
    BTN_SETTINGS,
    BTN_CANCEL,
    BTN_BACK,
)
from services.ai.llm_services import _call_ai_limited, _prepare_cached_card

logger = logging.getLogger(__name__)

_AI_BUSY_MESSAGE = "هوش مصنوعی الان شلوغه؛ کمی بعد دوباره تلاش کن."


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


def _quota_line(status: dict) -> str:
    used, limit = status["used"], status["limit"]
    if limit < 0:
        return f"{used} / نامحدود"
    return f"{used}/{limit} (باقی‌مانده {max(limit - used, 0)})"


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
    await _edit_or_send(
        update,
        context,
        "زبان جدید خود را انتخاب کنید:",
        reply_markup=lang_inline_keyboard(back_to_settings=True),
    )
    await notify_callback(update.callback_query)


async def change_goal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_user_activity(update, action="goal_change", outcome="started")
    await _edit_or_send(
        update,
        context,
        "هدف جدید خود را انتخاب کنید:",
        reply_markup=goal_inline_keyboard(back_to_settings=True),
    )
    await notify_callback(update.callback_query)


async def change_level_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _log_user_activity(update, action="level_change", outcome="started")
    await _edit_or_send(
        update,
        context,
        "سطح جدید خود را انتخاب کنید:",
        reply_markup=level_inline_keyboard(back_to_settings=True),
    )
    await notify_callback(update.callback_query)


async def change_presentation_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        await notify_callback(update.callback_query)
        return
    current = _user_presentation(row)
    if (row["plan"] or "free") not in PREMIUM_PLANS:
        await _edit_or_send(
            update,
            context,
            f"نمایش فعلی کارت‌ها: {'خلاصه' if current == 'brief' else 'کامل'}.\n"
            "انتخاب دائمی نمایش کارت فقط برای کاربران پریمیوم فعال است.",
        )
        await notify_callback(update.callback_query)
        return
    await _edit_or_send(
        update,
        context,
        f"نمایش فعلی کارت‌ها: {'خلاصه' if current == 'brief' else 'کامل'}.\n"
        "نمایش موردنظر را انتخاب کنید:",
        reply_markup=presentation_settings_keyboard(current, back_to_settings=True),
    )
    await notify_callback(update.callback_query)


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
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=settings_back_keyboard(),
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
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=settings_back_keyboard(),
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
        reply_markup=settings_back_keyboard(),
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
    deadline = time.monotonic() + ASK_WORD_AI_TIMEOUT_SECONDS
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
            data = await asyncio.wait_for(
                asyncio.to_thread(
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
                    deadline=deadline,
                ),
                timeout=max(0.0, deadline - time.monotonic()),
            )
        except asyncio.TimeoutError:
            db.release_grammar_tip(user_id)
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
                _AI_BUSY_MESSAGE,
            )
            return
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
        delivered = False
        try:
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
                text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            delivered = True
        finally:
            if not delivered:
                db.release_grammar_tip(user_id)
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
    usage_text = word_query_usage_text(row) if row else f"📊 استفاده امروز: 0/{limit}"
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
        await _edit_or_send(update, context, "اول باید /start رو بزنی.")
        await notify_callback(update.callback_query)
        return
    due = db.due_words_for_user(user_id)
    quota = db.get_quota_status(user_id)
    text = (
        f"🌐 زبان: {language_label(row['target_lang'])}\n"
        f"🎯 هدف: {goal_label(row['goal'])}\n"
        f"📚 سطح: {level_label(row['level'])}\n"
        f"💳 پلن: {_user_plan_label(row)}\n"
        f"📊 پرسش واژه: {_quota_line(quota['word_query'])}\n"
        f"💡 نکته گرامری: {_quota_line(quota['grammar_tip'])}\n"
        f"🔥 استریک: {row['streak'] or 0} روز\n"
        f"⏰ واژه‌های آماده‌ی مرور: {len(due)}"
    )
    await _edit_or_send(update, context, text, reply_markup=settings_back_keyboard())
    await notify_callback(update.callback_query)


async def _show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        await notify_callback(update.callback_query)
        return
    lang_name = language_label(row["target_lang"])
    goal_name = goal_label(row["goal"])
    level_name = level_label(row["level"])
    await _edit_or_send(
        update,
        context,
        "⚙️ تنظیمات و پروفایل من:\nاز دکمه‌های زیر یکی را انتخاب کن.",
        reply_markup=settings_inline_keyboard(lang_name, goal_name, level_name),
    )
    await notify_callback(update.callback_query)


# ---------------- Callback handlers ----------------


async def _handle_query_prepare(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    token: str,
):
    user_id = update.effective_user.id
    _log_user_activity(update, action="query_translate", outcome="requested")
    if _message_has_prepared_translations(update):
        await notify_callback(update.callback_query, "ترجمه‌ها آماده شده‌اند.", intent=CallbackNoticeIntent.SUCCESS)
        return

    async def prepare_card(card, **kwargs):
        return await asyncio.to_thread(_prepare_cached_card, card, **kwargs)

    result = await word_query.prepare(
        token,
        user_id,
        prepare_card=prepare_card,
    )
    if result.kind == "expired":
        await notify_callback(update.callback_query, "این نتیجه منقضی شده یا در دسترس نیست.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if result.kind == "not_found":
        await notify_callback(update.callback_query, "کاربر پیدا نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if result.kind == "card_prep_error":
        await notify_callback(update.callback_query, "این کارت فعلاً با اطمینان آماده نشد؛ بعداً دوباره امتحان کنید.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    user_row = result.user_row
    footer = (
        f"{word_query_usage_text(user_row)}\n\n"
        "برای افزودن این واژه به مرور، از دکمه‌ی زیر استفاده کن."
    )
    phon_lines = _phonetic_lines(result.card_data.get("phonetic", ""))
    context.user_data[f"query_kb_{result.token}"] = {
        "show_translations": False,
        "show_pronounce": result.show_pronounce,
    }
    try:
        await _edit_with_retry(
            update.callback_query,
            format_card(
                result.card_data,
                footer=footer,
                presentation=_user_presentation(user_row),
                translations_prepared=True,
                phonetic_lines=phon_lines,
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=query_result_keyboard(
                result.token, result.lang,
                show_translations=False,
                show_pronounce=result.show_pronounce,
                saved=result.saved,
            ),
        )
    except BadRequest as exc:
        if "not modified" in str(exc).casefold():
            await notify_callback(
                update.callback_query,
                "ترجمه‌ها قبلاً آماده شده‌اند.",
                intent=CallbackNoticeIntent.INFO,
            )
        else:
            logger.exception("failed to edit prepared query card")
            await notify_callback(
                update.callback_query,
                "نمایش ترجمه‌ها انجام نشد؛ لطفاً دوباره امتحان کنید.",
                intent=CallbackNoticeIntent.IMPORTANT_ERROR,
            )
        return
    await notify_callback(update.callback_query, "ترجمه‌ها آماده شدند.", intent=CallbackNoticeIntent.SUCCESS)
