import asyncio
import logging
import datetime
import re
import time
import threading
from collections import defaultdict, deque

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
    DEFAULT_ACTIVE_START_MINUTE,
    DEFAULT_ACTIVE_END_MINUTE,
    DEFAULT_PREFERRED_DELIVERY_MINUTE,
    MIN_SESSIONS,
    MAX_SESSIONS,
    TARGET_CARDS_PER_SESSION,
    SCHEDULER_SLOT_MINUTES,
    SCHEDULER_BUCKET_CAPACITY,
    AI_MAX_CONCURRENCY,
    AI_MAX_REQUESTS_PER_MINUTE,
    TELEGRAM_MAX_CONCURRENCY,
    SESSION_CARD_DELAY_SECONDS,
    PLANS,
    OWNER_BYPASS_LIMITS,
    daily_card_count_for_plan,
    effective_daily_allowance,
    effective_plan,
)
import db
import ai
import prompts
from catalog import LEVELS, goal_label, language_label, level_cefr, level_label
from scheduling import plan_sessions
from telegram.error import NetworkError, RetryAfter, TimedOut
from keyboards import (
    main_menu,
    lang_inline_keyboard,
    goal_inline_keyboard,
    level_inline_keyboard,
    admin_panel_keyboard,
    daily_card_keyboard,
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
_daily_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_ai_slots = threading.BoundedSemaphore(AI_MAX_CONCURRENCY)
_ai_request_times: deque[float] = deque()
_ai_request_lock = threading.Lock()
_telegram_slots = asyncio.Semaphore(TELEGRAM_MAX_CONCURRENCY)


def _ask_batch_limited(*args, **kwargs):
    _ai_slots.acquire()
    try:
        while True:
            now = time.monotonic()
            with _ai_request_lock:
                while _ai_request_times and now - _ai_request_times[0] >= 60:
                    _ai_request_times.popleft()
                if len(_ai_request_times) < AI_MAX_REQUESTS_PER_MINUTE:
                    _ai_request_times.append(now)
                    break
            time.sleep(0.25)
        return ai.ask_batch(*args, **kwargs)
    finally:
        _ai_slots.release()

def escape_mdv2(text: str) -> str:
    """Escape کامل‌تر برای MarkdownV2"""
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([' + re.escape(special) + r'])', r'\\\1', text)

def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID


def _user_plan(row) -> str:
    return effective_plan(row["plan"] or "free", OWNER_BYPASS_LIMITS and is_owner(row["user_id"]))


def _user_plan_label(row) -> str:
    actual = PLANS.get(row["plan"] or "free", row["plan"] or "free")
    if OWNER_BYPASS_LIMITS and is_owner(row["user_id"]):
        return f"{actual} (دسترسی مالک)"
    return actual


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
    lang_name = language_label(lang)
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
    lang_name = language_label(row["target_lang"])
    goal_name = goal_label(row["goal"])
    level_name = level_label(level)
    cefr = level_cefr(level)

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
    
    lang_name = language_label(lang)
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
    
    goal_name = goal_label(goal)
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
    level_name = level_label(level)
    cefr = level_cefr(level)
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

def _generate_daily_batch(
    lang: str,
    goal: str,
    level: str,
    card_count: int,
    used_words: list[str],
) -> list[dict]:
    cards: list[dict] = []
    last_error: Exception | None = None
    for _ in range(3):
        remaining = card_count - len(cards)
        if remaining <= 0:
            break
        batch_words = used_words + [card["word"] for card in cards]
        try:
            batch = _ask_batch_limited(
                prompts.daily_batch_system_prompt(
                    lang,
                    goal,
                    level,
                    remaining,
                    avoid_words=batch_words,
                ),
                expected_count=remaining,
                used_words=batch_words,
            )
        except Exception as exc:
            last_error = exc
            continue
        if not batch:
            continue
        cards.extend(batch)

    if not cards and last_error:
        raise last_error
    return cards


def _ensure_daily_cards(user_id: int, row, card_date: str, limit: int) -> list[dict]:
    cards = db.get_daily_cards(user_id, card_date)
    if len(cards) >= limit:
        return cards

    used_words = [str(card.get("word", "")) for card in cards]
    new_cards = _generate_daily_batch(
        row["target_lang"],
        row["goal"],
        row["level"],
        limit - len(cards),
        used_words,
    )
    for offset, card in enumerate(new_cards):
        db.add_daily_card(user_id, card_date, len(cards) + offset, card)
    return db.get_daily_cards(user_id, card_date)


def _ensure_scheduled_session_cards(user_id: int, row, queue_row) -> list[dict]:
    existing = db.get_daily_cards(user_id, queue_row["delivery_date"])
    start = queue_row["card_start_index"]
    end = start + queue_row["card_count"]
    if len(existing) >= end:
        return existing[start:end]

    used_words = [str(card.get("word", "")) for card in existing]
    cards: list[dict] = []
    while len(existing) + len(cards) < end:
        remaining = end - len(existing) - len(cards)
        batch = _generate_daily_batch(
            row["target_lang"],
            row["goal"],
            row["level"],
            min(6, remaining),
            used_words + [card["word"] for card in cards],
        )
        if not batch:
            raise RuntimeError("AI returned no cards for the scheduled session")
        cards.extend(batch)
    for offset, card in enumerate(cards):
        db.add_daily_card(user_id, queue_row["delivery_date"], len(existing) + offset, card)
    return db.get_daily_cards(user_id, queue_row["delivery_date"])[start:end]


def _ensure_next_daily_card(user_id: int, row, card_date: str, limit: int) -> tuple[dict | None, int]:
    next_index = db.get_daily_progress(user_id, card_date)
    if next_index >= limit:
        return None, next_index

    cards = db.get_daily_cards(user_id, card_date)
    if next_index >= len(cards):
        used_words = [str(card.get("word", "")) for card in cards]
        new_cards = _generate_daily_batch(
            row["target_lang"],
            row["goal"],
            row["level"],
            1,
            used_words,
        )
        if not new_cards:
            raise RuntimeError("AI returned no card for the requested daily card")
        db.add_daily_card(user_id, card_date, len(cards), new_cards[0])
        cards = db.get_daily_cards(user_id, card_date)

    card = cards[next_index]
    db.set_daily_progress(user_id, card_date, next_index + 1)
    return card, next_index


async def _send_next_daily_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    row,
    card_date: str,
    limit: int,
):
    user_id = row["user_id"]
    async with _daily_locks[user_id]:
        card, card_index = await asyncio.to_thread(
            _ensure_next_daily_card,
            user_id,
            row,
            card_date,
            limit,
        )

    if card is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ سهمیه‌ی امروزت ({limit} کارت) کامل شده است.",
        )
        return

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=format_card(
            card,
            footer=f"📖 کارت {card_index + 1} از {limit} امروز",
        ),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=daily_card_keyboard(
            user_id,
            card_date,
            card_index,
            card_index + 1 < limit,
        ),
    )


