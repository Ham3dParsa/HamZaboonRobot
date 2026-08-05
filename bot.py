import asyncio
import datetime
import logging
import math
import threading
import time
from collections import defaultdict, deque

import colorlog

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
    APP_TZ,
    AI_CARD_OUTPUT_FORMAT,
    ASK_WORD_AI_TIMEOUT_SECONDS,
    CONNECTION_HEALTH_INTERVAL_SECONDS,
    PREMIUM_PLANS,
    OWNER_BYPASS_LIMITS,
    daily_word_query_limit_for_plan,
    effective_daily_allowance,
    presentation_for_user,
    _app_today,
    _user_presentation,
    _user_plan,
    is_owner,
    LOG_LEVEL,
    COST,
    USER_ACTIVITY,
)
from services import db
from services.ai import ai
from services.ai import prompts
from services import tts
from config.catalog import (
    GOALS,
    LANGUAGES,
    LEVELS,
    goal_label,
    language_label,
    level_cefr,
    level_label,
)
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut
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
    srs_hidden_keyboard,
    srs_revealed_keyboard,
    srs_review_keyboard,
    daily_card_keyboard,
    study_start_keyboard,
    BTN_STUDY_SESSION,
    BTN_ASK_WORD,
    BTN_ADMIN,
    BTN_SETTINGS,
    BTN_CANCEL,
    BTN_BACK,
)

from services.utils.formatting import (
    CardPreparationError,
    format_card,
    format_srs_prompt,
    _phonetic_lines,
)

from services.utils.helpers import (
    _answer_callback_safely,
    _delete_with_retry,
    _edit_with_retry,
    _exit_awaiting_flow,
    _finish_llm_wait_state,
    _is_cancel_input,
    _normalize_custom_word_input,
    _send_with_retry,
    _send_voice_with_retry,
    _start_llm_wait_state,
    _telegram_slots,
    _user_activity_line,
    _CANCEL_INPUTS,
    _CUSTOM_WORD_MAX_CHARS,
    _CUSTOM_WORD_MAX_WORDS,
)

from services.ai.llm_services import (
    _call_ai_limited,
    _ask_batch_limited,
    _prepare_cached_card,
    _retry_primary_preset,
)

from handlers.admin import (
    open_admin_panel,
    _handle_admin_callback,
    _handle_admin_text_input,
    _handle_llm_callback,
    _edit_ai_preset,
    cmd_backup,
    cmd_restore,
    handle_restore_doc,
    auto_backup_job,
)

from handlers.user import (
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
    ask_for_ask_word,
    show_status,
    _handle_daily_prepare,
    _handle_query_prepare,
    _show_review_menu,
    _show_settings_menu,
    _custom_word_input_error,
    _word_query_usage_text,
)

from handlers.study_handler import handle_study_start

from handlers.srs_handler import (
    _handle_first_exposure_grade,
    _handle_query_add,
    _handle_srs_review,
    _handle_srs_reveal,
    _handle_srs_prepare,
    _saved_word_card,
)

logging.addLevelName(COST, "COST")
logging.addLevelName(USER_ACTIVITY, "USER")

_LEVEL_EMOJI = {
    logging.DEBUG: "",
    logging.INFO: "",
    logging.WARNING: "⚠ ",
    logging.ERROR: "✕ ",
    logging.CRITICAL: "⊗ ",
    COST: "💰 ",
    USER_ACTIVITY: "👤 ",
}

_LEVEL_COL_WIDTH = 10

class _LogFormatter(colorlog.ColoredFormatter):
    """ColourFormattter that prefixes level name with a severity emoji.
    Uses a custom %(leveldisplay)s attribute so the column aligns even when the
    level-name contains double-width (emoji) characters."""
    def format(self, record):
        emoji = _LEVEL_EMOJI.get(record.levelno, "")
        raw = record.levelname
        if emoji:
            display = f"{emoji}{raw}"
            record.levelname = display
        else:
            display = raw
            record.levelname = raw
        visual = sum(2 if ord(c) >= 0x1F000 else 1 for c in display)
        pad = _LEVEL_COL_WIDTH - visual
        if pad > 0:
            display += " " * pad
        record.leveldisplay = display
        return super().format(record)

