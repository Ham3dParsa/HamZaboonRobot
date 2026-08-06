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
    query_result_keyboard,
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
    _handle_query_prepare,
    _show_settings_menu,
    _custom_word_input_error,
    _word_query_usage_text,
)

from handlers.study_handler import handle_study_start

from handlers.srs_handler import (
    _handle_first_exposure_grade,
    _handle_query_add,
    _handle_srs_review,
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
_OFFLINE_MESSAGE = "متاسفانه به دلیل مشکلات موقتی فنی، فعلا قادر به انجام این درخواست نیستیم 🙏 لطفا بعدا تلاش کنید. ⏳"
_AI_BUSY_MESSAGE = "هوش مصنوعی الان شلوغه؛ کمی بعد دوباره تلاش کن."


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
            "متاسفانه به دلیل مشکلات موقتی فنی، فعلا قادر به انجام این درخواست نیستیم 🙏 لطفا بعدا تلاش کنید. ⏳",
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
        elif awaiting.startswith("admin_plan_full_edit:"):
            context.user_data.pop("plan_full_edit", None)
            await _exit_awaiting_flow(update, context, via_callback=True)
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
            elif awaiting.startswith("admin_plan_full_edit:"):
                context.user_data.pop("plan_full_edit", None)
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
    elif data.startswith("query:prepare:"):
        await _handle_query_prepare(update, context, data.split(":", 2)[2])
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
