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
    ASK_WORD_AI_TIMEOUT_SECONDS,
    CONNECTION_HEALTH_INTERVAL_SECONDS,
    PREMIUM_PLANS,
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
from services import tts
from services import word_query
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
    format_card,
    _phonetic_lines,
)
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback

from services.utils.helpers import (
    _delete_with_retry,
    _edit_with_retry,
    _exit_awaiting_flow,
    _finish_llm_wait_state,
    _is_cancel_input,
    _send_with_retry,
    _send_voice_with_retry,
    _start_llm_wait_state,
    _telegram_slots,
    _user_activity_line,
    _CANCEL_INPUTS,
    apply_log_level,
)

from services.utils.validation import (
    _CUSTOM_WORD_MAX_CHARS,
    _CUSTOM_WORD_MAX_WORDS,
    ERR_EMPTY,
    ERR_INVALID_CHARS,
    ERR_TOO_FEW_LETTERS,
    ERR_TOO_LONG,
    ERR_TOO_MANY_WORDS,
)

# Learner-facing Persian messages for the custom-word validation error keys.
# Keys mirror the locked Rule B error vocabulary in services/utils/validation.py.
_WORD_QUERY_ERROR_MESSAGES = {
    ERR_EMPTY: "یک واژه یا عبارت کوتاه بفرست.",
    ERR_TOO_LONG: f"حداکثر {_CUSTOM_WORD_MAX_CHARS} کاراکتر مجاز است.",
    ERR_TOO_MANY_WORDS: (
        f"فقط یک واژه یا عبارت کوتاهِ حداکثر {_CUSTOM_WORD_MAX_WORDS} کلمه‌ای بفرست."
    ),
    ERR_INVALID_CHARS: "لطفاً فقط واژه یا عبارت ساده بفرست (علائم محدود مجاز است).",
    ERR_TOO_FEW_LETTERS: "یک واژه یا عبارت واقعی بفرست.",
}

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
    is_admin_awaiting,
    handle_flow_back,
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
)

from handlers.help_command import send_help_panel, handle_help_callback

from handlers.study_handler import handle_study_inactive, handle_study_start

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
_offline_notice_sent: set[int] = set()  # chat_ids notified in the current offline window


# ---------------- روتر پیام‌های متنی (منو + حالت‌های در انتظار ورودی) ----------------

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _telegram_offline:
        await _send_offline_notice(context, update.effective_chat.id)
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

        if is_admin_awaiting(awaiting) and not is_owner(user_id):
            return  # لایه‌ی امنیتی اضافه؛ در حالت عادی اصلاً به این حالت نمی‌رسد

        if awaiting == "ask_word":
            row = db.get_user(user_id)
            limit = daily_word_query_limit_for_plan(row["plan"] if row else "free")

            # --- build the rate-limited 2-step generator (handler owns Telegram infra) ---
            deadline = time.monotonic() + ASK_WORD_AI_TIMEOUT_SECONDS

            async def generate_card(*, system_prompt, user_prompt, request_kind, user_id, plan):
                # The wait-state wraps ONLY the AI pipeline, so invalid input and
                # quota-exhausted never flash a misleading "thinking" message.
                wait_message = await _start_llm_wait_state(
                    update,
                    context,
                    "⏳ دارم معنی و توضیحش رو پیدا می‌کنم…",
                )
                try:
                    data = await asyncio.wait_for(
                        asyncio.to_thread(
                            _call_ai_limited,
                            ai.ask_card,
                            system_prompt,
                            user_prompt=user_prompt,
                            request_kind=request_kind,
                            user_id=user_id,
                            plan=plan,
                            deadline=deadline,
                        ),
                        timeout=max(0.0, deadline - time.monotonic()),
                    )
                    return await asyncio.wait_for(
                        asyncio.to_thread(
                            _prepare_cached_card,
                            data,
                            lang=row["target_lang"],
                            user_id=user_id,
                            plan=plan or "free",
                            source="custom_word",
                            persist_patch=lambda patch: True,
                            deadline=deadline,
                        ),
                        timeout=max(0.0, deadline - time.monotonic()),
                    )
                finally:
                    await _finish_llm_wait_state(wait_message)

            result = await word_query.ask(
                user_id,
                text,
                lang=row["target_lang"] if row else "en",
                level=row["level"] if row else "...",
                plan=row["plan"] if row else "free",
                generate_card=generate_card,
            )

            if result.kind == "invalid_input":
                context.user_data["awaiting"] = "ask_word"
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    f"{_WORD_QUERY_ERROR_MESSAGES[result.error_key]}\n\nچه واژه یا عبارتی رو می‌خوای معنی/توضیح بدم؟",
                    reply_markup=awaiting_inline_keyboard(),
                )
                return
            if result.kind == "quota_exhausted":
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    f"سقف روزانه‌ی پرسش واژه‌ی پلن شما ({limit} بار) تموم شده.",
                    reply_markup=main_menu(is_owner(user_id)),
                )
                return
            if result.kind == "ai_timeout":
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    _AI_BUSY_MESSAGE,
                    reply_markup=main_menu(is_owner(user_id)),
                )
                return
            if result.kind == "ai_error":
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    "مشکلی در ارتباط با هوش مصنوعی پیش اومد، دوباره امتحان کن.",
                    reply_markup=main_menu(is_owner(user_id)),
                )
                return
            if result.kind == "card_prep_error":
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    "این کارت نتونست با اطمینان آماده بشه؛ لطفاً بعداً دوباره امتحان کن.",
                    reply_markup=main_menu(is_owner(user_id)),
                )
                return

            show_translations = True
            show_pronounce = bool(result.show_pronounce)
            context.user_data[f"query_kb_{result.token}"] = {
                "show_translations": show_translations,
                "show_pronounce": show_pronounce,
            }
            phon_lines = _phonetic_lines(result.card_data.get("phonetic", ""))
            delivered = False
            try:
                await _send_with_retry(
                    context.bot,
                    update.effective_chat.id,
                    format_card(
                        result.card_data,
                        footer=(
                            f"{result.usage_text}\n\n"
                            "برای افزودن این واژه به مرور، از دکمه‌ی زیر استفاده کن."
                        ),
                        presentation=_user_presentation(row),
                        phonetic_lines=phon_lines,
                    ),
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=query_result_keyboard(
                        result.token,
                        row["target_lang"] if row else "en",
                        show_translations=show_translations,
                        show_pronounce=show_pronounce,
                    ),
                )
                delivered = True
            finally:
                if not delivered:
                    db.release_word_query(user_id)
            log.info(
                "custom word query delivered user_id=%s lang=%s",
                user_id,
                row["target_lang"] if row else "en",
            )
            await _send_with_retry(
                context.bot,
                update.effective_chat.id,
                "به منوی اصلی برگشتی 🙂",
                reply_markup=main_menu(is_owner(user_id)),
            )
            return

        if is_admin_awaiting(awaiting):
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
    elif text == "راهنما":
        await send_help_panel(update, context)
    else:
        await _send_with_retry(context.bot, update.effective_chat.id, "از دکمه‌های پایین استفاده کن 🙂", reply_markup=main_menu(is_owner(user_id)))