_handler = colorlog.StreamHandler()
_handler.setFormatter(_LogFormatter(
    "%(log_color)s%(asctime)s%(reset)s │ %(log_color)s%(leveldisplay)s%(reset)s │ %(log_color)s%(name)-24s%(reset)s │ %(log_color)s%(message)s%(reset)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    log_colors={
        "DEBUG": "thin_cyan",
        "INFO": "thin_white",
        "⚠ WARNING": "yellow",
        "✕ ERROR": "bold_red",
        "⊗ CRITICAL": "bold_red,bg_white",
        "💰 COST": "bold_blue",
        "👤 USER": "bold_cyan",
    },
))
_log_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(level=_log_level, handlers=[_handler], force=True)
for _quiet_logger_name in ("apscheduler", "httpcore", "httpx", "telegram"):
    logging.getLogger(_quiet_logger_name).setLevel(logging.WARNING)
log = logging.getLogger(__name__)

def _apply_log_level(level_name: str) -> None:
    """Set root logger level and quieter external loggers accordingly."""
    level = getattr(logging, level_name.upper(), None)
    if level is None:
        return
    logging.getLogger().setLevel(level)
    for name in ("apscheduler", "httpcore", "httpx", "telegram"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))
    log.info("log level set to %s", level_name.upper())


_app_timezone = APP_TZ
_daily_locks: dict[int, asyncio.Lock] = {}
_daily_locks_guard: threading.Lock = threading.Lock()


def _get_user_lock(user_id: int) -> asyncio.Lock:
    with _daily_locks_guard:
        if user_id not in _daily_locks:
            _daily_locks[user_id] = asyncio.Lock()
        return _daily_locks[user_id]


_telegram_offline: bool = False
_consecutive_health_failures: int = 0
_OFFLINE_THRESHOLD: int = 1
_OFFLINE_MESSAGE = "⚠️ اتصال ربات به اینترنت قطع شده. به محض وصل شدن، دوباره تلاش کن."
_AI_BUSY_MESSAGE = "هوش مصنوعی الان شلوغه؛ کمی بعد دوباره تلاش کن."


