import asyncio
import datetime
import logging
import math
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
    AI_CARD_OUTPUT_FORMAT,
    DELIVERY_MAX_ATTEMPTS,
    DELIVERY_RETRY_BASE_SECONDS,
    CONNECTION_HEALTH_INTERVAL_SECONDS,
    SESSION_CARD_DELAY_SECONDS,
    PREMIUM_PLANS,
    OWNER_BYPASS_LIMITS,
    daily_word_query_limit_for_plan,
    effective_daily_allowance,
    presentation_for_user,
    _app_today,
    _user_presentation,
    _user_plan,
    is_owner,
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
    presentation_settings_keyboard,
    awaiting_reply_keyboard,
    awaiting_inline_keyboard,
    daily_review_dates_keyboard,
    daily_review_menu_keyboard,
    query_result_keyboard,
    srs_hidden_keyboard,
    daily_card_keyboard,
    BTN_TODAY_CARD,
    BTN_ASK_WORD,
    BTN_STATUS,
    BTN_GRAMMAR,
    BTN_ADMIN,
    BTN_CHANGE_LANG,
    BTN_CHANGE_GOAL,
    BTN_CHANGE_LEVEL,
    BTN_CHANGE_PRESENTATION,
    BTN_CANCEL,
    BTN_BACK,
)

from formatting import (
    CardPreparationError,
    format_card,
    format_srs_prompt,
    _phonetic_lines,
)

from helpers import (
    _answer_callback_safely,
    _exit_awaiting_flow,
    _finish_llm_wait_state,
    _is_cancel_input,
    _normalize_custom_word_input,
    _send_with_retry,
    _start_llm_wait_state,
    _telegram_slots,
    _CANCEL_INPUTS,
    _CUSTOM_WORD_MAX_CHARS,
    _CUSTOM_WORD_MAX_WORDS,
)

from llm_services import (
    _call_ai_limited,
    _ask_batch_limited,
    _prepare_cached_card,
)

from user import (
    cmd_start,
    on_lang_selected,
    on_goal_selected,
    on_level_selected,
    change_lang_start,
    change_goal_start,
    change_level_start,
    change_presentation_start,
    on_lang_changed,
    on_goal_changed,
    on_level_changed,
    send_grammar_tip,
    ask_for_ask_word,
    show_status,
    _handle_daily_prepare,
    _handle_query_prepare,
    _show_review_menu,
    _custom_word_input_error,
    _word_query_usage_text,
    _grammar_tip_usage_text,
)

from srs_handler import (
    _handle_query_add,
    _handle_srs_review,
    _handle_srs_reveal,
    _handle_srs_prepare,
    _saved_word_card,
)

