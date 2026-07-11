import logging
import datetime
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import (
    BOT_TOKEN,
    OWNER_ID,
    FREE_DAILY_WORD_LIMIT,
    DAILY_SEND_HOUR,
    SRS_SEND_HOUR,
    SUPPORTED_LANGS,
    GOALS,
    LEVELS,
    LEVEL_CEFR,
    daily_card_count_for_plan,
)
import db
import ai
import prompts
from keyboards import (
    main_menu,
    lang_inline_keyboard,
    goal_inline_keyboard,
    level_inline_keyboard,
    admin_panel_keyboard,
    BTN_TODAY_CARD,
    BTN_ADD_WORD,
    BTN_ASK_WORD,
    BTN_STATUS,
    BTN_GRAMMAR,
    BTN_ADMIN,
    BTN_CHANGE_LANG,
    BTN_CHANGE_GOAL,
    BTN_CHANGE_LEVEL,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hamzaban")

def escape_mdv2(text: str) -> str:
    """Escape کامل‌تر برای MarkdownV2"""
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([' + re.escape(special) + r'])', r'\\\1', text)

def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID


def format_card(data: dict, footer: str = "") -> str:
    word = escape_mdv2(data.get("word", ""))
    phon = escape_mdv2(data.get("phonetic", ""))
    fa_meaning = escape_mdv2(data.get("fa_meaning", ""))
    fa_expl = escape_mdv2(data.get("fa_explanation", ""))
    
    syn_list = [escape_mdv2(s) for s in (data.get("synonyms") or [])]
    ant_list = [escape_mdv2(s) for s in (data.get("antonyms") or [])]
    syn = "، ".join(syn_list) or "—"
    ant = "، ".join(ant_list) or "—"
    
    examples = data.get("examples") or []
    ex_text = "\n".join(f"• {escape_mdv2(e)}" for e in examples) if examples else ""
    
    grammar_tip = escape_mdv2(data.get("grammar_tip", ""))

    lines = [f"*{word}*"]  # کلمه اصلی

    if phon:
        lines.append(f"`{phon}`")

    lines.append(f"\n🇮🇷 *{fa_meaning}*")
    
    if fa_expl:
        lines.append(f"_{fa_expl}_")
    
    lines.append(f"\n🟢 *مترادف:* {syn}")
    lines.append(f"🔴 *متضاد:* {ant}")
    
    if ex_text:
        lines.append(f"\n*مثال‌ها:*\n{ex_text}")
    
    if grammar_tip:
        lines.append(f"\n✍️ *نکته‌ی گرامری:*\n{grammar_tip}")
    
    if footer:
        lines.append(f"\n{escape_mdv2(footer)}")
    
    return "\n".join(lines)


# ---------------- /start و onboarding ----------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.create_user_if_needed(user.id, user.username or user.first_name or "")
    row = db.get_user(user.id)
    
    if row and row["onboarded"]:
        await update.message.reply_text(
            "خوش برگشتی به هم‌زبان 👋",
            reply_markup=main_menu(is_owner(user.id))
        )
        return
    
    welcome_text = "سلام! 👋 به *هم‌زبان* خوش اومدی.\nاول بگو داری چه زبونی یاد می‌گیری؟"
    welcome_text = escape_mdv2(welcome_text)   # ← حتما escape شود
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=lang_inline_keyboard(),
    )


async def on_lang_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    context.user_data["pending_lang"] = lang
    lang_name = SUPPORTED_LANGS.get(lang, lang)
    text = f"زبان انتخابی: *{lang_name}* ✅\nحالا هدفت از یادگیری چیه؟"
    text = escape_mdv2(text)
    
    await update.callback_query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=goal_inline_keyboard(),
    )


async def on_goal_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, goal: str):
    user_id = update.effective_user.id
    lang = context.user_data.get("pending_lang", "en")
    db.set_user_lang_goal(user_id, lang, goal)

    await update.callback_query.edit_message_text(
        "حالا سطح فعلی زبانت را انتخاب کن:",
        reply_markup=level_inline_keyboard(),
    )