async def _send_card_from_store(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    card_date: str,
    card_index: int,
    *,
    review_mode: bool = False,
    callback_query=None,
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
    progress = db.get_daily_progress(user_id, card_date)
    if not review_mode:
        limit = effective_daily_allowance(
            row["plan"] or "free",
            row["optional_daily_limit"],
            OWNER_BYPASS_LIMITS and is_owner(user_id),
        )
        next_index = card_index + 1
        has_next = next_index < limit
        next_card_is_new = next_index >= progress
    else:
        has_next = card_index + 1 < len(cards)
        next_card_is_new = False
    markup = daily_card_keyboard(
        user_id,
        card_date,
        card_index,
        has_next,
        callback_prefix="review:next" if review_mode else "daily:next",
        show_translations=True,
        show_pronounce=db.get_setting("tts_access", "premium") != "none" and (_user_plan(row) in PREMIUM_PLANS or db.get_setting("tts_access", "premium") == "all"),
        has_prev=card_index > 0,
        next_card_is_new=next_card_is_new,
    )
    text = format_card(
        card,
        footer=footer,
        presentation=_user_presentation(row),
        phonetic_lines=phon_lines,
    )
    if callback_query:
        try:
            await _edit_with_retry(callback_query, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)
            return card, len(cards)
        except BadRequest:
            pass
    await _send_with_retry(context.bot, chat_id, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)
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

    active_preset = db.get_active_preset()
    provenance = active_preset.get("name", "unknown") if active_preset else "unknown"
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
        db.add_daily_card(user_id, card_date, len(cards) + offset, card, provenance=provenance)
    return db.get_daily_cards(user_id, card_date)


def _ensure_next_daily_card(user_id: int, row, card_date: str, limit: int) -> tuple[dict | None, int]:
    session = _daily_card_session_profile(user_id, row, card_date)
    next_index = db.get_daily_progress(user_id, card_date)
    if next_index >= limit:
        return None, next_index

    cards = db.get_daily_cards(user_id, card_date)
    if next_index >= len(cards):
        active_preset = db.get_active_preset()
        provenance = active_preset.get("name", "unknown") if active_preset else "unknown"
        batch_size = active_preset.get("daily_batch_size", 6) if active_preset else 6
        used_words = _daily_avoid_words(user_id, session["target_lang"], card_date, cards)
        remaining = limit - len(cards)
        new_cards = _generate_daily_batch(
            session["target_lang"],
            session["goal"],
            session["level"],
            min(batch_size, remaining),
            used_words,
            user_id,
            row["plan"] or "free",
        )
        if not new_cards:
            raise RuntimeError("AI returned no card for the requested daily card")
        for offset, card in enumerate(new_cards):
            db.add_daily_card(user_id, card_date, len(cards) + offset, card, provenance=provenance)
        cards = db.get_daily_cards(user_id, card_date)

    card = cards[next_index]
    return card, next_index


async def _send_next_daily_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    row,
    card_date: str,
    limit: int,
    *,
    callback_query=None,
):
    user_id = row["user_id"]
    async with _get_user_lock(user_id):
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
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            f"✅ سهمیه‌ی امروزت ({limit} کارت) کامل شده است.",
            reply_markup=daily_review_menu_keyboard(),
        )
        return

    db.touch_streak(user_id)
    log.info("daily card delivered user_id=%s date=%s index=%s", user_id, card_date, card_index)
    phon_lines = _phonetic_lines(card.get("phonetic", ""))
    markup = daily_card_keyboard(
        user_id,
        card_date,
        card_index,
        card_index + 1 < limit,
        show_translations=True,
        show_pronounce=db.get_setting("tts_access", "premium") != "none" and (_user_plan(row) in PREMIUM_PLANS or db.get_setting("tts_access", "premium") == "all"),
        has_prev=card_index > 0,
    )
    text = format_card(
        card,
        footer=f"📖 کارت {card_index + 1} از {limit} امروز",
        presentation=_user_presentation(row),
        phonetic_lines=phon_lines,
    )
    if callback_query:
        try:
            await _edit_with_retry(callback_query, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)
            return
        except BadRequest:
            pass
    await _send_with_retry(context.bot, update.effective_chat.id, text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=markup)


async def send_daily_card_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await _send_with_retry(context.bot, update.effective_chat.id, "اول باید /start رو بزنی.")
        return

    today = _app_today()
    plan = _user_plan(row)
    limit = effective_daily_allowance(
        row["plan"] or "free",
        row["optional_daily_limit"],
        OWNER_BYPASS_LIMITS and is_owner(user_id),
    )

    user = update.effective_user
    _ua_line = _user_activity_line(
        user_id=user_id, full_name=user.full_name, username=user.username,
        action="daily_card", outcome="started",
        plan=row["plan"], lang=row["target_lang"], goal=row["goal"], level=row["level"],
    )
    if _ua_line:
        log.log(USER_ACTIVITY, "%s", _ua_line)

    wait_message = await _start_llm_wait_state(
        update,
        context,
        "⏳ دارم کارت امروز رو می‌سازم…",
    )
    success = True
    try:
        await _send_next_daily_card(update, context, row, today, limit)
    except Exception:
        success = False
        log.exception("Daily card generation failed")
        await _send_with_retry(context.bot, update.effective_chat.id, "مشکلی در ساخت کارت‌های امروز پیش اومد.")
    finally:
        await _finish_llm_wait_state(wait_message, bot=context.bot)
        _ua_line2 = _user_activity_line(
            user_id=user_id, full_name=user.full_name, username=user.username,
            action="daily_card", outcome="success" if success else "error",
            plan=row["plan"], lang=row["target_lang"], goal=row["goal"], level=row["level"],
        )
        if _ua_line2:
            log.log(USER_ACTIVITY, "%s", _ua_line2)
















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
        callback_query=update.callback_query,
    )