async def send_daily_card_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.message.reply_text("اول باید /start رو بزنی.")
        return

    today = datetime.date.today().isoformat()
    plan = _user_plan(row)
    limit = effective_daily_allowance(
        row["plan"] or "free",
        row["optional_daily_limit"],
        OWNER_BYPASS_LIMITS and is_owner(user_id),
    )

    await update.message.chat.send_action("typing")
    try:
        await _send_next_daily_card(update, context, row, today, limit)
    except Exception:
        log.exception("Daily card generation failed")
        await update.message.reply_text("مشکلی در ساخت کارت‌های امروز پیش اومد.")

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
    if not db.can_ask_word(
        user_id,
        FREE_DAILY_WORD_LIMIT,
        bypass_limits=OWNER_BYPASS_LIMITS and is_owner(user_id),
    ):
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
        f"🌐 زبان: {language_label(row['target_lang'])}\n"
        f"🎯 هدف: {goal_label(row['goal'])}\n"
        f"📚 سطح: {level_label(row['level'])}\n"
        f"💳 پلن: {_user_plan_label(row)}\n"
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
    elif action == "set_plan":
        context.user_data["awaiting"] = "admin_set_plan"
        await q.edit_message_text(
            "فرمت را ارسال کنید:\n`user_id_or_username plan`\n\n"
            "مثال: `123456789 silver` یا `@username gold`\n"
            "پلن‌ها: free، silver، gold",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
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

        if awaiting == "admin_set_plan":
            parts = text.split()
            if len(parts) != 2 or parts[1].lower() not in PLANS:
                await update.message.reply_text(
                    "فرمت نامعتبر است. نمونه: `123456789 silver` یا `@username gold`",
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                return
            target = db.find_user(parts[0])
            if not target:
                await update.message.reply_text("کاربر پیدا نشد؛ ابتدا باید کاربر /start را زده باشد.")
                return
            plan = parts[1].lower()
            previous_plan = target["plan"] or "free"
            db.set_plan(target["user_id"], plan)
            await update.message.reply_text(
                f"پلن کاربر {target['user_id']} از {PLANS.get(previous_plan, previous_plan)} "
                f"به {PLANS[plan]} تغییر کرد."
            )
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
    elif data.startswith("daily:next:"):
        parts = data.split(":")
        if len(parts) != 5:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        target_user_id_text, card_date, current_index_text = parts[2], parts[3], parts[4]
        today = datetime.date.today().isoformat()
        if card_date != today:
            await update.callback_query.answer("این کارت مربوط به روز گذشته است.", show_alert=True)
            return
        try:
            target_user_id = int(target_user_id_text)
            current_index = int(current_index_text)
        except ValueError:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return

        user_id = update.effective_user.id
        if user_id != target_user_id:
            await update.callback_query.answer("این کارت برای کاربر دیگری است.", show_alert=True)
            return
        row = db.get_user(user_id)
        if not row or not row["onboarded"]:
            await update.callback_query.answer("ابتدا /start را بزنید.", show_alert=True)
            return
        if db.get_daily_progress(user_id, today) != current_index + 1:
            await update.callback_query.answer("این دکمه قبلاً استفاده شده است.", show_alert=True)
            return

        limit = effective_daily_allowance(
            row["plan"] or "free",
            row["optional_daily_limit"],
            OWNER_BYPASS_LIMITS and is_owner(user_id),
        )
        await update.callback_query.answer()
        try:
            await _send_next_daily_card(update, context, row, today, limit)
        except Exception:
            log.exception("Next daily card generation failed")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="مشکلی در ساخت کارت بعدی پیش اومد.",
            )
    elif data.startswith("admin:"):
        await admin_callback(update, context, data.split(":", 1)[1])


# ---------------- ارسال روزانه‌ی خودکار ----------------

def _plan_daily_queue(delivery_date: str):
    loads: dict[int, int] = defaultdict(int)
    for row in db.all_active_users():
        user_id = row["user_id"]
        if db.delivery_queue_for_user(user_id, delivery_date):
            continue
        limit = effective_daily_allowance(
            row["plan"] or "free",
            row["optional_daily_limit"],
            OWNER_BYPASS_LIMITS and is_owner(user_id),
        )
        preferred = row["preferred_delivery_minute"] or DEFAULT_PREFERRED_DELIVERY_MINUTE
        start = row["active_window_start_minute"]
        end = row["active_window_end_minute"]
        sessions = plan_sessions(
            limit,
            preferred,
            DEFAULT_ACTIVE_START_MINUTE if start is None else start,
            DEFAULT_ACTIVE_END_MINUTE if end is None else end,
            slot_minutes=SCHEDULER_SLOT_MINUTES,
            bucket_capacity=SCHEDULER_BUCKET_CAPACITY,
            min_sessions=MIN_SESSIONS,
            max_sessions=MAX_SESSIONS,
            target_cards_per_session=TARGET_CARDS_PER_SESSION,
            bucket_loads=loads,
        )
        for session in sessions:
            loads[session.planned_minute] += 1
        db.enqueue_delivery_sessions(user_id, delivery_date, sessions)


async def _send_with_retry(bot, chat_id: int, text: str):
    for attempt in range(3):
        try:
            async with _telegram_slots:
                return await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), 30))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(2**attempt)