# ---------------- روتر callback query ها ----------------

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _telegram_offline:
        await notify_callback(
            update.callback_query,
            _OFFLINE_MESSAGE,
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        await _send_offline_notice(context, update.effective_chat.id)
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
            "help:",
        )
    ):
        await notify_callback(update.callback_query)

    if data == "flow:back":
        await handle_flow_back(update, context)
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
            await notify_callback(update.callback_query, "فعلاً چیزی برای لغو نیست.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    if data.startswith("presentation:set:"):
        preference = data.split(":", 2)[2]
        if preference not in {"brief", "detailed"}:
            await notify_callback(update.callback_query, "انتخاب نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        user_id = update.effective_user.id
        row = db.get_user(user_id)
        if not row or not row["onboarded"]:
            await notify_callback(update.callback_query, "ابتدا /start را بزنید.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        if (row["plan"] or "free") not in PREMIUM_PLANS:
            await notify_callback(update.callback_query, "این تنظیم فقط برای کاربران پریمیوم فعال است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        db.set_presentation_preference(user_id, preference)
        label = "خلاصه" if preference == "brief" else "کامل"
        await _edit_with_retry(
            update.callback_query,
            f"نمایش کارت‌ها روی «{label}» تنظیم شد.",
            reply_markup=presentation_settings_keyboard(preference, back_to_settings=True),
        )
        await notify_callback(update.callback_query, "تنظیمات ذخیره شد.", intent=CallbackNoticeIntent.SUCCESS)
        return

    if data.startswith("lang:"):
        lang = data.split(":", 1)[1]
        if lang not in LANGUAGES:
            await notify_callback(update.callback_query, "زبان نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        row = db.get_user(update.effective_user.id)
        if row and row["onboarded"]:
            await on_lang_changed(update, context, lang)      # تغییر زبان
        else:
            await on_lang_selected(update, context, lang)     # onboarding
    elif data.startswith("goal:"):
        goal = data.split(":", 1)[1]
        if goal not in GOALS:
            await notify_callback(update.callback_query, "هدف نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        row = db.get_user(update.effective_user.id)
        if row and row["onboarded"]:
            await on_goal_changed(update, context, goal)      # تغییر هدف
        else:
            await on_goal_selected(update, context, goal)     # onboarding
    elif data.startswith("level:"):
        level = data.split(":", 1)[1]
        if level not in LEVELS:
            await notify_callback(update.callback_query, "سطح نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
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
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
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
            await notify_callback(update.callback_query, "بسته شد.", intent=CallbackNoticeIntent.INFO)
        except BadRequest:
            await notify_callback(update.callback_query)
    elif data.startswith("llm:"):
        await _handle_llm_callback(update, context, data)
    elif data.startswith("srs:fe:"):
        parts = data.split(":")
        if len(parts) != 5:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        await _handle_first_exposure_grade(update, context, parts[2], parts[3], parts[4])
    elif data.startswith("srs:"):
        parts = data.split(":")
        if len(parts) != 4:
            await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        try:
            grade = int(parts[1])
        except ValueError:
            log.warning("Unrecognized srs callback: %s", data)
            await notify_callback(update.callback_query, "این دکمه دیگر معتبر نیست.", intent=CallbackNoticeIntent.INFO)
            return
        if grade not in (1, 2, 3, 4):
            log.warning("Unrecognized srs callback: %s", data)
            await notify_callback(update.callback_query, "این دکمه دیگر معتبر نیست.", intent=CallbackNoticeIntent.INFO)
            return
        await _handle_srs_review(update, grade, parts[2], parts[3], context)
    elif data == "study:start":
        await handle_study_start(update, context)
    elif data == "study:inactive":
        await handle_study_inactive(update, context)
    elif data.startswith("tts:pronounce:"):
        await _handle_tts_pronounce(update, context, data.split(":", 2)[2])
    elif data.startswith("help:"):
        await handle_help_callback(update, context, data)
    elif data.startswith("admin:"):
        await _handle_admin_callback(update, context, data.split(":", 1)[1])
    else:
        log.warning("Unhandled callback data in recognized prefix: %s", data)
        await notify_callback(
            update.callback_query,
            "عملیات ناموفق بود.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )


async def _send_offline_notice(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if chat_id in _offline_notice_sent:
        return
    _offline_notice_sent.add(chat_id)
    try:
        await _send_with_retry(
            context.bot,
            chat_id,
            _OFFLINE_MESSAGE,
            reset_telegram_cb=False,
        )
    except Exception:
        log.debug("offline notification send failed (expected)")


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
                _offline_notice_sent.clear()
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
            _offline_notice_sent.clear()
            log.info("Telegram connection restored")
        else:
            log.info("Telegram connection healthy")


async def _handle_tts_pronounce(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split(":")
    if len(parts) < 2:
        await notify_callback(update.callback_query, "دکمه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    source = parts[0]
    if source not in {"q", "s"}:
        await notify_callback(update.callback_query, "دکمه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    user_id = update.effective_user.id
    row = db.get_user(user_id)
    if not row or not row["onboarded"]:
        await notify_callback(update.callback_query, "ابتدا /start را بزنید.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    tts_access = db.get_setting("tts_access", "premium")
    if tts_access == "none":
        await notify_callback(update.callback_query, "تلفظ غیرفعال است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if tts_access == "premium" and _user_plan(row) not in PREMIUM_PLANS:
        await notify_callback(update.callback_query, "این قابلیت فقط برای کاربران نقره‌ای و طلایی فعال است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    word = None
    lang = None

    if source == "q":
        if len(parts) != 2:
            await notify_callback(update.callback_query, "دکمه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        token = parts[1]
        qr = db.get_query_result(token, user_id=user_id)
        if not qr:
            await notify_callback(update.callback_query, "این نتیجه منقضی شده است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        word = qr["word"]
        lang = qr["lang"]

    elif source == "s":
        if len(parts) != 3:
            await notify_callback(update.callback_query, "دکمه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        try:
            target_user_id = int(parts[1])
            word_id = int(parts[2])
        except ValueError:
            await notify_callback(update.callback_query, "دکمه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        if user_id != target_user_id:
            await notify_callback(update.callback_query, "این مرور برای کاربر دیگری است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        sw = db.get_saved_word(word_id, user_id=user_id)
        if not sw:
            await notify_callback(update.callback_query, "واژه در مرور شما پیدا نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        word = sw["word"]
        lang = sw["lang"]

    else:
        await notify_callback(update.callback_query, "دکمه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    if not word or not lang:
        await notify_callback(update.callback_query, "واژه یا زبان نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    await notify_callback(update.callback_query, "🎧 در حال آماده‌سازی تلفظ…", intent=CallbackNoticeIntent.INFO)

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
    callback_query = getattr(update, "callback_query", None)
    if callback_query is not None:
        await notify_callback(
            callback_query,
            "خطا در پردازش درخواست. دوباره تلاش کنید.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )


def main():
    db.init_db()
    db_level = db.get_setting("log_level", "")
    if db_level:
        apply_log_level(db_level)
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN در .env تنظیم نشده.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", send_help_panel))
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