async def on_level_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, level: str):
    user_id = update.effective_user.id
    db.set_user_level(user_id, level)
    row = db.get_user(user_id)
    lang_name = SUPPORTED_LANGS.get(row["target_lang"], row["target_lang"])
    goal_name = GOALS.get(row["goal"], row["goal"])
    level_name = LEVELS.get(level, level)
    cefr = LEVEL_CEFR.get(level, "")

    await update.callback_query.edit_message_text(
        f"عالی! سطح تو *{escape_mdv2(level_name)}* \\({escape_mdv2(cefr)}\\) ثبت شد\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"زبان: {lang_name} · هدف: {goal_name}\n"
            "از منوی پایین استفاده کن:"
        ),
        reply_markup=main_menu(is_owner(user_id)),
    )


async def change_lang_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "زبان جدید خود را انتخاب کنید:",
        reply_markup=lang_inline_keyboard()
    )

async def change_goal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "هدف جدید خود را انتخاب کنید:",
        reply_markup=goal_inline_keyboard()
    )


async def change_level_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سطح جدید خود را انتخاب کنید:",
        reply_markup=level_inline_keyboard(),
    )


async def on_lang_changed(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    user_id = update.effective_user.id
    db.set_user_lang(user_id, lang)
    
    lang_name = SUPPORTED_LANGS.get(lang, lang)
    # متن کامل را اول بسازیم سپس escape کنیم
    text = f"✅ زبان با موفقیت به *{lang_name}* تغییر کرد."
    text = escape_mdv2(text)
    
    await update.callback_query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await context.bot.send_message(
        chat_id=user_id,
        text="از منوی پایین استفاده کنید:",
        reply_markup=main_menu(is_owner(user_id))
    )


async def on_goal_changed(update: Update, context: ContextTypes.DEFAULT_TYPE, goal: str):
    user_id = update.effective_user.id
    db.set_user_goal(user_id, goal)
    
    goal_name = GOALS.get(goal, goal)
    text = f"✅ هدف با موفقیت به *{goal_name}* تغییر کرد."
    text = escape_mdv2(text)
    
    await update.callback_query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await context.bot.send_message(
        chat_id=user_id,
        text="از منوی پایین استفاده کنید:",
        reply_markup=main_menu(is_owner(user_id))
    )


async def on_level_changed(update: Update, context: ContextTypes.DEFAULT_TYPE, level: str):
    user_id = update.effective_user.id
    db.set_user_level(user_id, level)
    level_name = LEVELS.get(level, level)
    cefr = LEVEL_CEFR.get(level, "")
    text = f"✅ سطح با موفقیت به *{level_name}* ({cefr}) تغییر کرد."
    await update.callback_query.edit_message_text(
        escape_mdv2(text),
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await context.bot.send_message(
        chat_id=user_id,
        text="از منوی پایین استفاده کنید:",
        reply_markup=main_menu(is_owner(user_id)),
    )


# ---------------- دکمه‌های اصلی ----------------

def _generate_unique_card(
    lang: str,
    goal: str,
    level: str,
    used_words,
    retries: int = 2,
) -> dict:
    """یک کارت روزانه می‌سازد و اگر واژه‌اش تکراری بود چند بار دوباره تلاش می‌کند."""
    used_norm = {str(w).strip().lower() for w in (used_words or []) if w}
    data = {}
    for _ in range(retries + 1):
        data = ai.ask_card(
            prompts.daily_card_system_prompt(
                lang,
                goal,
                level=level,
                avoid_words=used_words,
            )
        )
        word = str(data.get("word", "")).strip().lower()
        if word and word not in used_norm:
            return data
    return data


async def send_daily_card_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.message.reply_text("اول باید /start رو بزنی.")
        return

    today = datetime.date.today().isoformat()
    plan = row["plan"] or "free"
    limit = daily_card_count_for_plan(plan)

    # کارت‌های امروز از قبل تولید شده‌اند؟ اگر بله، به‌جای فراخوانی دوباره‌ی API
    # همان‌ها را برای مرور نشان می‌دهیم. مکان‌نمای مرور در حافظه‌ی همان روز نگه داشته می‌شود.
    cards = db.get_daily_cards(user_id, today)

    if context.user_data.get("daily_cursor_date") != today:
        context.user_data["daily_cursor_date"] = today
        context.user_data["daily_cursor"] = 0
    cursor = context.user_data.get("daily_cursor", 0)

    # ۱) هنوز کارتی از امروز برای دیدن باقی مانده → از کش نشان بده (بدون هزینه‌ی API)
    if cursor < len(cards):
        data = cards[cursor]
        context.user_data["daily_cursor"] = cursor + 1
        footer = f"📖 مرور کارت {cursor + 1} از {len(cards)} امروز"
        await update.message.reply_text(
            format_card(data, footer=footer),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # ۲) به سقف پلن رسیده‌ای → کارت جدید تولید نکن، از اول مرور کن
    if len(cards) >= limit:
        if not cards:
            await update.message.reply_text("امروز کارتی برای نمایش نیست.")
            return
        data = cards[0]
        context.user_data["daily_cursor"] = 1
        footer = (
            f"✅ کارت‌های امروزت ({limit} کارت) کامل شده؛ این‌ها را مرور کن.\n"
            f"📖 مرور کارت ۱ از {len(cards)}"
        )
        await update.message.reply_text(
            format_card(data, footer=footer),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # ۳) هنوز ظرفیت داری → یک کارت جدید (غیرتکراری) بساز، ذخیره کن و نشان بده
    used_words = [c.get("word", "") for c in cards]
    await update.message.chat.send_action("typing")
    try:
        data = _generate_unique_card(
            row["target_lang"],
            row["goal"],
            row["level"],
            used_words,
        )
    except Exception:
        log.exception("AI error")
        await update.message.reply_text("مشکلی در ارتباط با هوش مصنوعی پیش اومد.")
        return

    new_index = len(cards)
    db.add_daily_card(user_id, today, new_index, data)
    context.user_data["daily_cursor"] = new_index + 1

    streak = db.touch_streak(user_id)
    footer = f"🔥 استریک: {streak} روز  ·  کارت {new_index + 1} از {limit}"
    await update.message.reply_text(
        format_card(data, footer=footer),
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def send_grammar_tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.message.reply_text("اول باید /start رو بزنی.")
        return

    await update.message.chat.send_action("typing")
    try:
        data = ai.ask_json(
            prompts.grammar_tip_system_prompt(
                row["target_lang"],
                row["goal"],
                row["level"],
            )
        )
    except Exception:
        log.exception("AI error")
        await update.message.reply_text("مشکلی در ارتباط با هوش مصنوعی پیش اومد، دوباره امتحان کن.")
        return

    # ساخت متن با escape مناسب برای MarkdownV2
    title = escape_mdv2(data.get('title', ''))
    explanation = escape_mdv2(data.get('explanation', ''))
    example = escape_mdv2(data.get('example', ''))

    text = f"✍️ *{title}*\n\n{explanation}\n\n`{example}`"   # مثال را در کد قرار دادیم

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def ask_for_add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting"] = "add_word"
    await update.message.reply_text("واژه‌ای که می‌خوای یادت بمونه رو بفرست:")


async def ask_for_ask_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.can_ask_word(user_id, FREE_DAILY_WORD_LIMIT):
        await update.message.reply_text(
            f"سقف روزانه‌ی پرسش واژه‌ی رایگان ({FREE_DAILY_WORD_LIMIT} بار) تموم شده. "
            "برای پرسش نامحدود، پلن نقره‌ای یا طلایی رو فعال کن."
        )
        return
    context.user_data["awaiting"] = "ask_word"
    await update.message.reply_text("چه واژه یا عبارتی رو می‌خوای معنی/توضیح بدم؟")


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.message.reply_text("اول باید /start رو بزنی.")
        return
    due = db.due_words_for_user(user_id)
    text = (
        f"🌐 زبان: {SUPPORTED_LANGS.get(row['target_lang'], row['target_lang'])}\n"
        f"🎯 هدف: {GOALS.get(row['goal'], row['goal'])}\n"
        f"📚 سطح: {LEVELS.get(row['level'], row['level'])} ({LEVEL_CEFR.get(row['level'], '')})\n"
        f"💳 پلن: {row['plan']}\n"
        f"🔥 استریک: {row['streak'] or 0} روز\n"
        f"⏰ واژه‌های آماده‌ی مرور: {len(due)}"
    )
    await update.message.reply_text(text)


# ---------------- پنل ادمین (فقط مالک) ----------------

async def open_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text("پنل مدیریت ربات:", reply_markup=admin_panel_keyboard())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    if not is_owner(update.effective_user.id):
        await update.callback_query.answer("فقط مالک ربات دسترسی داره.", show_alert=True)
        return
    q = update.callback_query
    if action == "stats":
        await q.edit_message_text(f"👥 تعداد کل کاربران: {db.count_users()}")
    elif action == "set_model":
        context.user_data["awaiting"] = "admin_set_model"
        await q.edit_message_text(
            f"نام مدل فعلی: `{db.get_setting('ai_model')}`\nنام مدل جدید رو بفرست:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    elif action == "set_base_url":
        context.user_data["awaiting"] = "admin_set_base_url"
        await q.edit_message_text(
            f"Base URL فعلی: `{db.get_setting('ai_base_url')}`\nBase URL جدید رو بفرست:",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    elif action == "set_api_key":
        context.user_data["awaiting"] = "admin_set_api_key"
        await q.edit_message_text("API Key جدید رو بفرست (بعداً این پیام رو از چت پاک کن):")
    elif action == "broadcast":
        context.user_data["awaiting"] = "admin_broadcast"
        await q.edit_message_text("متن پیام همگانی رو بفرست:")
    elif action == "show_settings":
        key = db.get_setting("ai_api_key", "")
        masked = (key[:6] + "…" + key[-4:]) if len(key) > 12 else "—"
        await q.edit_message_text(
            f"🤖 مدل: `{db.get_setting('ai_model')}`\n"
            f"🌐 Base URL: `{db.get_setting('ai_base_url')}`\n"
            f"🔑 API Key: `{masked}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ---------------- روتر پیام‌های متنی (منو + حالت‌های در انتظار ورودی) ----------------

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    awaiting = context.user_data.get("awaiting")

    if awaiting:
        context.user_data["awaiting"] = None

        if awaiting.startswith("admin_") and not is_owner(user_id):
            return  # لایه‌ی امنیتی اضافه؛ در حالت عادی اصلاً به این حالت نمی‌رسد

        if awaiting == "add_word":
            row = db.get_user(user_id)
            db.add_saved_word(user_id, text, row["target_lang"] if row else "en")
            await update.message.reply_text(f"واژه‌ی «{text}» ثبت شد؛ سر وقتش برات یادآوری می‌کنم. ✅")
            return

        if awaiting == "ask_word":
            row = db.get_user(user_id)
            await update.message.chat.send_action("typing")
            try:
                data = ai.ask_card(
                    prompts.custom_word_system_prompt(
                        row["target_lang"],
                        row["level"],
                    ),
                    user_prompt=text,
                )
            except Exception:
                log.exception("AI error")
                await update.message.reply_text("مشکلی در ارتباط با هوش مصنوعی پیش اومد، دوباره امتحان کن.")
                return
            db.increment_word_ask(user_id)
            await update.message.reply_text(format_card(data), parse_mode=ParseMode.MARKDOWN_V2)
            return

        if awaiting == "admin_set_model":
            db.set_setting("ai_model", text)
            await update.message.reply_text(f"مدل جدید ثبت شد: `{text}`", parse_mode=ParseMode.MARKDOWN_V2)
            return

        if awaiting == "admin_set_base_url":
            db.set_setting("ai_base_url", text)
            await update.message.reply_text(f"Base URL جدید ثبت شد: `{text}`", parse_mode=ParseMode.MARKDOWN_V2)
            return

        if awaiting == "admin_set_api_key":
            db.set_setting("ai_api_key", text)
            await update.message.reply_text("API Key جدید ثبت شد. ✅")
            return

        if awaiting == "admin_broadcast":
            users = db.all_active_users()
            sent = 0
            for u in users:
                try:
                    await context.bot.send_message(chat_id=u["user_id"], text=text)
                    sent += 1
                except Exception:
                    pass
            await update.message.reply_text(f"پیام برای {sent} کاربر ارسال شد.")
            return

    # مسیر دکمه‌های منوی اصلی
    if text == BTN_TODAY_CARD:
        await send_daily_card_now(update, context)
    elif text == BTN_GRAMMAR:
        await send_grammar_tip(update, context)
    elif text == BTN_ADD_WORD:
        await ask_for_add_word(update, context)
    elif text == BTN_ASK_WORD:
        await ask_for_ask_word(update, context)
    elif text == BTN_STATUS:
        await show_status(update, context)
    elif text == BTN_ADMIN:
        await open_admin_panel(update, context)
    elif text == BTN_CHANGE_LANG:
        await change_lang_start(update, context)
    elif text == BTN_CHANGE_GOAL:
        await change_goal_start(update, context)
    elif text == BTN_CHANGE_LEVEL:
        await change_level_start(update, context)
    else:
        await update.message.reply_text("از دکمه‌های پایین استفاده کن 🙂", reply_markup=main_menu(is_owner(user_id)))


# ---------------- روتر callback query ها ----------------

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    await update.callback_query.answer()
    
    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        row = db.get_user(update.effective_user.id)
        if row and row["onboarded"]:
            await on_lang_changed(update, context, lang)      # تغییر زبان
        else:
            await on_lang_selected(update, context, lang)     # onboarding
    elif data.startswith("goal:"):
        goal = data.split(":", 1)[1]
        row = db.get_user(update.effective_user.id)
        if row and row["onboarded"]:
            await on_goal_changed(update, context, goal)      # تغییر هدف
        else:
            await on_goal_selected(update, context, goal)     # onboarding
    elif data.startswith("level:"):
        level = data.split(":", 1)[1]
        if level not in LEVELS:
            await update.callback_query.answer("سطح نامعتبر است.", show_alert=True)
            return
        row = db.get_user(update.effective_user.id)
        if row and row["onboarded"]:
            await on_level_changed(update, context, level)
        else:
            await on_level_selected(update, context, level)
    elif data.startswith("admin:"):
        await admin_callback(update, context, data.split(":", 1)[1])


# ---------------- ارسال روزانه‌ی خودکار ----------------

async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today().isoformat()
    for row in db.all_active_users():
        user_id = row["user_id"]
        try:
            # اگر امروز کارت خودکار قبلاً ساخته شده، دوباره از API نگیر.
            if db.count_daily_cards(user_id, today) > 0:
                continue
            data = ai.ask_card(
                prompts.daily_card_system_prompt(
                    row["target_lang"],
                    row["goal"],
                    level=row["level"],
                )
            )
            db.add_daily_card(user_id, today, 0, data)
            streak = db.touch_streak(user_id)
            await context.bot.send_message(
                chat_id=user_id,
                text=format_card(data, footer=f"🔥 استریک: {streak} روز"),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            log.exception(f"daily_job failed for user {user_id}")


async def srs_job(context: ContextTypes.DEFAULT_TYPE):
    """یادآوری واژه‌های ذخیره‌شده‌ی سررسیدشده (مرور فاصله‌دار)."""
    for row in db.all_active_users():
        user_id = row["user_id"]
        try:
            due = db.due_words_for_user(user_id)
            if not due:
                continue
            words = "\n".join(f"• {escape_mdv2(w['word'])}" for w in due)
            text = (
                f"⏰ *وقت مرور {len(due)} واژه‌ست:*\n\n{words}\n\n"
                "سعی کن معنی هرکدوم رو یادت بیاری، بعد چک کن\\."
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            for w in due:
                db.advance_word_review(w["id"])
        except Exception:
            log.exception(f"srs_job failed for user {user_id}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled exception while processing update", exc_info=context.error)


def main():
    db.init_db()
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN در .env تنظیم نشده.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(error_handler)

    if app.job_queue:
        app.job_queue.run_daily(daily_job, time=datetime.time(hour=DAILY_SEND_HOUR, minute=0))
        app.job_queue.run_daily(srs_job, time=datetime.time(hour=SRS_SEND_HOUR, minute=0))

    log.info("ربات هم‌زبان استارت شد.")
    app.run_polling()


if __name__ == "__main__":
    main()