# ---------------- روتر پیام‌های متنی (منو + حالت‌های در انتظار ورودی) ----------------

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _telegram_offline:
        try:
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
                _OFFLINE_MESSAGE,
            )
        except Exception:
            log.debug("offline notification send failed (expected)")
        return
    user_id = update.effective_user.id
    db.reset_user_blocked(user_id)
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
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    f"{error}\n\nچه واژه یا عبارتی رو می‌خوای معنی/توضیح بدم؟",
                    reply_markup=awaiting_inline_keyboard(),
                )
                return
            if not db.reserve_word_query(
                user_id,
                limit,
                bypass_limits=OWNER_BYPASS_LIMITS and is_owner(user_id),
            ):
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    f"سقف روزانه‌ی پرسش واژه‌ی پلن شما ({limit} بار) تموم شده.",
                    reply_markup=main_menu(is_owner(user_id)),
                )
                return
            wait_message = await _start_llm_wait_state(
                update,
                context,
                "⏳ دارم معنی و توضیحش رو پیدا می‌کنم…",
            )
            deadline = time.monotonic() + ASK_WORD_AI_TIMEOUT_SECONDS
            try:
                data = await asyncio.wait_for(
                    asyncio.to_thread(
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
                        deadline=deadline,
                    ),
                    timeout=max(0.0, deadline - time.monotonic()),
                )
            except asyncio.TimeoutError:
                db.release_word_query(user_id)
                await _finish_llm_wait_state(wait_message)
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    _AI_BUSY_MESSAGE,
                    reply_markup=main_menu(is_owner(user_id)),
                )
                return
            except Exception:
                db.release_word_query(user_id)
                log.exception("AI error")
                await _finish_llm_wait_state(wait_message)
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    "مشکلی در ارتباط با هوش مصنوعی پیش اومد، دوباره امتحان کن.",
                    reply_markup=main_menu(is_owner(user_id)),
                )
                return
            try:
                data = await asyncio.wait_for(
                    asyncio.to_thread(
                        _prepare_cached_card,
                        data,
                        lang=row["target_lang"],
                        user_id=user_id,
                        plan=row["plan"] or "free",
                        source="custom_word",
                        persist_patch=lambda patch: True,
                        deadline=deadline,
                    ),
                    timeout=max(0.0, deadline - time.monotonic()),
                )
            except asyncio.TimeoutError:
                db.release_word_query(user_id)
                await _finish_llm_wait_state(wait_message)
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    _AI_BUSY_MESSAGE,
                    reply_markup=main_menu(is_owner(user_id)),
                )
                return
            except CardPreparationError:
                db.release_word_query(user_id)
                await _finish_llm_wait_state(wait_message)
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
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
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
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
                    show_pronounce=db.get_setting("tts_access", "premium") != "none" and (_user_plan(row) in PREMIUM_PLANS or db.get_setting("tts_access", "premium") == "all"),
                ),
            )
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
                "به منوی اصلی برگشتی 🙂",
                reply_markup=main_menu(is_owner(user_id)),
            )
            return

        if awaiting.startswith("admin_") or awaiting.startswith("llm_cost_") or awaiting.startswith("llm_price_") or awaiting.startswith("ai_preset_") or awaiting.startswith("ai_custom_test_"):
            await _handle_admin_text_input(update, context, awaiting, text)
            return

    # مسیر دکمه‌های منوی اصلی
    if text == BTN_STUDY_SESSION:
        await handle_study_start(update, context)
    elif text == BTN_ASK_WORD:
        await ask_for_ask_word(update, context)
    elif text == BTN_SETTINGS:
        await _show_settings_menu(update, context)
    elif text == BTN_ADMIN:
        await open_admin_panel(update, context)
    else:
        await _send_with_retry(context.bot, update.effective_chat.id, "از دکمه‌های پایین استفاده کن 🙂", reply_markup=main_menu(is_owner(user_id)))


