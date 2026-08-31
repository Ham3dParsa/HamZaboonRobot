"""Admin user-management domain (issue #stats-users).

Owns the ``admin:user`` callback sub-tree and the three awaiting flows it needs
(``admin_user_search``, ``admin_user_set_plan:`` and ``admin_user_message:``).
All data access funnels through ``services.db.users`` (single source of truth);
keyboards live in ``config.keyboards.admin``. The owner gate is enforced by the
parent ``admin`` route in ``services.routing``.

Flows
-----
* ``admin_user_search`` — exact-key flow: the admin sends a user_id or
  ``@username``; we resolve via ``db.find_user`` and render the profile card.
* ``admin_user_set_plan:<user_id>`` — namespace flow: the admin sends only the
  plan name; the user id is carried in the awaiting key, reusing the single
  ``db.set_plan`` write seam.
* ``admin_user_message:<user_id>`` — namespace flow: direct message to user.
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from services import db
from services.send_pretty import RawFormat, say
from telegram.constants import ParseMode

from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.formatting import to_persian_digits
from services.utils.helpers import _edit_or_send, _send_with_retry
from config.catalog import goal_label, language_label, level_label
from config.keyboards import (
    admin_awaiting_inline_keyboard,
    dm_preview_keyboard,
    user_management_keyboard,
    user_profile_keyboard,
    user_reset_confirm_keyboard,
)
from handlers.flows import mark_awaiting_consumed, register_flow

logger = logging.getLogger(__name__)


def _profile_text_and_keyboard(user_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    """Build the profile card text + action keyboard, or None when no such user."""
    row = db.get_user(user_id)
    if not row:
        return None
    stats = db.get_user_learning_stats(user_id)
    blocked = bool(row["bot_blocked"])
    plan_label = (db.get_plan(row["plan"] or "free") or {}).get("display_name", row["plan"] or "free")
    lang = language_label(row["target_lang"]) if row["target_lang"] else "—"
    goal = goal_label(row["goal"]) if row["goal"] else "—"
    level = level_label(row["level"]) if row["level"] else "—"
    full_name = (dict(row).get("full_name") or "").strip()
    full_name_display = full_name if full_name else "—"
    username_display = f"@{row['username']}" if row["username"] else "—"
    last_active = to_persian_digits(row["last_active_date"]) if row["last_active_date"] else "—"
    created_at = to_persian_digits(row["created_at"]) if row["created_at"] else "—"
    text = (
        "👤 پروفایل کاربر\n\n"
        f"┌ نام کامل     │ {full_name_display}\n"
        f"├ شناسه       │ {to_persian_digits(row['user_id'])}\n"
        f"├ نام‌کاربری  │ {username_display}\n"
        f"├ پلن        │ {plan_label}\n"
        f"├ زبان/هدف/سطح │ {lang} / {goal} / {level}\n"
        f"├ استریک      │ {to_persian_digits(row['streak'] or 0)} 🔥\n"
        f"├ لغات/مرور/جلسات │ {to_persian_digits(stats['saved_words'])} / {to_persian_digits(stats['review_events'])} / {to_persian_digits(stats['study_sessions'])}\n"
        f"├ آخرین فعالیت │ {last_active}\n"
        f"└ ثبت‌نام     │ {created_at}\n"
        f"🚫 بلاک: {'بله' if blocked else 'خیر'}\n"
    )
    return text, user_profile_keyboard(user_id, blocked)


async def _show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    result = _profile_text_and_keyboard(user_id)
    if result is None:
        await notify_callback(
            update.callback_query, "کاربر پیدا نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR
        )
        return
    text, keyboard = result
    await _edit_or_send(update, context, text, reply_markup=keyboard)


async def _send_profile_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Send the profile card as a fresh message (used after text-input flows)."""
    result = _profile_text_and_keyboard(user_id)
    if result is None:
        await say(
            update, context, "کاربر پیدا نشد.", raw=RawFormat.PLAIN, mode="send",
        )
        return
    text, keyboard = result
    await say(
        update, context, text, raw=RawFormat.PLAIN, keyboard=keyboard, mode="send",
    )