async def _dispatch_queue(context: ContextTypes.DEFAULT_TYPE, delivery_date: str):
    now = datetime.datetime.utcnow().isoformat()
    for queue_row in db.get_delivery_queue(delivery_date):
        if queue_row["planned_for"] > now:
            continue
        claimed = db.claim_delivery_queue(queue_row["id"])
        if not claimed:
            continue
        user_id = claimed["user_id"]
        try:
            row = db.get_user(user_id)
            if not row:
                raise RuntimeError("user no longer exists")
            async with _daily_locks[user_id]:
                cards = await asyncio.to_thread(
                    _ensure_scheduled_session_cards,
                    user_id,
                    row,
                    claimed,
                )
            limit = effective_daily_allowance(
                row["plan"] or "free",
                row["optional_daily_limit"],
                OWNER_BYPASS_LIMITS and is_owner(user_id),
            )
            streak = db.touch_streak(user_id)
            for offset, card in enumerate(cards[claimed["sent_count"] :], start=claimed["sent_count"]):
                await _send_with_retry(
                    context.bot,
                    user_id,
                    format_card(
                        card,
                        footer=(
                            f"🔥 استریک: {streak} روز  · جلسه "
                            f"{claimed['session_index'] + 1} · کارت "
                            f"{claimed['card_start_index'] + offset + 1} از {limit}"
                        ),
                    ),
                )
                db.advance_delivery_progress(claimed["id"], offset + 1)
                if offset + 1 < len(cards):
                    await asyncio.sleep(SESSION_CARD_DELAY_SECONDS)
            db.mark_delivery_sent(claimed["id"])
        except Exception as exc:
            db.mark_delivery_failed(claimed["id"], repr(exc))
            log.exception("scheduled delivery failed for user %s", user_id)


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.date.today().isoformat()
    stale_before = (datetime.datetime.utcnow() - datetime.timedelta(minutes=15)).isoformat()
    db.requeue_stale_deliveries(stale_before)
    await asyncio.to_thread(_plan_daily_queue, today)
    await _dispatch_queue(context, today)


async def delivery_dispatch_job(context: ContextTypes.DEFAULT_TYPE):
    await _dispatch_queue(context, datetime.date.today().isoformat())


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
        app.job_queue.run_daily(daily_job, time=datetime.time(hour=0, minute=1))
        app.job_queue.run_repeating(delivery_dispatch_job, interval=60, first=0)
        app.job_queue.run_daily(srs_job, time=datetime.time(hour=SRS_SEND_HOUR, minute=0))

    log.info("ربات هم‌زبان استارت شد.")
    app.run_polling()


if __name__ == "__main__":
    main()