# ---------------- روتر callback query ها ----------------

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _telegram_offline:
        await _answer_callback_safely(
            update.callback_query,
            "ربات به اینترنت دسترسی ندارد.",
            show_alert=True,
        )
        try:
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
                _OFFLINE_MESSAGE,
            )
        except Exception:
            log.debug("offline notification send failed (expected)")
        return
    db.reset_user_blocked(update.effective_user.id)
    data = update.callback_query.data
    if not data.startswith(
        (
            "study:start",
            "query:add:",
            "query:prepare:",
            "daily:prepare:",
            "daily:prev:",
            "review:prepare:",
            "presentation:",
            "flow:",
            "srs:",
            "tts:pronounce:",
            "settings:",
        )
    ):
        await update.callback_query.answer()

    if data == "flow:back":
        awaiting = context.user_data.get("awaiting", "")
        if awaiting.startswith("ai_preset_edit:"):
            preset_name = awaiting.split(":", 1)[1].rsplit(":", 1)[0]
            context.user_data.pop("awaiting", None)
            await _edit_ai_preset(update, context, preset_name)
        elif awaiting.startswith("ai_preset_full_edit:"):
            preset_name = awaiting.split(":", 2)[1]
            context.user_data.pop("full_edit", None)
            context.user_data.pop("awaiting", None)
            await _edit_ai_preset(update, context, preset_name)
        elif awaiting:
            await _exit_awaiting_flow(update, context, via_callback=True)
        else:
            await update.callback_query.answer("فعلاً چیزی برای لغو نیست.", show_alert=True)
        return

    if data == "flow:cancel":
        awaiting = context.user_data.get("awaiting", "")
        if awaiting:
            if awaiting.startswith("ai_preset_edit:"):
                preset_name = awaiting.split(":", 1)[1].rsplit(":", 1)[0]
                context.user_data.setdefault("preset_edits", {}).pop(preset_name, None)
            elif awaiting.startswith("ai_preset_full_edit:"):
                context.user_data.pop("full_edit", None)
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
        await _edit_with_retry(
            update.callback_query,
            f"نمایش کارت‌ها روی «{label}» تنظیم شد.",
            reply_markup=presentation_settings_keyboard(preference, back_to_settings=True),
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

        progress = db.get_daily_progress(user_id, today)
        next_index = current_index + 1

        if next_index < progress:
            await update.callback_query.answer()
            try:
                await _send_card_from_store(context, update.effective_chat.id, user_id, today, next_index, callback_query=update.callback_query)
            except CardPreparationError:
                await _send_with_retry(context.bot, update.effective_chat.id, "این کارت فعلاً با اطمینان آماده نشد؛ بعداً دوباره امتحان کنید.")
            return

        if next_index > progress:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
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
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
                "مشکلی در ساخت کارت بعدی پیش اومد.",
            )
    elif data.startswith("daily:prev:"):
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
        prev_index = current_index - 1
        if prev_index < 0:
            await update.callback_query.answer("این اولین کارت است.", show_alert=True)
            return
        await update.callback_query.answer()
        try:
            await _send_card_from_store(context, update.effective_chat.id, user_id, card_date, prev_index, callback_query=update.callback_query)
        except CardPreparationError:
            await _send_with_retry(context.bot, update.effective_chat.id, "این کارت فعلاً با اطمینان آماده نشد؛ بعداً دوباره امتحان کنید.")
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
                callback_query=update.callback_query,
            )
        except CardPreparationError:
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
                "این کارت فعلاً با اطمینان آماده نشد؛ لطفاً بعداً دوباره امتحان کنید.",
            )
    elif data == "review:noop":
        await update.callback_query.answer("هنوز کارتی برای مرور ندارید.", show_alert=True)
    elif data.startswith("query:add:"):
        parts = data.split(":", 2)
        if len(parts) != 3:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        await _handle_query_add(update, context, parts[2])
    elif data == "settings:lang":
        await change_lang_start(update, context)
    elif data == "settings:goal":
        await change_goal_start(update, context)
    elif data == "settings:level":
        await change_level_start(update, context)
    elif data == "settings:presentation":
        await change_presentation_start(update, context)
    elif data == "settings:status":
        await show_status(update, context)
    elif data == "settings:back":
        await _show_settings_menu(update, context)
    elif data == "settings:close":
        try:
            await update.callback_query.message.delete()
            await _answer_callback_safely(update.callback_query, "بسته شد.")
        except BadRequest:
            await _answer_callback_safely(update.callback_query)
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
    elif data.startswith("srs:fe:"):
        parts = data.split(":")
        if len(parts) != 5:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        await _handle_first_exposure_grade(update, context, parts[2], parts[3], parts[4])
    elif data.startswith("srs:"):
        parts = data.split(":")
        if len(parts) != 4:
            await update.callback_query.answer("دکمه‌ی نامعتبر است.", show_alert=True)
            return
        try:
            grade = int(parts[1])
        except ValueError:
            log.warning("Unrecognized srs callback: %s", data)
            await update.callback_query.answer("این دکمه دیگر معتبر نیست.", show_alert=False)
            return
        if grade not in (1, 2, 3, 4):
            log.warning("Unrecognized srs callback: %s", data)
            await update.callback_query.answer("این دکمه دیگر معتبر نیست.", show_alert=False)
            return
        await _handle_srs_review(update, grade, parts[2], parts[3], context)
    elif data == "study:start":
        await handle_study_start(update, context)
    elif data.startswith("tts:pronounce:"):
        await _handle_tts_pronounce(update, context, data.split(":", 2)[2])
    elif data.startswith("admin:"):
        await _handle_admin_callback(update, context, data.split(":", 1)[1])


