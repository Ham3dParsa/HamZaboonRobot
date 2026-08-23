import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from services import db
from config.catalog import (
    goal_label,
    language_label,
    level_cefr,
    level_label,
)
from config import (
    OWNER_BYPASS_LIMITS,
    _app_today,
    _user_presentation,
    _user_plan_label,
    daily_word_query_limit_for_plan,
    is_owner,
)
from config.plan_identity import has_feature
from services.utils.formatting import (
    ASK_WORD_PROMPT,
    escape_mdv2,
    word_query_usage_text,
)
from services.utils.callback_notifications import notify_callback
from services.send_pretty import Message, RawFormat, bold, say, send
from services.activity_log import log_user_activity
from services.utils.helpers import (
    _edit_or_send,
    _send_with_retry,
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
)

logger = logging.getLogger(__name__)

_AI_BUSY_MESSAGE = "هوش مصنوعی الان شلوغه؛ کمی بعد دوباره تلاش کن."


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

    log_user_activity(
        update,
        action="start",
        outcome="onboarded" if row and row["onboarded"] else "new",
    )

    if row and row["onboarded"]:
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            "خوش برگشتی به هم‌زبان 👋",
            reply_markup=main_menu(is_owner(user.id)),
        )
        return

    welcome = Message()
    welcome.add_line(
        "سلام! 👋 به ", bold("هم‌زبان"), " خوش اومدی."
    )
    welcome.add_line("اول بگو داری چه زبونی یاد می‌گیری؟")

    await send(
        update.effective_chat.id,
        welcome,
        bot=context.bot,
        keyboard=lang_inline_keyboard(),
    )


async def on_lang_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    log_user_activity(update, action="onboard_lang", outcome=f"lang={lang}")
    context.user_data["pending_lang"] = lang
    lang_name = language_label(lang)

    text = Message()
    text.add_line("زبان انتخابی: ", bold(lang_name), " ✅")
    text.add_line("حالا هدفت از یادگیری چیه؟")

    await say(
        update,
        context,
        text,
        keyboard=goal_inline_keyboard(),
    )


async def on_goal_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, goal: str):
    log_user_activity(update, action="onboard_goal", outcome=f"goal={goal}")
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
    log_user_activity(update, action="onboard_level", outcome=f"level={level}")
    user_id = update.effective_user.id
    db.set_user_level(user_id, level)
    row = db.get_user(user_id)
    lang_name = language_label(row["target_lang"])
    goal_name = goal_label(row["goal"])
    level_name = level_label(level)
    cefr = level_cefr(level)

    text = Message()
    text.add_line("عالی! سطح تو ", bold(level_name), f" ({cefr}) ثبت شد.")

    logger.debug(f"Sending message: {text.render()}")

    await say(
        update,
        context,
        text,
    )
    await _send_with_retry(
        context.bot,
        user_id,
        f"زبان: {lang_name} · هدف: {goal_name}\n"
        "از منوی پایین استفاده کن:",
        reply_markup=main_menu(is_owner(user_id)),
    )


async def change_lang_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_user_activity(update, action="lang_change", outcome="started")
    await _edit_or_send(
        update,
        context,
        "زبان جدید خود را انتخاب کنید:",
        reply_markup=lang_inline_keyboard(back_to_settings=True),
    )
    await notify_callback(update.callback_query)


async def change_goal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_user_activity(update, action="goal_change", outcome="started")
    await _edit_or_send(
        update,
        context,
        "هدف جدید خود را انتخاب کنید:",
        reply_markup=goal_inline_keyboard(back_to_settings=True),
    )
    await notify_callback(update.callback_query)


async def change_level_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_user_activity(update, action="level_change", outcome="started")
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
    if not has_feature(row["plan"] or "free", "presentation"):
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
    log_user_activity(update, action="lang_change", outcome=f"saved: {lang}")
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
    log_user_activity(update, action="goal_change", outcome=f"saved: {goal}")
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
    log_user_activity(update, action="level_change", outcome=f"saved: {level}")
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
    """Retired — grammar tip disabled in prod (#24). Logic archived to
    `docs/archive/retired/grammar_tip_2026-08-23.md`. Keep stub to avoid
    import breakage; future work can restore body from archive."""
    await _send_with_retry(
        context.bot,
        update.effective_chat.id,
        "این قابلیت فعلاً غیرفعال است.",
    )
    log_user_activity(update, action="grammar_tip", outcome="retired")


async def ask_for_ask_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log_user_activity(update, action="word_query", outcome="requested")
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
        f"{usage_text}\n\n{ASK_WORD_PROMPT}",
        reply_markup=awaiting_reply_keyboard(),
    )


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await say(update, context, "اول باید /start رو بزنی.", raw=RawFormat.PLAIN)
        if update.callback_query:
            await notify_callback(update.callback_query)
        return
    due = db.due_words_for_user(user_id, row["target_lang"])
    quota = db.get_quota_status(user_id)
    text = (
        f"🌐 زبان: {language_label(row['target_lang'])}\n"
        f"🎯 هدف: {goal_label(row['goal'])}\n"
        f"📚 سطح: {level_label(row['level'])}\n"
        f"💳 پلن: {_user_plan_label(row)}\n"
        f"📊 پرسش واژه: {_quota_line(quota['word_query'])}\n"
        f"🔥 استریک: {row['streak'] or 0} روز\n"
        f"⏰ واژه‌های آماده‌ی مرور: {len(due)}"
    )
    await say(update, context, text, keyboard=settings_back_keyboard(), raw=RawFormat.PLAIN)
    if update.callback_query:
        await notify_callback(update.callback_query)


async def _show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        if update.callback_query:
            await notify_callback(update.callback_query)
        return
    lang_name = language_label(row["target_lang"])
    goal_name = goal_label(row["goal"])
    level_name = level_label(row["level"])
    await say(
        update,
        context,
        "⚙️ تنظیمات و پروفایل من:\nاز دکمه‌های زیر یکی را انتخاب کن.",
        keyboard=settings_inline_keyboard(lang_name, goal_name, level_name),
        raw=RawFormat.PLAIN,
    )
    if update.callback_query:
        await notify_callback(update.callback_query)


# ---------------- Callback handlers ----------------