from admin import (
    _handle_admin_callback,
    _handle_admin_text_input,
    _handle_llm_callback,
    open_admin_panel,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
for _quiet_logger_name in ("apscheduler", "httpcore", "httpx", "telegram"):
    logging.getLogger(_quiet_logger_name).setLevel(logging.WARNING)
log = logging.getLogger("hamzaban")
_app_timezone = ZoneInfo(APP_TIMEZONE)
_daily_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_MANUAL_DAILY_BATCH_SIZE = 6


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
    phon_lines = _phonetic_lines(card.get("phonetic", ""))
    await context.bot.send_message(
        chat_id=chat_id,
        text=format_card(
            card,
            footer=footer,
            presentation=_user_presentation(row),
            phonetic_lines=phon_lines,
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


def _daily_avoid_words(user_id: int, target_lang: str, card_date: str, current_cards: list[dict]) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for word in db.get_recent_daily_words(user_id, target_lang, exclude_date=card_date, limit=50):
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


def _ensure_daily_cards(user_id: int, row, card_date: str, limit: int) -> list[dict]:
    session = _daily_card_session_profile(user_id, row, card_date)
    cards = db.get_daily_cards(user_id, card_date)
    if len(cards) >= limit:
        return cards

    used_words = _daily_avoid_words(user_id, session["target_lang"], card_date, cards)
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

    used_words = _daily_avoid_words(user_id, session["target_lang"], queue_row["delivery_date"], existing)
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
        used_words = _daily_avoid_words(user_id, session["target_lang"], card_date, cards)
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
    phon_lines = _phonetic_lines(card.get("phonetic", ""))
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=format_card(
            card,
            footer=f"📖 کارت {card_index + 1} از {limit} امروز",
            presentation=_user_presentation(row),
            phonetic_lines=phon_lines,
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
                    f"سقف روزانه‌ی پرسش واژه‌ی پلن شما ({limit} بار) تموم شده.",
                    reply_markup=main_menu(is_owner(user_id)),
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
                await update.message.reply_text(
                    "مشکلی در ارتباط با هوش مصنوعی پیش اومد، دوباره امتحان کن.",
                    reply_markup=main_menu(is_owner(user_id)),
                )
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
                    "این کارت نتونست با اطمینان آماده بشه؛ لطفاً بعداً دوباره امتحان کن.",
                    reply_markup=main_menu(is_owner(user_id)),
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
            phon_lines = _phonetic_lines(data.get("phonetic", ""))
            await update.message.reply_text(
                format_card(
                    data,
                    footer=(
                        f"{usage_text}\n\n"
                        "برای افزودن این واژه به مرور، از دکمه‌ی زیر استفاده کن."
                    ),
                    presentation=_user_presentation(row),
                    phonetic_lines=phon_lines,
                ),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=query_result_keyboard(
                    query_token,
                    row["target_lang"] if row else "en",
                    show_translations=True,
                ),
            )
            await update.message.reply_text(
                "به منوی اصلی برگشتی 🙂",
                reply_markup=main_menu(is_owner(user_id)),
            )
            return

        if awaiting.startswith("admin_") or awaiting.startswith("llm_cost_") or awaiting.startswith("llm_price_"):
            await _handle_admin_text_input(update, context, awaiting, text)
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
    elif text == BTN_CHANGE_PRESENTATION:
        await change_presentation_start(update, context)
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
            "presentation:",
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

    if data.startswith("presentation:set:"):
        preference = data.split(":", 2)[2]
        if preference not in {"brief", "detailed"}:
            await update.callback_query.answer("انتخاب نامعتبر است.", show_alert=True)
            return
        user_id = update.effective_user.id
        row = db.get_user(user_id)
        if not row or not row["onboarded"]:
            await update.callback_query.answer("ابتدا /start را بزنید.", show_alert=True)
            return
        if (row["plan"] or "free") not in PREMIUM_PLANS:
            await update.callback_query.answer(
                "این تنظیم فقط برای کاربران پریمیوم فعال است.",
                show_alert=True,
            )
            return
        db.set_presentation_preference(user_id, preference)
        label = "خلاصه" if preference == "brief" else "کامل"
        await update.callback_query.edit_message_text(
            f"نمایش کارت‌ها روی «{label}» تنظیم شد.",
            reply_markup=presentation_settings_keyboard(preference),
        )
        await update.callback_query.answer("تنظیمات ذخیره شد.")
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
        await _handle_llm_callback(update, context, data)
    elif data.startswith("srs:prepare:"):
        parts = data.split(":")
        if len(parts) != 4:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        await _handle_srs_prepare(update, context, parts[2], parts[3])
    elif data.startswith("srs:reveal:"):
        parts = data.split(":")
        if len(parts) != 4:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        await _handle_srs_reveal(update, context, parts[2], parts[3])
    elif data.startswith("srs:"):
        parts = data.split(":")
        if len(parts) != 4:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        await _handle_srs_review(update, parts[1], parts[2], parts[3])
    elif data.startswith("admin:"):
        await _handle_admin_callback(update, context, data.split(":", 1)[1])


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
                phon_lines = _phonetic_lines(card.get("phonetic", ""))
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
                        presentation=_user_presentation(row),
                        phonetic_lines=phon_lines,
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
    stale_before = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(minutes=15)
    ).isoformat()
    db.requeue_stale_deliveries(stale_before, DELIVERY_MAX_ATTEMPTS)
    await _dispatch_queue(
        context,
        _app_today(),
    )


async def connection_health_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        async with _telegram_slots:
            await context.bot.get_me()
    except (RetryAfter, TimedOut, NetworkError) as exc:
        log.warning("Telegram connection check failed: %s", exc)
    except Exception:
        log.exception("Telegram connection check failed unexpectedly")
    else:
        log.info("Telegram connection healthy")


async def srs_job(context: ContextTypes.DEFAULT_TYPE):
    """یادآوری واژه‌های ذخیره‌شده‌ی سررسیدشده (مرور فاصله‌دار)."""
    for row in db.all_active_users():
        user_id = row["user_id"]
        try:
            due = db.due_words_for_user(user_id)
            if not due:
                continue
            for word in due:
                word_id = word["id"]
                if not db.claim_srs_reminder(word_id):
                    continue
                try:
                    card = await asyncio.to_thread(
                        _prepare_cached_card,
                        _saved_word_card(word),
                        lang=word["lang"],
                        user_id=user_id,
                        plan=row["plan"] or "free",
                        source="srs",
                        persist_patch=lambda patch, word_id_=word_id: db.update_saved_word_fields(
                            word_id_,
                            user_id,
                            patch,
                        ),
                    )
                    phon_lines = _phonetic_lines(card.get("phonetic", ""))
                    await _send_with_retry(
                        context.bot,
                        user_id,
                        format_srs_prompt(card, phonetic_lines=phon_lines),
                        parse_mode=ParseMode.MARKDOWN_V2,
                        reply_markup=srs_hidden_keyboard(user_id, word_id),
                    )
                    if not db.mark_word_review_pending(word_id):
                        db.release_srs_claim(word_id)
                        continue
                    log.info("srs review reminder sent user_id=%s word_id=%s", user_id, word_id)
                except CardPreparationError:
                    db.release_srs_claim(word_id)
                    log.warning("SRS card preparation failed for user %s word_id=%s", user_id, word_id)
                except Exception:
                    db.release_srs_claim(word_id)
                    raise
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
        app.job_queue.run_repeating(
            connection_health_job,
            interval=CONNECTION_HEALTH_INTERVAL_SECONDS,
            first=CONNECTION_HEALTH_INTERVAL_SECONDS,
        )
        app.job_queue.run_daily(
            srs_job,
            time=datetime.time(
                hour=SRS_REMINDER_MINUTE // 60,
                minute=SRS_REMINDER_MINUTE % 60,
                tzinfo=_app_timezone,
            ),
        )

    log.info("The bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