async def handle_admin_user(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Route ``admin:user*`` sub-actions (action already strips the ``admin:`` prefix)."""
    if action == "user":
        await _edit_or_send(
            update, context,
            "👤 مدیریت کاربر\n\nیکی از گزینه‌ها را انتخاب کن:",
            reply_markup=user_management_keyboard(),
        )
        return
    if action == "user:search":
        context.user_data["awaiting"] = "admin_user_search"
        await notify_callback(update.callback_query)
        await _edit_or_send(
            update, context,
            "شناسه کاربر (عدد) یا نام‌کاربری (@username) را بفرستید:",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
        return
    if action.startswith("user:profile:"):
        await _show_profile(update, context, int(action.split(":", 2)[2]))
        return
    if action.startswith("user:plan:"):
        user_id = int(action.split(":", 2)[2])
        context.user_data["awaiting"] = f"admin_user_set_plan:{user_id}"
        await notify_callback(update.callback_query)
        await _edit_or_send(
            update, context,
            f"نام پلن را برای کاربر {user_id} بفرستید (مثال: silver):",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
        return
    if action.startswith("user:msg_confirm:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        pending = context.user_data.get("pending_dm")
        if not pending or int(pending.get("user_id", -1)) != user_id:
            await notify_callback(update.callback_query, "پیش‌نمایشی یافت نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        html = pending.get("html") or pending.get("text", "")
        text_val = pending.get("text", "")
        kwargs = {}
        if html and html != text_val:
            kwargs["parse_mode"] = ParseMode.HTML
            send_text = html
        else:
            send_text = text_val
        try:
            await _send_with_retry(context.bot, user_id, send_text, **kwargs)
        except Exception:
            logger.exception("admin message to user %s failed", user_id)
            await notify_callback(update.callback_query, "ارسال ناموفق بود.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            await _edit_or_send(update, context, "ارسال پیام ناموفق بود (کاربر یافت نشد یا ربات را بلاک کرده).")
            return
        context.user_data.pop("pending_dm", None)
        mark_awaiting_consumed(context)
        context.user_data.pop("awaiting", None)
        await notify_callback(update.callback_query, "ارسال شد.", intent=CallbackNoticeIntent.SUCCESS)
        await _edit_or_send(update, context, "پیام ارسال شد.")
        return
    if action.startswith("user:msg_cancel:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            user_id = None
        context.user_data.pop("pending_dm", None)
        mark_awaiting_consumed(context)
        context.user_data.pop("awaiting", None)
        await notify_callback(update.callback_query, "لغو شد.", intent=CallbackNoticeIntent.INFO)
        await _edit_or_send(update, context, "لغو شد.")
        return
    if action.startswith("user:msg_edit:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        context.user_data.pop("pending_dm", None)
        context.user_data["awaiting"] = f"admin_user_message:{user_id}"
        await notify_callback(update.callback_query)
        await _edit_or_send(
            update, context,
            f"متن پیام به کاربر {user_id} را دوباره بفرستید:",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
        return
    if action.startswith("user:msg:"):
        user_id = int(action.split(":", 2)[2])
        context.user_data["awaiting"] = f"admin_user_message:{user_id}"
        await notify_callback(update.callback_query)
        await _edit_or_send(
            update, context,
            f"متن پیام به کاربر {user_id} را بفرستید:",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
        return
    if action.startswith("user:block:"):
        user_id = int(action.split(":", 2)[2])
        db.set_user_blocked(user_id)
        await notify_callback(update.callback_query, "بلاک شد.", intent=CallbackNoticeIntent.SUCCESS)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:unblock:"):
        user_id = int(action.split(":", 2)[2])
        db.reset_user_blocked(user_id)
        await notify_callback(update.callback_query, "رفع بلاک شد.", intent=CallbackNoticeIntent.SUCCESS)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:reset:"):
        user_id = int(action.split(":", 2)[2])
        await _edit_or_send(
            update, context,
            "⚠️ ریست پیشرفت تمام لغات ذخیره‌شده، مرورها و جلسات این کاربر را حذف "
            "می‌کند. این کار غیرقابل‌بازگشت است. تایید می‌کنید؟",
            reply_markup=user_reset_confirm_keyboard(user_id),
        )
        return
    if action.startswith("user:reset_confirm:"):
        user_id = int(action.split(":", 2)[2])
        db.reset_user_progress(user_id)
        await notify_callback(update.callback_query, "پیشرفت ریست شد.", intent=CallbackNoticeIntent.SUCCESS)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:reset_cancel:"):
        user_id = int(action.split(":", 2)[2])
        await notify_callback(update.callback_query, "لغو شد.", intent=CallbackNoticeIntent.INFO)
        await _show_profile(update, context, user_id)
        return
    await notify_callback(update.callback_query, "دکمه‌ی نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)


# ---------------------------------------------------------------------------
# Awaiting flows (R2) — registered with the central registry at import time.
# ---------------------------------------------------------------------------


async def _handle_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str, text: str):
    row = db.find_user(text)
    if not row:
        context.user_data["awaiting"] = "admin_user_search"
        await say(
            update, context,
            "کاربر پیدا نشد. دوباره بفرستید یا لغو کنید.",
            raw=RawFormat.PLAIN, mode="send",
        )
        return
    mark_awaiting_consumed(context)  # profile resolved (B5/Kilo CRITICAL)
    await _send_profile_message(update, context, row["user_id"])


async def _handle_user_set_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str, text: str):
    user_id = int(awaiting.split(":", 1)[1])
    plan = text.strip().lower()
    if not db.valid_plan_name(plan):
        context.user_data["awaiting"] = awaiting
        await say(
            update, context,
            "نام پلن نامعتبر است (free، bronze، silver، gold، emerald).",
            raw=RawFormat.PLAIN, mode="send",
        )
        return
    db.set_plan(user_id, plan)
    mark_awaiting_consumed(context)  # plan write is irreversible (B5/Kilo CRITICAL)
    await say(
        update, context,
        f"پلن کاربر {user_id} به {plan} تغییر کرد.",
        raw=RawFormat.PLAIN, mode="send",
    )
    await _send_profile_message(update, context, user_id)


async def _handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str, text: str):
    user_id = int(awaiting.split(":", 1)[1])
    msg = text.strip()
    if not msg:
        context.user_data["awaiting"] = awaiting
        await say(
            update, context,
            "متن پیام خالی است. دوباره بفرستید یا لغو کنید.",
            raw=RawFormat.PLAIN, mode="send",
        )
        return
    # Capture HTML-preserving representation for format preservation (R3).
    html = None
    try:
        em = getattr(update, "effective_message", None) or getattr(update, "message", None)
        html = getattr(em, "text_html", None) if em is not None else None
    except Exception:
        html = None
    if not html:
        html = msg
    context.user_data["pending_dm"] = {"user_id": user_id, "text": msg, "html": html}
    # Awaiting is consumed for the text input; preview is callback-driven.
    mark_awaiting_consumed(context)
    preview = html
    # Render preview to admin with format preservation.
    use_html = bool(preview and preview != msg)
    preview_text = f"👁 پیش‌نمایش پیام به کاربر {user_id}:\n\n{preview}\n\nتایید می‌کنید؟"
    await say(
        update, context,
        preview_text,
        raw=RawFormat.HTML if use_html else RawFormat.PLAIN,
        keyboard=dm_preview_keyboard(user_id),
        mode="send",
    )


def _register_user_flows() -> None:
    """Register user-management awaiting flows with the central registry."""
    register_flow("admin_user_search", _handle_user_search)
    register_flow("admin_user_set_plan:", _handle_user_set_plan)
    register_flow("admin_user_message:", _handle_user_message)


_register_user_flows()
