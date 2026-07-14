import asyncio
import calendar
import logging
import datetime
import json
import math
import re
import time
import threading
from collections import defaultdict, deque
from zoneinfo import ZoneInfo

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
    APP_TIMEZONE,
    SRS_REMINDER_MINUTE,
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
    AI_CARD_OUTPUT_FORMAT,
    DELIVERY_MAX_ATTEMPTS,
    DELIVERY_RETRY_BASE_SECONDS,
    TELEGRAM_MAX_CONCURRENCY,
    SESSION_CARD_DELAY_SECONDS,
    PLANS,
    OWNER_BYPASS_LIMITS,
    daily_word_query_limit_for_plan,
    effective_daily_allowance,
    effective_plan,
)
import db
import ai
import prompts
from catalog import (
    GOALS,
    LANGUAGES,
    LEVELS,
    goal_label,
    language_label,
    level_cefr,
    level_label,
)
from scheduling import plan_sessions
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from keyboards import (
    main_menu,
    lang_inline_keyboard,
    goal_inline_keyboard,
    level_inline_keyboard,
    awaiting_reply_keyboard,
    awaiting_inline_keyboard,
    daily_review_dates_keyboard,
    daily_review_menu_keyboard,
    query_result_keyboard,
    srs_review_keyboard,
    admin_panel_keyboard,
    llm_cost_dashboard_keyboard,
    llm_cost_plan_keyboard,
    llm_cost_kind_keyboard,
    llm_cost_status_keyboard,
    llm_cost_pricing_keyboard,
    daily_card_keyboard,
    BTN_TODAY_CARD,
    BTN_ASK_WORD,
    BTN_STATUS,
    BTN_GRAMMAR,
    BTN_ADMIN,
    BTN_CHANGE_LANG,
    BTN_CHANGE_GOAL,
    BTN_CHANGE_LEVEL,
    BTN_CANCEL,
    BTN_BACK,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hamzaban")
_app_timezone = ZoneInfo(APP_TIMEZONE)
_daily_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_ai_slots = threading.BoundedSemaphore(AI_MAX_CONCURRENCY)
_ai_request_times: deque[float] = deque()
_ai_request_lock = threading.Lock()
_telegram_slots = asyncio.Semaphore(TELEGRAM_MAX_CONCURRENCY)
_CUSTOM_WORD_MAX_CHARS = 42
_CUSTOM_WORD_MAX_WORDS = 3
_MANUAL_DAILY_BATCH_SIZE = 6
_CANCEL_INPUTS = {
    "cancel",
    "back",
    "لغو",
    "بازگشت",
    "انصراف",
    BTN_CANCEL.casefold(),
    BTN_BACK.casefold(),
}


def _call_ai_limited(function, *args, **kwargs):
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
        return function(*args, **kwargs)
    finally:
        _ai_slots.release()


def _ask_batch_limited(*args, **kwargs):
    return _call_ai_limited(ai.ask_batch, *args, **kwargs)


def _app_today() -> str:
    return datetime.datetime.now(_app_timezone).date().isoformat()


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


def _normalize_custom_word_input(text: str) -> str:
    return " ".join(text.split())


def _custom_word_input_error(text: str, target_lang: str) -> str | None:
    normalized = _normalize_custom_word_input(text)
    if not normalized:
        return "یک واژه یا عبارت کوتاه بفرست."
    if len(normalized) > _CUSTOM_WORD_MAX_CHARS:
        return f"فقط یک واژه یا عبارت کوتاهِ حداکثر {_CUSTOM_WORD_MAX_WORDS} کلمه‌ای بفرست."

    words = normalized.split()
    if len(words) > _CUSTOM_WORD_MAX_WORDS:
        return f"فقط یک واژه یا عبارت کوتاهِ حداکثر {_CUSTOM_WORD_MAX_WORDS} کلمه‌ای بفرست."
    if any(len(word) > 20 for word in words):
        return "واژه یا عبارتت خیلی بلند است؛ کوتاه‌تر بفرست."
    if any(char.isdigit() for char in normalized):
        return "لطفاً فقط واژه یا عبارت بفرست، نه عدد و نشانه‌های اضافی."
    if not re.fullmatch(r"[\w\s\u0600-\u06FF'’\-]+", normalized):
        return "لطفاً فقط واژه یا عبارت ساده بفرست."

    has_persian = bool(re.search(r"[\u0600-\u06FF]", normalized))
    has_latin = bool(re.search(r"[A-Za-z]", normalized))
    if not has_persian and not has_latin:
        return "یک واژه یا عبارت واقعی بفرست."

    latin_target = target_lang in {"en", "es", "fr", "de"}
    if latin_target and has_persian and len(words) >= 3:
        return "برای این زبان، یک واژه یا عبارت کوتاه‌تر و مرتبط‌تر بفرست."
    if latin_target and not has_latin and len(words) > 2:
        return "برای این زبان، یک واژه یا عبارت کوتاه‌تر و مرتبط‌تر بفرست."
    return None


def _is_cancel_input(text: str) -> bool:
    return _normalize_custom_word_input(text).casefold() in _CANCEL_INPUTS


async def _start_llm_wait_state(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    chat = update.effective_chat
    if not chat:
        return None
    await chat.send_action("typing")
    try:
        return await context.bot.send_message(chat_id=chat.id, text=text)
    except Exception:
        log.exception("Failed to send LLM wait-state message")
        return None


async def _finish_llm_wait_state(wait_message):
    if not wait_message:
        return
    try:
        await wait_message.delete()
    except Exception:
        log.exception("Failed to delete LLM wait-state message")


async def _exit_awaiting_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, *, via_callback: bool = False):
    context.user_data.pop("awaiting", None)
    user_id = update.effective_user.id
    reply_markup = main_menu(is_owner(user_id))
    if via_callback:
        try:
            await update.callback_query.edit_message_text("انصراف شد.")
        except BadRequest:
            log.info("cancel callback edit failed; continuing with menu message")
        await update.callback_query.message.reply_text("انصراف شد.", reply_markup=reply_markup)
        await update.callback_query.answer("انصراف شد.", show_alert=False)
        return
    await update.message.reply_text("انصراف شد.", reply_markup=reply_markup)


async def _edit_or_send(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    try:
        return await update.callback_query.edit_message_text(text, **kwargs)
    except BadRequest:
        log.info("callback edit failed; sending replacement message")
        return await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            **kwargs,
        )


async def _send_card_from_store(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    card_date: str,
    card_index: int,
    *,
    review_mode: bool = False,
):
    cards = db.get_daily_cards(user_id, card_date)
    if card_index >= len(cards):
        return None, len(cards)
    card = cards[card_index]
    row = db.get_user(user_id)
    session = db.get_daily_card_session(user_id, card_date)
    if not row:
        raise CardPreparationError("daily card owner no longer exists")
    card = await asyncio.to_thread(
        _prepare_cached_card,
        card,
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
    footer = f"📖 کارت {card_index + 1} از {len(cards)} برای {card_date}"
    if review_mode:
        footer = f"📚 مرور کارت {card_index + 1} از {len(cards)} برای {card_date}"
    await context.bot.send_message(
        chat_id=chat_id,
        text=format_card(
            card,
            footer=footer,
        ),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=daily_card_keyboard(
            user_id,
            card_date,
            card_index,
            card_index + 1 < len(cards),
            callback_prefix="review:next" if review_mode else "daily:next",
            show_translations=True,
        ),
    )
    return card, len(cards)


def escape_mdv2(text: str) -> str:
    """Escape کامل‌تر برای MarkdownV2"""
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([' + re.escape(special) + r'])', r'\\\1', text)


def escape_mdv2_code(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"([`\\])", r"\\\1", text)


def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID


def _user_plan(row) -> str:
    return effective_plan(row["plan"] or "free", OWNER_BYPASS_LIMITS and is_owner(row["user_id"]))


def _user_plan_label(row) -> str:
    actual = PLANS.get(row["plan"] or "free", row["plan"] or "free")
    if OWNER_BYPASS_LIMITS and is_owner(row["user_id"]):
        return f"{actual} (دسترسی مالک)"
    return actual


def format_card(
    data: dict,
    footer: str = "",
    *,
    presentation: str = "detailed",
    translations_prepared: bool = False,
) -> str:
    if presentation not in {"brief", "detailed"}:
        raise ValueError("presentation must be 'brief' or 'detailed'")

    word = escape_mdv2(data.get("word", ""))
    phon = escape_mdv2_code(data.get("phonetic", ""))
    fa_meaning = escape_mdv2(data.get("fa_meaning", ""))
    fa_expl = escape_mdv2(data.get("fa_explanation", ""))

    lines = [f"*{word}*"]

    if phon:
        lines.append(f"`{phon}`")

    lines.append(f"\n🇮🇷 *{fa_meaning}*")

    if fa_expl:
        lines.append(f"_{fa_expl}_")

    if presentation == "brief":
        if footer:
            lines.append(f"\n{escape_mdv2(footer)}")
        return "\n".join(lines)

    syn_list = [escape_mdv2(s) for s in (data.get("synonyms") or [])]
    ant_list = [escape_mdv2(s) for s in (data.get("antonyms") or [])]
    syn = "، ".join(syn_list) or "—"
    ant = "، ".join(ant_list) or "—"

    examples = (data.get("examples") or [])[:2]
    ex_text = "\n".join(f"• {escape_mdv2(e)}" for e in examples) if examples else ""

    grammar_tip = escape_mdv2(data.get("grammar_tip", ""))

    lines.append(f"\n🟢 *مترادف:* {syn}")
    lines.append(f"🔴 *متضاد:* {ant}")

    if ex_text:
        lines.append(f"\n*مثال‌ها:*\n{ex_text}")

    if translations_prepared:
        translations = (data.get("example_translations") or [])[:2]
        translation_lines = "\n".join(
            f"• {escape_mdv2(example)} — ||{escape_mdv2(translation)}||"
            for example, translation in zip(examples, translations)
        )
        if translation_lines:
            lines.append(f"\n📝 *ترجمه‌ی مثال‌ها:*\n{translation_lines}")

    if grammar_tip:
        lines.append(f"\n✍️ *نکته‌ی گرامری:*\n{grammar_tip}")

    if footer:
        lines.append(f"\n{escape_mdv2(footer)}")

    return "\n".join(lines)


class CardPreparationError(RuntimeError):
    pass


def _prepare_cached_card(
    card: object,
    *,
    lang: str,
    user_id: int,
    plan: str,
    source: str,
    persist_patch,
) -> dict:
    try:
        return ai.validate_card(card)
    except ai.CardValidationError as validation_error:
        fields = ai.card_repair_fields(card)
        if not fields:
            raise CardPreparationError(
                f"{source} card has no repairable fields"
            ) from validation_error
        try:
            patch = _call_ai_limited(
                ai.repair_card,
                card,
                fields,
                lang,
                user_id=user_id,
                plan=plan,
            )
            merged = dict(card) if isinstance(card, dict) else {}
            merged.update(patch)
            repaired = ai.validate_card(merged)
            if not persist_patch(patch):
                raise CardPreparationError(
                    f"{source} card repair could not be persisted"
                )
            log.info(
                "cached card repaired source=%s user_id=%s fields=%s",
                source,
                user_id,
                fields,
            )
            return repaired
        except Exception as repair_error:
            log.exception(
                "cached card repair failed source=%s user_id=%s fields=%s",
                source,
                user_id,
                fields,
            )
            raise CardPreparationError(
                f"{source} card could not be repaired safely"
            ) from repair_error


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
    
    await _edit_or_send(
        update,
        context,
        text,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=goal_inline_keyboard(),
    )


async def on_goal_selected(update: Update, context: ContextTypes.DEFAULT_TYPE, goal: str):
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
    user_id = update.effective_user.id
    db.set_user_level(user_id, level)
    row = db.get_user(user_id)
    lang_name = language_label(row["target_lang"])
    goal_name = goal_label(row["goal"])
    level_name = level_label(level)
    cefr = level_cefr(level)

    await _edit_or_send(
        update,
        context,
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
    
    await _edit_or_send(
        update,
        context,
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
    
    await _edit_or_send(
        update,
        context,
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
    await _edit_or_send(
        update,
        context,
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
    user_id: int | None = None,
    plan: str | None = None,
) -> list[dict]:
    cards: list[dict] = []
    last_error: Exception | None = None
    omit_prompt_avoid = False
    for attempt in range(1, 4):
        remaining = card_count - len(cards)
        if remaining <= 0:
            break
        batch_words = used_words + [card["word"] for card in cards]
        prompt_avoid_words = [] if omit_prompt_avoid else batch_words
        if omit_prompt_avoid:
            log.info(
                "daily batch retry omitting prompt avoid-list user_id=%s attempt=%s",
                user_id,
                attempt,
            )
        try:
            batch = _ask_batch_limited(
                prompts.daily_batch_system_prompt(
                    lang,
                    goal,
                    level,
                    remaining,
                    avoid_words=prompt_avoid_words,
                    compact=AI_CARD_OUTPUT_FORMAT == "compact_json",
                ),
                expected_count=remaining,
                used_words=batch_words,
                request_kind="daily_batch",
                user_id=user_id,
                plan=plan,
            )
        except Exception as exc:
            last_error = exc
            if (
                isinstance(exc, ai.BatchValidationError)
                and exc.diagnostics.get("accepted", 0) == 0
                and exc.diagnostics.get("validation_rejected", 0) == 0
                and exc.diagnostics.get("duplicates_against_avoid", 0) > 0
                and exc.diagnostics.get("duplicates_within_batch", 0) == 0
            ):
                omit_prompt_avoid = True
            log.warning(
                "daily batch attempt failed user_id=%s attempt=%s requested=%s "
                "accepted_so_far=%s error=%s",
                user_id,
                attempt,
                remaining,
                len(cards),
                exc,
            )
            continue
        if not batch:
            log.warning(
                "daily batch returned empty result user_id=%s attempt=%s requested=%s",
                user_id,
                attempt,
                remaining,
            )
            continue
        cards.extend(batch)

    if not cards and last_error:
        raise last_error
    return cards


def _daily_avoid_words(user_id: int, card_date: str, current_cards: list[dict]) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for word in db.get_recent_daily_words(user_id, exclude_date=card_date, limit=50):
        normalized = " ".join(str(word).split()).casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            words.append(word)
    for card in current_cards:
        word = str(card.get("word", "")).strip()
        normalized = " ".join(word.split()).casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            words.append(word)
    return words


def _daily_card_session_profile(user_id: int, row, card_date: str):
    session = db.ensure_daily_card_session(
        user_id,
        card_date,
        row["target_lang"],
        row["goal"],
        row["level"],
    )
    return session


def _review_history_page(dates: list[str], page: int, page_size: int = 7) -> tuple[list[str], int, int]:
    total_pages = max(1, math.ceil(len(dates) / page_size))
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = start + page_size
    return dates[start:end], page, total_pages


def _ensure_daily_cards(user_id: int, row, card_date: str, limit: int) -> list[dict]:
    session = _daily_card_session_profile(user_id, row, card_date)
    cards = db.get_daily_cards(user_id, card_date)
    if len(cards) >= limit:
        return cards

    used_words = _daily_avoid_words(user_id, card_date, cards)
    new_cards = _generate_daily_batch(
        session["target_lang"],
        session["goal"],
        session["level"],
        limit - len(cards),
        used_words,
        user_id,
        row["plan"] or "free",
    )
    for offset, card in enumerate(new_cards):
        db.add_daily_card(user_id, card_date, len(cards) + offset, card)
    return db.get_daily_cards(user_id, card_date)


def _ensure_scheduled_session_cards(user_id: int, row, queue_row) -> list[dict]:
    session = _daily_card_session_profile(user_id, row, queue_row["delivery_date"])
    existing = db.get_daily_cards(user_id, queue_row["delivery_date"])
    start = queue_row["card_start_index"]
    end = start + queue_row["card_count"]
    if len(existing) >= end:
        return existing[start:end]

    used_words = _daily_avoid_words(user_id, queue_row["delivery_date"], existing)
    cards: list[dict] = []
    while len(existing) + len(cards) < end:
        remaining = end - len(existing) - len(cards)
        batch = _generate_daily_batch(
            session["target_lang"],
            session["goal"],
            session["level"],
            min(6, remaining),
            used_words + [card["word"] for card in cards],
            user_id,
            row["plan"] or "free",
        )
        if not batch:
            raise RuntimeError("AI returned no cards for the scheduled session")
        cards.extend(batch)
    for offset, card in enumerate(cards):
        db.add_daily_card(user_id, queue_row["delivery_date"], len(existing) + offset, card)
    return db.get_daily_cards(user_id, queue_row["delivery_date"])[start:end]


def _ensure_next_daily_card(user_id: int, row, card_date: str, limit: int) -> tuple[dict | None, int]:
    session = _daily_card_session_profile(user_id, row, card_date)
    next_index = db.get_daily_progress(user_id, card_date)
    if next_index >= limit:
        return None, next_index

    cards = db.get_daily_cards(user_id, card_date)
    if next_index >= len(cards):
        used_words = _daily_avoid_words(user_id, card_date, cards)
        remaining = limit - len(cards)
        new_cards = _generate_daily_batch(
            session["target_lang"],
            session["goal"],
            session["level"],
            min(_MANUAL_DAILY_BATCH_SIZE, remaining),
            used_words,
            user_id,
            row["plan"] or "free",
        )
        if not new_cards:
            raise RuntimeError("AI returned no card for the requested daily card")
        for offset, card in enumerate(new_cards):
            db.add_daily_card(user_id, card_date, len(cards) + offset, card)
        cards = db.get_daily_cards(user_id, card_date)

    card = cards[next_index]
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
        if card is not None:
            card = await asyncio.to_thread(
                _prepare_cached_card,
                card,
                lang=row["target_lang"],
                user_id=user_id,
                plan=row["plan"] or "free",
                source="daily",
                persist_patch=lambda patch: db.update_daily_card_fields(
                    user_id,
                    card_date,
                    card_index,
                    patch,
                ),
            )
            db.set_daily_progress(user_id, card_date, card_index + 1)

    if card is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ سهمیه‌ی امروزت ({limit} کارت) کامل شده است.",
            reply_markup=daily_review_menu_keyboard(),
        )
        return

    db.touch_streak(user_id)
    log.info("daily card delivered user_id=%s date=%s index=%s", user_id, card_date, card_index)
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
            show_translations=True,
        ),
    )


async def send_daily_card_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.message.reply_text("اول باید /start رو بزنی.")
        return

    today = _app_today()
    plan = _user_plan(row)
    limit = effective_daily_allowance(
        row["plan"] or "free",
        row["optional_daily_limit"],
        OWNER_BYPASS_LIMITS and is_owner(user_id),
    )

    wait_message = await _start_llm_wait_state(
        update,
        context,
        "⏳ دارم کارت امروز رو می‌سازم…",
    )
    try:
        await _send_next_daily_card(update, context, row, today, limit)
    except Exception:
        log.exception("Daily card generation failed")
        await update.message.reply_text("مشکلی در ساخت کارت‌های امروز پیش اومد.")
    finally:
        await _finish_llm_wait_state(wait_message)

async def send_grammar_tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.message.reply_text("اول باید /start رو بزنی.")
        return

    limit = daily_word_query_limit_for_plan(row["plan"] or "free")
    usage_before_text = _grammar_tip_usage_text(row)
    if not db.reserve_grammar_tip(
        user_id,
        limit,
        bypass_limits=OWNER_BYPASS_LIMITS and is_owner(user_id),
    ):
        await update.message.reply_text(
            f"{usage_before_text}\n\nسقف روزانه‌ی نکته‌ی گرامری تموم شده."
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
            log.exception("AI error")
            await update.message.reply_text(
                "مشکلی در ارتباط با هوش مصنوعی پیش اومد، دوباره امتحان کن."
            )
            return
        # ساخت متن با escape مناسب برای MarkdownV2
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
        log.info("grammar tip delivered user_id=%s lang=%s", user_id, row["target_lang"])
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception:
        log.exception("Grammar tip delivery failed")
        await update.message.reply_text("مشکلی در ارسال نکته‌ی گرامری پیش اومد.")
    finally:
        await _finish_llm_wait_state(wait_message)


async def ask_for_ask_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    plan = row["plan"] if row else "free"
    limit = daily_word_query_limit_for_plan(plan)
    usage_text = _word_query_usage_text(row) if row else f"📊 استفاده امروز: 0/{limit}"
    if not db.can_ask_word(
        user_id,
        limit,
        bypass_limits=OWNER_BYPASS_LIMITS and is_owner(user_id),
    ):
        await update.message.reply_text(
            f"{usage_text}\n\nسقف روزانه‌ی پرسش واژه‌ی پلن شما تموم شده."
        )
        return
    context.user_data["awaiting"] = "ask_word"
    await update.message.reply_text(
        f"{usage_text}\n\nچه واژه یا عبارتی رو می‌خوای معنی/توضیح بدم؟",
        reply_markup=awaiting_reply_keyboard(),
    )


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
        log.info("query result saved user_id=%s word_id_token=%s", user_id, token)
    else:
        message = "این واژه از قبل در مرور شما ثبت شده بود."
    await update.callback_query.answer(message, show_alert=True)


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
    if action == "remember":
        if not db.advance_word_review(word_id):
            await update.callback_query.answer("این مرور قبلاً ثبت شده است.", show_alert=True)
            return
        db.touch_streak(user_id)
        await update.callback_query.answer("ثبت شد؛ مرور بعدی زمان‌بندی شد.", show_alert=True)
        log.info("srs review advanced user_id=%s word_id=%s", user_id, word_id)
        return
    if action == "again":
        if not db.defer_word_review(word_id):
            await update.callback_query.answer("این مرور قبلاً ثبت شده است.", show_alert=True)
            return
        db.touch_streak(user_id)
        await update.callback_query.answer("باشه؛ فردا دوباره یادآوری می‌کنم.", show_alert=True)
        log.info("srs review deferred user_id=%s word_id=%s", user_id, word_id)
        return
    await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)


def _message_has_prepared_translations(update: Update) -> bool:
    message = update.callback_query.message
    return bool(message and "ترجمه‌ی مثال‌ها" in (message.text or ""))


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
    markup = daily_card_keyboard(
        user_id,
        card_date,
        card_index,
        card_index + 1 < len(cards),
        callback_prefix="review:next" if review_mode else "daily:next",
        show_translations=False,
    )
    try:
        await update.callback_query.edit_message_text(
            format_card(card, footer=footer, translations_prepared=True),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=markup,
        )
    except BadRequest as exc:
        if "not modified" in str(exc).casefold():
            await update.callback_query.answer("ترجمه‌ها قبلاً آماده شده‌اند.")
        else:
            log.exception("failed to edit prepared daily card")
            await update.callback_query.answer(
                "نمایش ترجمه‌ها انجام نشد؛ لطفاً دوباره امتحان کنید.",
                show_alert=True,
            )
        return
    await update.callback_query.answer("ترجمه‌ها آماده شدند.")


async def _handle_query_prepare(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    token: str,
):
    user_id = update.effective_user.id
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
    try:
        await update.callback_query.edit_message_text(
            format_card(card, footer=footer, translations_prepared=True),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=query_result_keyboard(row["token"], row["lang"], show_translations=False),
        )
    except BadRequest as exc:
        if "not modified" in str(exc).casefold():
            await update.callback_query.answer("ترجمه‌ها قبلاً آماده شده‌اند.")
        else:
            log.exception("failed to edit prepared query card")
            await update.callback_query.answer(
                "نمایش ترجمه‌ها انجام نشد؛ لطفاً دوباره امتحان کنید.",
                show_alert=True,
            )
        return
    await update.callback_query.answer("ترجمه‌ها آماده شدند.")


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
    try:
        await update.callback_query.edit_message_text(
            format_card(card, footer=footer, translations_prepared=True),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=srs_review_keyboard(user_id, word_id, show_translations=False),
        )
    except BadRequest as exc:
        if "not modified" in str(exc).casefold():
            await update.callback_query.answer("ترجمه‌ها قبلاً آماده شده‌اند.")
        else:
            log.exception("failed to edit prepared SRS card")
            await update.callback_query.answer(
                "نمایش ترجمه‌ها انجام نشد؛ لطفاً دوباره امتحان کنید.",
                show_alert=True,
            )
        return
    await update.callback_query.answer("ترجمه‌ها آماده شدند.")


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


async def _show_review_date(update: Update, context: ContextTypes.DEFAULT_TYPE, card_date: str):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.callback_query.answer("ابتدا /start را بزنید.", show_alert=True)
        return
    cards = db.get_daily_cards(user_id, card_date)
    if not cards:
        await update.callback_query.answer("برای این روز کارتی پیدا نشد.", show_alert=True)
        return
    await _send_card_from_store(
        context,
        update.effective_chat.id,
        user_id,
        card_date,
        0,
        review_mode=True,
    )


def _llm_cost_default_state() -> dict[str, object]:
    return {
        "range": "mtd",
        "detail": False,
        "plan": None,
        "user_id": None,
        "request_kind": None,
        "model": None,
        "outcome": None,
    }


def _llm_cost_state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    state = context.user_data.get("llm_cost_state")
    if not isinstance(state, dict):
        state = _llm_cost_default_state()
    else:
        merged = _llm_cost_default_state()
        merged.update({key: state.get(key, value) for key, value in merged.items()})
        state = merged
    context.user_data["llm_cost_state"] = state
    return state


def _llm_cost_set_state(
    context: ContextTypes.DEFAULT_TYPE,
    **updates,
) -> dict[str, object]:
    state = _llm_cost_state(context).copy()
    for key, value in updates.items():
        if value == "":
            value = None
        state[key] = value
    context.user_data["llm_cost_state"] = state
    return state


def _llm_cost_range_bounds(range_name: str) -> tuple[str, str, str]:
    today = datetime.datetime.now(_app_timezone).date()
    if range_name == "today":
        start = end = today
        label = "today"
    elif range_name == "7d":
        start = today - datetime.timedelta(days=6)
        end = today
        label = "7d"
    elif range_name == "30d":
        start = today - datetime.timedelta(days=29)
        end = today
        label = "30d"
    elif range_name == "all":
        return "", "", "ALL"
    else:
        start = today.replace(day=1)
        end = today
        label = "MTD"
    return start.isoformat(), end.isoformat(), label


def _llm_cost_query_filters(state: dict[str, object]) -> dict[str, object]:
    start_date, end_date, _ = _llm_cost_range_bounds(str(state.get("range") or "mtd"))
    filters: dict[str, object] = {
        "start_date": start_date,
        "end_date": end_date,
    }
    for key in ("plan", "user_id", "request_kind", "model", "outcome"):
        value = state.get(key)
        if value not in {None, "", "all"}:
            filters[key] = value
    return filters


def _llm_cost_currency_text(cost_usd: float, cost_toman: float) -> str:
    return f"${cost_usd:,.4f} / {round(cost_toman):,} Toman"


def _llm_cost_projection(filters: dict[str, object]) -> tuple[str, str, float] | None:
    month_start = datetime.datetime.now(_app_timezone).date().replace(day=1)
    today = datetime.datetime.now(_app_timezone).date()
    projection_filters = dict(filters)
    projection_filters["start_date"] = month_start.isoformat()
    projection_filters["end_date"] = today.isoformat()
    summary = db.summarize_llm_requests(projection_filters)
    request_count = int(summary.get("request_count") or 0)
    cost_usd = float(summary.get("cost_usd") or 0)
    cost_toman = float(summary.get("cost_toman") or 0)
    if request_count <= 0 or cost_usd <= 0:
        return None
    month_days = calendar.monthrange(today.year, today.month)[1]
    elapsed_days = max((today - month_start).days + 1, 1)
    linear_usd = (cost_usd / elapsed_days) * month_days
    linear_toman = (cost_toman / elapsed_days) * month_days
    daily_rows = db.recent_llm_requests(projection_filters, limit=5000)
    daily_costs: dict[str, float] = defaultdict(float)
    for row in daily_rows:
        daily_costs[str(row["request_date"])] += float(row["cost_usd"] or 0)
    recent_days = sorted(daily_costs)[-7:]
    if recent_days:
        rolling_usd = sum(daily_costs[day] for day in recent_days) / len(recent_days) * month_days
        rolling_toman = rolling_usd * (
            cost_toman / cost_usd if cost_usd else db.get_llm_cost_profile()["usd_to_toman_rate"]
        )
    else:
        rolling_toman = linear_toman
        rolling_usd = linear_usd
    ratio = rolling_usd / linear_usd if linear_usd else 1.0
    return (
        _llm_cost_currency_text(linear_usd, linear_toman),
        _llm_cost_currency_text(rolling_usd, rolling_toman),
        ratio,
    )


def _llm_cost_filter_label(value: object, fallback: str = "all") -> str:
    if value in {None, "", "all"}:
        return fallback
    return str(value)


def _llm_cost_state_label(state: dict[str, object]) -> str:
    parts = [
        f"range={state.get('range', 'mtd')}",
        f"plan={_llm_cost_filter_label(state.get('plan'))}",
        f"user={_llm_cost_filter_label(state.get('user_id'))}",
        f"kind={_llm_cost_filter_label(state.get('request_kind'))}",
        f"model={_llm_cost_filter_label(state.get('model'))}",
        f"status={_llm_cost_filter_label(state.get('outcome'))}",
    ]
    return " • ".join(parts)


def _llm_cost_percent(numerator: int | float, denominator: int | float) -> str:
    if not denominator:
        return "0.0%"
    return f"{(float(numerator) / float(denominator)) * 100:.1f}%"


def _llm_cost_status_icon(outcome: object) -> str:
    return {
        "success": "🟢",
        "failure_billed": "🔴",
        "failure_zero_cost": "⚪",
    }.get(str(outcome), "⚪")


def _llm_cost_report_text(state: dict[str, object]) -> str:
    filters = _llm_cost_query_filters(state)
    summary = db.summarize_llm_requests(filters)
    request_count = int(summary.get("request_count") or 0)
    prompt_tokens = int(summary.get("prompt_tokens") or 0)
    completion_tokens = int(summary.get("completion_tokens") or 0)
    total_tokens = int(summary.get("total_tokens") or 0)
    cost_usd = float(summary.get("cost_usd") or 0)
    cost_toman = float(summary.get("cost_toman") or 0)
    avg_latency = summary.get("avg_latency_ms")
    avg_cost = cost_usd / request_count if request_count else 0.0
    success_count = int(summary.get("success_count") or 0)
    billed_failures = int(summary.get("billed_failure_count") or 0)
    zero_cost_failures = int(summary.get("zero_cost_failure_count") or 0)
    billed_failure_cost_usd = float(summary.get("billed_failure_cost_usd") or 0)
    billed_failure_cost_toman = float(summary.get("billed_failure_cost_toman") or 0)
    success_rate = _llm_cost_percent(success_count, request_count)
    billed_failure_rate = _llm_cost_percent(billed_failures, request_count)
    range_label = str(state.get("range") or "mtd").upper()

    lines = [
        "📊 LLM Cost Dashboard",
        f"Scope: {_llm_cost_state_label(state)}",
        "",
        f"Overview — {range_label}",
        f"📨 Requests: {request_count:,}",
        f"💳 Spend: {_llm_cost_currency_text(cost_usd, cost_toman)}",
        f"🪙 Avg cost/request: {_llm_cost_currency_text(avg_cost, avg_cost * db.get_llm_cost_profile()['usd_to_toman_rate'])}",
        f"🟢 Success rate: {success_rate} ({success_count:,})",
        f"🔴 Billed failure rate: {billed_failure_rate} ({billed_failures:,})",
        "",
        f"🧮 Tokens: prompt {prompt_tokens:,} • completion {completion_tokens:,} • total {total_tokens:,}",
        f"⏱ Avg latency: {round(float(avg_latency), 1) if avg_latency is not None else 0.0} ms",
    ]

    if billed_failures > 0 or (request_count and billed_failures / request_count >= 0.2):
        lines.extend(
            [
                "",
                "⚠️ Attention required",
                f"💸 Billed failures: {billed_failures:,} "
                f"({_llm_cost_currency_text(billed_failure_cost_usd, billed_failure_cost_toman)})",
                f"⚪ Zero-cost failures: {zero_cost_failures:,}",
            ]
        )
    else:
        lines.extend(["", "🟢 System health: no billable failures"])

    projection = None
    if state.get("range") == "mtd":
        projection = _llm_cost_projection(filters)
    if projection:
        linear, rolling, ratio = projection
        lines.extend(
            [
                "",
                "📈 Month-end Projection",
                f"- Linear: {linear} (MTD run rate)",
                f"- Rolling 7-day: {rolling} (recent daily average)",
            ]
        )
        if ratio >= 2:
            lines.append(f"⚠️ Rolling projection is {ratio:.1f}× the linear projection")

    breakdown_specs = [
        ("📦 By plan", "plan"),
        ("🧩 By request kind", "request_kind"),
        ("🤖 By model", "model"),
    ]
    if state.get("user_id") is None:
        breakdown_specs.append(("👤 By user", "user_id"))
    for title, key in breakdown_specs:
        rows = db.breakdown_llm_requests(key, filters, limit=5)
        lines.append("")
        lines.append(title + ":")
        if not rows:
            lines.append("- none")
            continue
        for row in rows:
            bucket = row.get("bucket")
            if key == "plan":
                bucket = {
                    "free": "free",
                    "silver": "silver",
                    "gold": "gold",
                }.get(str(bucket), str(bucket))
            lines.append(
                f"- {bucket}: {int(row.get('request_count') or 0):,} req • "
                f"{_llm_cost_currency_text(float(row.get('cost_usd') or 0), float(row.get('cost_toman') or 0))} • "
                f"{_llm_cost_percent(float(row.get('cost_usd') or 0), cost_usd)} spend • "
                f"{_llm_cost_percent(int(row.get('billed_failure_count') or 0), int(row.get('request_count') or 0))} billed fail"
            )

    if state.get("detail"):
        rows = db.recent_llm_requests(filters, limit=10)
        lines.extend(["", "🧾 Recent Requests"])
        if not rows:
            lines.append("- none")
        else:
            for row in rows:
                lines.append(
                    f"- {str(row['created_at'])[:19]} "
                    f"{_llm_cost_status_icon(row['outcome'])} {row['outcome']} | "
                    f"{row['request_kind']} | {row['model']} | "
                    f"user {row['user_id']} / {row['plan']} | "
                    f"{int(row['total_tokens'] or 0):,} tok | "
                    f"{_llm_cost_currency_text(float(row['cost_usd'] or 0), float(row['cost_toman'] or 0))} | "
                    f"{round(float(row['latency_ms']), 1) if row['latency_ms'] is not None else 0.0} ms"
                )

    return "\n".join(lines)


def _llm_pricing_text() -> str:
    profile = db.get_llm_cost_profile()
    return "\n".join(
        [
            "LLM pricing defaults",
            f"- Input: ${profile['input_cost_usd_per_million']:,.4f} / 1M tokens",
            f"- Output: ${profile['output_cost_usd_per_million']:,.4f} / 1M tokens",
            f"- USD→Toman: {profile['usd_to_toman_rate']:,.0f}",
            "",
            "These values are the active defaults used by new requests unless the admin updates them.",
        ]
    )


async def _show_llm_cost_dashboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    detail: bool | None = None,
):
    state = _llm_cost_state(context)
    if detail is not None:
        state = _llm_cost_set_state(context, detail=detail)
    text = _llm_cost_report_text(state)
    if update.callback_query:
        await _edit_or_send(
            update,
            context,
            text,
            reply_markup=llm_cost_dashboard_keyboard(bool(state.get("detail"))),
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=llm_cost_dashboard_keyboard(bool(state.get("detail"))),
        )


# ---------------- پنل ادمین (فقط مالک) ----------------

async def open_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text("پنل مدیریت ربات:", reply_markup=admin_panel_keyboard())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    if not is_owner(update.effective_user.id):
        await update.callback_query.answer("فقط مالک ربات دسترسی داره.", show_alert=True)
        return
    if action == "stats":
        await _edit_or_send(update, context, f"👥 تعداد کل کاربران: {db.count_users()}")
    elif action == "llm_costs":
        await _show_llm_cost_dashboard(update, context)
    elif action == "llm_pricing":
        await _edit_or_send(
            update,
            context,
            _llm_pricing_text(),
            reply_markup=llm_cost_pricing_keyboard(),
        )
    elif action == "set_plan":
        context.user_data["awaiting"] = "admin_set_plan"
        await _edit_or_send(
            update,
            context,
            "فرمت را ارسال کنید:\n`user_id_or_username plan`\n\n"
            "مثال: `123456789 silver` یا `@username gold`\n"
            "پلن‌ها: free، silver، gold",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=awaiting_inline_keyboard(),
        )
    elif action == "set_model":
        context.user_data["awaiting"] = "admin_set_model"
        await _edit_or_send(
            update,
            context,
            f"نام مدل فعلی: `{db.get_setting('ai_model')}`\nنام مدل جدید رو بفرست:",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=awaiting_inline_keyboard(),
        )
    elif action == "set_base_url":
        context.user_data["awaiting"] = "admin_set_base_url"
        await _edit_or_send(
            update,
            context,
            f"Base URL فعلی: `{db.get_setting('ai_base_url')}`\nBase URL جدید رو بفرست:",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=awaiting_inline_keyboard(),
        )
    elif action == "set_api_key":
        context.user_data["awaiting"] = "admin_set_api_key"
        await _edit_or_send(
            update,
            context,
            "API Key جدید رو بفرست (بعداً این پیام رو از چت پاک کن):",
            reply_markup=awaiting_inline_keyboard(),
        )
    elif action == "broadcast":
        context.user_data["awaiting"] = "admin_broadcast"
        await _edit_or_send(
            update,
            context,
            "متن پیام همگانی رو بفرست:",
            reply_markup=awaiting_inline_keyboard(),
        )
    elif action == "show_settings":
        key = db.get_setting("ai_api_key", "")
        masked = (key[:6] + "…" + key[-4:]) if len(key) > 12 else "—"
        await _edit_or_send(
            update,
            context,
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
        if _is_cancel_input(text):
            await _exit_awaiting_flow(update, context)
            return

        context.user_data["awaiting"] = None

        if (awaiting.startswith("admin_") or awaiting.startswith("llm_cost_") or awaiting.startswith("llm_price_")) and not is_owner(user_id):
            return  # لایه‌ی امنیتی اضافه؛ در حالت عادی اصلاً به این حالت نمی‌رسد

        if awaiting == "ask_word":
            row = db.get_user(user_id)
            limit = daily_word_query_limit_for_plan(row["plan"] if row else "free")
            error = _custom_word_input_error(text, row["target_lang"] if row else "en")
            if error:
                context.user_data["awaiting"] = "ask_word"
                await update.message.reply_text(
                    f"{error}\n\nچه واژه یا عبارتی رو می‌خوای معنی/توضیح بدم؟",
                    reply_markup=awaiting_inline_keyboard(),
                )
                return
            if not db.reserve_word_query(
                user_id,
                limit,
                bypass_limits=OWNER_BYPASS_LIMITS and is_owner(user_id),
            ):
                await update.message.reply_text(
                    f"سقف روزانه‌ی پرسش واژه‌ی پلن شما ({limit} بار) تموم شده."
                )
                return
            wait_message = await _start_llm_wait_state(
                update,
                context,
                "⏳ دارم معنی و توضیحش رو پیدا می‌کنم…",
            )
            try:
                data = await asyncio.to_thread(
                    _call_ai_limited,
                    ai.ask_card,
                    prompts.custom_word_system_prompt(
                        row["target_lang"],
                        row["level"],
                        compact=AI_CARD_OUTPUT_FORMAT == "compact_json",
                    ),
                    user_prompt=text,
                    request_kind="custom_word",
                    user_id=user_id,
                    plan=row["plan"] or "free",
                )
            except Exception:
                db.release_word_query(user_id)
                log.exception("AI error")
                await _finish_llm_wait_state(wait_message)
                await update.message.reply_text("مشکلی در ارتباط با هوش مصنوعی پیش اومد، دوباره امتحان کن.")
                return
            try:
                data = await asyncio.to_thread(
                    _prepare_cached_card,
                    data,
                    lang=row["target_lang"],
                    user_id=user_id,
                    plan=row["plan"] or "free",
                    source="custom_word",
                    persist_patch=lambda patch: True,
                )
            except CardPreparationError:
                db.release_word_query(user_id)
                await _finish_llm_wait_state(wait_message)
                await update.message.reply_text(
                    "این کارت نتونست با اطمینان آماده بشه؛ لطفاً بعداً دوباره امتحان کن."
                )
                return
            row_after = db.get_user(user_id)
            usage_row = row_after or row
            usage_text = _word_query_usage_text(usage_row) if usage_row else f"📊 استفاده امروز: 1/{limit}"
            query_token = db.create_query_result(
                user_id,
                text,
                data.get("word", text),
                row["target_lang"] if row else "en",
                data,
            )
            db.touch_streak(user_id)
            log.info("custom word query delivered user_id=%s lang=%s", user_id, row["target_lang"])
            await _finish_llm_wait_state(wait_message)
            await update.message.reply_text(
                format_card(
                    data,
                    footer=(
                        f"{usage_text}\n\n"
                        "برای افزودن این واژه به مرور، از دکمه‌ی زیر استفاده کن."
                    ),
                ),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=query_result_keyboard(
                    query_token,
                    row["target_lang"] if row else "en",
                    show_translations=True,
                ),
            )
            return

        if awaiting == "admin_set_model":
            db.set_setting("ai_model", text)
            await update.message.reply_text(f"مدل جدید ثبت شد: `{text}`", parse_mode=ParseMode.MARKDOWN_V2)
            return

        if awaiting == "llm_cost_user":
            if text.casefold() in {"all", "همه", "none", "null"}:
                _llm_cost_set_state(context, user_id=None)
            else:
                target = db.find_user(text)
                if not target:
                    context.user_data["awaiting"] = "llm_cost_user"
                    await update.message.reply_text(
                        "User not found. Send a valid user_id or @username, or type all.",
                        reply_markup=awaiting_inline_keyboard(),
                    )
                    return
                _llm_cost_set_state(context, user_id=target["user_id"])
            await _show_llm_cost_dashboard(update, context)
            return

        if awaiting == "llm_cost_model":
            if text.casefold() in {"all", "همه", "none", "null"}:
                _llm_cost_set_state(context, model=None)
            else:
                _llm_cost_set_state(context, model=text.strip())
            await _show_llm_cost_dashboard(update, context)
            return

        if awaiting in {"llm_price_input", "llm_price_output", "llm_price_rate"}:
            try:
                value = float(text.replace(",", "").strip())
                if value < 0:
                    raise ValueError
            except ValueError:
                context.user_data["awaiting"] = awaiting
                await update.message.reply_text(
                    "عدد معتبر بفرست، مثلاً 0.12 یا 65000.",
                    reply_markup=awaiting_inline_keyboard(),
                )
                return
            profile = db.get_llm_cost_profile()
            if awaiting == "llm_price_input":
                db.set_llm_cost_profile(
                    input_cost_usd_per_million=value,
                    output_cost_usd_per_million=profile["output_cost_usd_per_million"],
                    usd_to_toman_rate=profile["usd_to_toman_rate"],
                )
            elif awaiting == "llm_price_output":
                db.set_llm_cost_profile(
                    input_cost_usd_per_million=profile["input_cost_usd_per_million"],
                    output_cost_usd_per_million=value,
                    usd_to_toman_rate=profile["usd_to_toman_rate"],
                )
            else:
                db.set_llm_cost_profile(
                    input_cost_usd_per_million=profile["input_cost_usd_per_million"],
                    output_cost_usd_per_million=profile["output_cost_usd_per_million"],
                    usd_to_toman_rate=value,
                )
            await update.message.reply_text(_llm_pricing_text())
            return

        if awaiting == "admin_set_plan":
            parts = text.split()
            if len(parts) != 2 or parts[1].lower() not in PLANS:
                context.user_data["awaiting"] = "admin_set_plan"
                await update.message.reply_text(
                    "فرمت نامعتبر است. نمونه: `123456789 silver` یا `@username gold`",
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                return
            target = db.find_user(parts[0])
            if not target:
                context.user_data["awaiting"] = "admin_set_plan"
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
                    await _send_with_retry(context.bot, u["user_id"], text)
                    sent += 1
                except Exception:
                    log.exception("Broadcast failed for user %s", u["user_id"])
            await update.message.reply_text(f"پیام برای {sent} کاربر ارسال شد.")
            return

    # مسیر دکمه‌های منوی اصلی
    if text == BTN_TODAY_CARD:
        await send_daily_card_now(update, context)
    elif text == BTN_GRAMMAR:
        await send_grammar_tip(update, context)
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
    if not data.startswith(
        (
            "query:add:",
            "query:prepare:",
            "daily:prepare:",
            "review:prepare:",
            "flow:",
            "srs:",
        )
    ):
        await update.callback_query.answer()

    if data in {"flow:cancel", "flow:back"}:
        if context.user_data.get("awaiting"):
            await _exit_awaiting_flow(update, context, via_callback=True)
        else:
            await update.callback_query.answer("فعلاً چیزی برای لغو نیست.", show_alert=True)
        return

    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        if lang not in LANGUAGES:
            await update.callback_query.answer("زبان نامعتبر است.", show_alert=True)
            return
        row = db.get_user(update.effective_user.id)
        if row and row["onboarded"]:
            await on_lang_changed(update, context, lang)      # تغییر زبان
        else:
            await on_lang_selected(update, context, lang)     # onboarding
    elif data.startswith("goal:"):
        goal = data.split(":", 1)[1]
        if goal not in GOALS:
            await update.callback_query.answer("هدف نامعتبر است.", show_alert=True)
            return
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
    elif data.startswith("daily:prepare:"):
        await _handle_daily_prepare(update, context, data, review_mode=False)
    elif data.startswith("review:prepare:"):
        await _handle_daily_prepare(update, context, data, review_mode=True)
    elif data.startswith("query:prepare:"):
        await _handle_query_prepare(update, context, data.split(":", 2)[2])
    elif data.startswith("daily:next:"):
        parts = data.split(":")
        if len(parts) != 5:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        target_user_id_text, card_date, current_index_text = parts[2], parts[3], parts[4]
        today = _app_today()
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
    elif data == "review:menu":
        await _show_review_menu(update, context)
    elif data.startswith("review:page:"):
        parts = data.split(":")
        if len(parts) != 3:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        try:
            page = int(parts[2])
        except ValueError:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        await _show_review_menu(update, context, page)
    elif data.startswith("review:date:"):
        card_date = data.split(":", 2)[2]
        await _show_review_date(update, context, card_date)
    elif data.startswith("review:next:"):
        parts = data.split(":")
        if len(parts) != 5:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        target_user_id_text, card_date, current_index_text = parts[2], parts[3], parts[4]
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
        cards = db.get_daily_cards(user_id, card_date)
        if current_index + 1 >= len(cards):
            await update.callback_query.answer("کارت دیگری برای این روز وجود ندارد.", show_alert=True)
            return
        await update.callback_query.answer()
        try:
            await _send_card_from_store(
                context,
                update.effective_chat.id,
                user_id,
                card_date,
                current_index + 1,
                review_mode=True,
            )
        except CardPreparationError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="این کارت فعلاً با اطمینان آماده نشد؛ لطفاً بعداً دوباره امتحان کنید.",
            )
    elif data == "review:noop":
        await update.callback_query.answer("هنوز کارتی برای مرور ندارید.", show_alert=True)
    elif data.startswith("query:add:"):
        parts = data.split(":", 2)
        if len(parts) != 3:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        await _handle_query_add(update, context, parts[2])
    elif data.startswith("llm:"):
        parts = data.split(":")
        if len(parts) < 2:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        action = parts[1]
        if action == "pricing" and len(parts) >= 2:
            if len(parts) == 2 or (len(parts) == 3 and parts[2] == "back"):
                await _show_llm_cost_dashboard(update, context)
            elif len(parts) == 3 and parts[2] == "set_input":
                context.user_data["awaiting"] = "llm_price_input"
                await _edit_or_send(
                    update,
                    context,
                    "Send input cost per 1M tokens in USD:",
                    reply_markup=awaiting_inline_keyboard(),
                )
            elif len(parts) == 3 and parts[2] == "set_output":
                context.user_data["awaiting"] = "llm_price_output"
                await _edit_or_send(
                    update,
                    context,
                    "Send output cost per 1M tokens in USD:",
                    reply_markup=awaiting_inline_keyboard(),
                )
            elif len(parts) == 3 and parts[2] == "set_rate":
                context.user_data["awaiting"] = "llm_price_rate"
                await _edit_or_send(
                    update,
                    context,
                    "Send the USD→Toman rate:",
                    reply_markup=awaiting_inline_keyboard(),
                )
            else:
                await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        if action == "range" and len(parts) == 3:
            _llm_cost_set_state(context, range=parts[2], detail=False)
            await _show_llm_cost_dashboard(update, context)
        elif action == "set" and len(parts) == 3:
            field = parts[2]
            if field == "plan":
                await _edit_or_send(
                    update,
                    context,
                    "Select a plan:",
                    reply_markup=llm_cost_plan_keyboard(),
                )
            elif field == "user":
                context.user_data["awaiting"] = "llm_cost_user"
                await _edit_or_send(
                    update,
                    context,
                    "Send a user_id or @username, or type all:",
                    reply_markup=awaiting_inline_keyboard(),
                )
            elif field == "kind":
                await _edit_or_send(
                    update,
                    context,
                    "Select a request kind:",
                    reply_markup=llm_cost_kind_keyboard(),
                )
            elif field == "model":
                context.user_data["awaiting"] = "llm_cost_model"
                await _edit_or_send(
                    update,
                    context,
                    "نام مدل را بفرست، یا بنویس all:",
                    reply_markup=awaiting_inline_keyboard(),
                )
            elif field == "status":
                await _edit_or_send(
                    update,
                    context,
                    "Select a status:",
                    reply_markup=llm_cost_status_keyboard(),
                )
            else:
                await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
        elif action == "plan" and len(parts) == 3:
            _llm_cost_set_state(context, plan=None if parts[2] == "all" else parts[2], detail=False)
            await _show_llm_cost_dashboard(update, context)
        elif action == "kind" and len(parts) == 3:
            _llm_cost_set_state(context, request_kind=None if parts[2] == "all" else parts[2], detail=False)
            await _show_llm_cost_dashboard(update, context)
        elif action == "status" and len(parts) == 3:
            _llm_cost_set_state(context, outcome=None if parts[2] == "all" else parts[2], detail=False)
            await _show_llm_cost_dashboard(update, context)
        elif action == "clear":
            context.user_data["llm_cost_state"] = _llm_cost_default_state()
            await _show_llm_cost_dashboard(update, context)
        elif action == "refresh":
            await _show_llm_cost_dashboard(update, context)
        elif action == "recent":
            _llm_cost_set_state(context, detail=not bool(_llm_cost_state(context).get("detail")))
            await _show_llm_cost_dashboard(update, context)
        else:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
    elif data.startswith("srs:prepare:"):
        parts = data.split(":")
        if len(parts) != 4:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        await _handle_srs_prepare(update, context, parts[2], parts[3])
    elif data.startswith("srs:"):
        parts = data.split(":")
        if len(parts) != 4:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        await _handle_srs_review(update, parts[1], parts[2], parts[3])
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


async def _send_with_retry(
    bot,
    chat_id: int,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup=None,
):
    for attempt in range(3):
        try:
            async with _telegram_slots:
                kwargs = {"chat_id": chat_id, "text": text}
                if parse_mode is not None:
                    kwargs["parse_mode"] = parse_mode
                if reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                return await bot.send_message(**kwargs)
        except BadRequest:
            raise
        except RetryAfter as exc:
            if attempt == 2:
                raise
            await asyncio.sleep(min(float(exc.retry_after), 30))
        except (TimedOut, NetworkError):
            if attempt == 2:
                raise
            await asyncio.sleep(2**attempt)


async def _dispatch_queue(context: ContextTypes.DEFAULT_TYPE, delivery_date: str):
    now = datetime.datetime.now(_app_timezone).isoformat()
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
            streak = row["streak"] or 0
            for offset, card in enumerate(cards[claimed["sent_count"] :], start=claimed["sent_count"]):
                card = await asyncio.to_thread(
                    _prepare_cached_card,
                    card,
                    lang=row["target_lang"],
                    user_id=user_id,
                    plan=row["plan"] or "free",
                    source="scheduled_daily",
                    persist_patch=lambda patch, card_index=claimed["card_start_index"] + offset: (
                        db.update_daily_card_fields(
                            user_id,
                            claimed["delivery_date"],
                            card_index,
                            patch,
                        )
                    ),
                )
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
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=daily_card_keyboard(
                        user_id,
                        claimed["delivery_date"],
                        claimed["card_start_index"] + offset,
                        False,
                        show_translations=True,
                    ),
                )
                db.advance_delivery_progress(claimed["id"], offset + 1)
                if offset + 1 < len(cards):
                    await asyncio.sleep(SESSION_CARD_DELAY_SECONDS)
            db.mark_delivery_sent(claimed["id"])
        except Exception as exc:
            if isinstance(exc, CardPreparationError):
                try:
                    await _send_with_retry(
                        context.bot,
                        user_id,
                        "یکی از کارت‌ها نتونست با اطمینان آماده بشه؛ لطفاً بعداً دوباره امتحان کن.",
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
                except Exception:
                    log.exception("failed to report card preparation error to user %s", user_id)
            attempts = claimed["attempts"]
            if attempts >= DELIVERY_MAX_ATTEMPTS:
                db.mark_delivery_failed(
                    claimed["id"],
                    repr(exc),
                    terminal=True,
                )
            else:
                delay = DELIVERY_RETRY_BASE_SECONDS * (2 ** (attempts - 1))
                retry_at = (
                    datetime.datetime.now(datetime.timezone.utc)
                    + datetime.timedelta(seconds=delay)
                ).isoformat()
                db.mark_delivery_failed(
                    claimed["id"],
                    repr(exc),
                    retry_at=retry_at,
                )
            log.exception("scheduled delivery failed for user %s", user_id)


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    today = datetime.datetime.now(_app_timezone).date().isoformat()
    stale_before = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(minutes=15)
    ).isoformat()
    db.requeue_stale_deliveries(stale_before, DELIVERY_MAX_ATTEMPTS)
    await asyncio.to_thread(_plan_daily_queue, today)
    await _dispatch_queue(context, today)


async def startup_catch_up_job(context: ContextTypes.DEFAULT_TYPE):
    for job in (daily_job, delivery_dispatch_job, srs_job):
        try:
            await job(context)
        except Exception:
            log.exception("startup catch-up job failed for %s", job.__name__)


async def delivery_dispatch_job(context: ContextTypes.DEFAULT_TYPE):
    await _dispatch_queue(
        context,
        _app_today(),
    )


async def srs_job(context: ContextTypes.DEFAULT_TYPE):
    """یادآوری واژه‌های ذخیره‌شده‌ی سررسیدشده (مرور فاصله‌دار)."""
    for row in db.all_active_users():
        user_id = row["user_id"]
        try:
            due = db.due_words_for_user(user_id)
            if not due:
                continue
            for word in due:
                card = await asyncio.to_thread(
                    _prepare_cached_card,
                    _saved_word_card(word),
                    lang=word["lang"],
                    user_id=user_id,
                    plan=row["plan"] or "free",
                    source="srs",
                    persist_patch=lambda patch, word_id=word["id"]: db.update_saved_word_fields(
                        word_id,
                        user_id,
                        patch,
                    ),
                )
                await _send_with_retry(
                    context.bot,
                    user_id,
                    format_card(
                        card,
                        footer=(
                            "⏰ مرور فاصله‌دار: اول معنی، مثال و نکته را از حفظ "
                            "یادآوری کن؛ بعد نتیجه را با دکمه‌ها ثبت کن."
                        ),
                    ),
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=srs_review_keyboard(
                        user_id,
                        word["id"],
                        show_translations=True,
                    ),
                )
                db.mark_word_review_pending(word["id"])
                log.info("srs review reminder sent user_id=%s word_id=%s", user_id, word["id"])
        except CardPreparationError:
            try:
                await _send_with_retry(
                    context.bot,
                    user_id,
                    "یکی از کارت‌های مرور نتونست با اطمینان آماده بشه؛ لطفاً بعداً دوباره امتحان کن.",
                )
            except Exception:
                log.exception("failed to report SRS card preparation error for %s", user_id)
            log.exception("SRS card preparation failed for user %s", user_id)
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
        app.job_queue.run_once(startup_catch_up_job, when=1)
        app.job_queue.run_daily(
            daily_job,
            time=datetime.time(hour=0, minute=1, tzinfo=_app_timezone),
        )
        app.job_queue.run_repeating(delivery_dispatch_job, interval=60, first=0)
        app.job_queue.run_daily(
            srs_job,
            time=datetime.time(
                hour=SRS_REMINDER_MINUTE // 60,
                minute=SRS_REMINDER_MINUTE % 60,
                tzinfo=_app_timezone,
            ),
        )

    log.info("ربات هم‌زبان استارت شد.")
    app.run_polling()


if __name__ == "__main__":
    main()