async def connection_health_job(context: ContextTypes.DEFAULT_TYPE):
    global _telegram_offline, _consecutive_health_failures
    try:
        async with _telegram_slots:
            await context.bot.get_me()
    except (RetryAfter, TimedOut, NetworkError) as exc:
        _consecutive_health_failures += 1
        if _consecutive_health_failures >= _OFFLINE_THRESHOLD:
            was_offline = _telegram_offline
            _telegram_offline = True
            if not was_offline:
                log.warning(
                    "Telegram marked offline after %s consecutive failures",
                    _consecutive_health_failures,
                )
        log.warning(
            "Telegram connection check failed (%s/%s): %s",
            _consecutive_health_failures,
            _OFFLINE_THRESHOLD,
            exc,
        )
    except Exception:
        _consecutive_health_failures += 1
        log.exception("Telegram connection check failed unexpectedly")
    else:
        was_offline = _telegram_offline
        _telegram_offline = False
        _consecutive_health_failures = 0
        if was_offline:
            log.info("Telegram connection restored")
        else:
            log.info("Telegram connection healthy")


async def _handle_tts_pronounce(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split(":")
    if len(parts) < 2:
        await update.callback_query.answer("دکمه نامعتبر است.", show_alert=True)
        return

    source = parts[0]
    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await update.callback_query.answer("ابتدا /start را بزنید.", show_alert=True)
        return

    tts_access = db.get_setting("tts_access", "premium")
    if tts_access == "none":
        await update.callback_query.answer("تلفظ غیرفعال است.", show_alert=True)
        return
    if tts_access == "premium" and _user_plan(row) not in PREMIUM_PLANS:
        await update.callback_query.answer("این قابلیت فقط برای کاربران نقره‌ای و طلایی فعال است.", show_alert=True)
        return

    word = None
    lang = None

    if source == "d":
        if len(parts) != 4:
            await update.callback_query.answer("دکمه نامعتبر است.", show_alert=True)
            return
        try:
            target_user_id = int(parts[1])
            card_date = parts[2]
            card_index = int(parts[3])
        except ValueError:
            await update.callback_query.answer("دکمه نامعتبر است.", show_alert=True)
            return
        if user_id != target_user_id:
            await update.callback_query.answer("این کارت برای کاربر دیگری است.", show_alert=True)
            return
        cards = db.get_daily_cards(user_id, card_date)
        if card_index < 0 or card_index >= len(cards):
            await update.callback_query.answer("کارت پیدا نشد.", show_alert=True)
            return
        card_data = cards[card_index]
        if isinstance(card_data, dict):
            word = card_data.get("word", "")
        elif isinstance(card_data, str):
            try:
                import json
                card_data = json.loads(card_data)
                word = card_data.get("word", "")
            except (json.JSONDecodeError, TypeError):
                pass
        session = db.get_daily_card_session(user_id, card_date)
        lang = session["target_lang"] if session else row["target_lang"]

    elif source == "q":
        if len(parts) != 2:
            await update.callback_query.answer("دکمه نامعتبر است.", show_alert=True)
            return
        token = parts[1]
        qr = db.get_query_result(token, user_id=user_id)
        if not qr:
            await update.callback_query.answer("این نتیجه منقضی شده است.", show_alert=True)
            return
        word = qr["word"]
        lang = qr["lang"]

    elif source == "s":
        if len(parts) != 3:
            await update.callback_query.answer("دکمه نامعتبر است.", show_alert=True)
            return
        try:
            target_user_id = int(parts[1])
            word_id = int(parts[2])
        except ValueError:
            await update.callback_query.answer("دکمه نامعتبر است.", show_alert=True)
            return
        if user_id != target_user_id:
            await update.callback_query.answer("این مرور برای کاربر دیگری است.", show_alert=True)
            return
        sw = db.get_saved_word(word_id, user_id=user_id)
        if not sw:
            await update.callback_query.answer("واژه در مرور شما پیدا نشد.", show_alert=True)
            return
        word = sw["word"]
        lang = sw["lang"]

    else:
        await update.callback_query.answer("دکمه نامعتبر است.", show_alert=True)
        return

    if not word or not lang:
        await update.callback_query.answer("واژه یا زبان نامعتبر است.", show_alert=True)
        return

    await update.callback_query.answer("🎧 در حال آماده‌سازی تلفظ…")

    try:
        path = await tts.pronounce(word, lang)
        voice_bytes = await asyncio.to_thread(path.read_bytes)
        await _send_voice_with_retry(
            context.bot,
            update.effective_chat.id,
            voice_bytes,
            reply_to_message_id=update.callback_query.message.message_id,
        )
    except Exception:
        log.exception("TTS pronunciation failed")
        await _send_with_retry(
            context.bot,
            update.effective_chat.id,
            "متأسفانه تولید تلفظ با خطا مواجه شد. لطفاً کمی بعد دوباره تلاش کنید.",
        )


async def primary_retry_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodically try to restore primary AI preset if fallback is active."""
    try:
        await asyncio.to_thread(_retry_primary_preset)
    except Exception:
        log.exception("Primary retry job failed")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled exception while processing update", exc_info=context.error)


def main():
    db.init_db()
    db.migrate_saved_words_to_fsrs()
    db_level = db.get_setting("log_level", "")
    if db_level:
        _apply_log_level(db_level)
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN در .env تنظیم نشده.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(CommandHandler("restore", cmd_restore))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.Document.FileExtension("db") & ~filters.COMMAND, handle_restore_doc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(error_handler)

    if app.job_queue:
        app.job_queue.run_repeating(
            connection_health_job,
            interval=CONNECTION_HEALTH_INTERVAL_SECONDS,
            first=CONNECTION_HEALTH_INTERVAL_SECONDS,
        )
        if OWNER_ID != 0:
            app.job_queue.run_repeating(
                auto_backup_job,
                interval=21600,
                first=21600,
            )
            app.job_queue.run_repeating(
                primary_retry_job,
                interval=1800,
                first=1800,
            )

    log.info("The bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
