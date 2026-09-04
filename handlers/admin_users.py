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
from services.send_pretty import Backend, Message, RawFormat, bold, plain, say, table
from telegram.constants import ParseMode

from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.formatting import html_escape, to_jalali_str, to_persian_digits
from services.utils.helpers import _clear_awaiting_prompt, _edit_or_send, _send_with_retry, _store_awaiting_msg, clear_admin_pending_state
from config import is_owner
from config.catalog import goal_label, language_label, level_label
from config.keyboards import (
    admin_awaiting_inline_keyboard,
    dm_preview_keyboard,
    user_block_confirm_keyboard,
    user_management_keyboard,
    user_plan_confirm_keyboard,
    user_plan_picker_keyboard,
    user_profile_keyboard,
    user_reset_confirm_keyboard,
)
from handlers.flows import mark_awaiting_consumed, register_flow

logger = logging.getLogger(__name__)


def _build_profile_message(row, stats, blocked: bool) -> Message:
    """Build a RichMessage table for the user profile (RTL, no box-drawing).

    Q5: 9-row compact table (was 14). Combines language/goal/level into one row,
    merges word stats into a detailed ``لغات`` row and activity into ``آمار``.
    Dates are rendered via ``to_jalali_str`` (Persian digits, Jalali calendar).
    """
    def _sanitize(v: str) -> str:
        return v.replace("\n", " ").replace("\r", " ")

    full_name = _sanitize((dict(row).get("full_name") or "").strip().replace("\n", " ")[:50] or "—")
    username = _sanitize(f"@{row['username']}" if row["username"] else "—")
    plan_label = _sanitize((db.get_plan(row["plan"] or "free") or {}).get("display_name", row["plan"] or "free"))
    lang = _sanitize(language_label(row["target_lang"]) if row["target_lang"] else "—")
    goal = _sanitize(goal_label(row["goal"]) if row["goal"] else "—")
    level = _sanitize(level_label(row["level"]) if row["level"] else "—")
    combo_lang_goal_level = _sanitize(f"{lang} / {goal} / {level}")
    # Q6 detailed word breakdown (stats now carries learned/not_exposed/due)
    total = stats.get("total", stats.get("saved_words", 0)) or 0
    learned = stats.get("learned", 0) or 0
    not_exposed = stats.get("not_exposed", 0) or 0
    due = stats.get("due", 0) or 0
    lughat_val = _sanitize(
        f"{to_persian_digits(total)} (آموخته {to_persian_digits(learned)} | "
        f"ناآشنا {to_persian_digits(not_exposed)} | سررسید {to_persian_digits(due)})"
    )
    review = stats.get("review_events", 0) or 0
    sessions = stats.get("study_sessions", stats.get("session_reports", 0)) or 0
    streak_val = row["streak"] or 0
    amar_val = _sanitize(
        f"{to_persian_digits(review)} مرور | {to_persian_digits(sessions)} جلسه | "
        f"استریک {to_persian_digits(streak_val)} 🔥"
    )
    # Jalali dates (Q2) — to_jalali_str already returns Persian digits
    raw_last = (row["last_active_date"] or "").strip() if isinstance(row["last_active_date"], str) else (row["last_active_date"] or "")
    raw_created = (row["created_at"] or "").strip() if isinstance(row["created_at"], str) else (row["created_at"] or "")
    last_active = _sanitize(to_jalali_str(raw_last) if raw_last else "—")
    created_at = _sanitize(to_jalali_str(raw_created) if raw_created else "—")
    # Block status folded into plan row suffix to keep 9 rows (keyboard already shows block toggle)
    plan_with_block = _sanitize(f"{plan_label} {'(مسدود)' if blocked else ''}".strip())
    msg = Message()
    msg.add_line(bold("👤 پروفایل کاربر"))
    hdr = (bold("فیلد"), bold("مقدار"))
    rows = [
        (plain("نام کامل"), plain(full_name)),
        (plain("شناسه"), plain(to_persian_digits(row["user_id"]))),
        (plain("نام کاربری"), plain(username)),
        (plain("پلن"), plain(plan_with_block)),
        (plain("زبان / هدف / سطح"), plain(combo_lang_goal_level)),
        (plain("لغات"), plain(lughat_val)),
        (plain("آمار"), plain(amar_val)),
        (plain("آخرین فعالیت"), plain(last_active)),
        (plain("ثبت‌نام"), plain(created_at)),
    ]
    msg.add_line(table(hdr, *rows))
    return msg


def _profile_text_and_keyboard(user_id: int) -> tuple[Message, InlineKeyboardMarkup] | None:
    """Build the profile RichMessage + action keyboard, or None when no such user."""
    row = db.get_user(user_id)
    if not row:
        return None
    stats = db.get_user_learning_stats(user_id)
    blocked = bool(row["bot_blocked"])
    msg = _build_profile_message(row, stats, blocked)
    keyboard = user_profile_keyboard(user_id, blocked)
    return msg, keyboard


async def _show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    result = _profile_text_and_keyboard(user_id)
    if result is None:
        await notify_callback(
            update.callback_query, "کاربر پیدا نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR
        )
        return
    try:
        context.user_data["admin_last_user_id"] = int(user_id)
    except Exception:
        pass
    msg, keyboard = result
    # RichMessage handles RTL + table natively via telegram_rich
    await say(update, context, msg, backend=Backend.RICH, is_rtl=True, keyboard=keyboard)


async def _send_profile_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Send the profile card as a fresh message (used after text-input flows)."""
    result = _profile_text_and_keyboard(user_id)
    if result is None:
        await say(
            update, context, "کاربر پیدا نشد.", raw=RawFormat.PLAIN, mode="send",
        )
        return
    try:
        context.user_data["admin_last_user_id"] = int(user_id)
    except Exception:
        pass
    msg, keyboard = result
    await say(
        update, context, msg, backend=Backend.RICH, is_rtl=True, keyboard=keyboard, mode="send",
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
        msg = await _edit_or_send(
            update, context,
            "شناسه کاربر (عدد) یا نام‌کاربری (@username) را بفرستید:",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
        _store_awaiting_msg(context, update, msg)
        return
    if action.startswith("user:profile:"):
        await _show_profile(update, context, int(action.split(":", 2)[2]))
        return
    if action.startswith("user:plan_confirm:"):
        # Q4 plan double-confirm: format user:plan_confirm:<id>:<plan>
        parts = action.split(":")
        try:
            user_id = int(parts[2]) if len(parts) > 2 else 0
            new_plan = parts[3].strip().lower() if len(parts) > 3 else ""
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        if not db.valid_plan_name(new_plan):
            await notify_callback(update.callback_query, "نام پلن نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        pending = context.user_data.get("pending_plan")
        if not pending or int(pending.get("user_id", -1)) != user_id or pending.get("new_plan") != new_plan:
            await notify_callback(update.callback_query, "پیش‌نمایشی یافت نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        context.user_data.pop("pending_plan", None)
        mark_awaiting_consumed(context)
        context.user_data.pop("awaiting", None)
        db.set_plan(user_id, new_plan)
        await notify_callback(update.callback_query, "پلن تغییر کرد.", intent=CallbackNoticeIntent.SUCCESS)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:plan_cancel:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        context.user_data.pop("pending_plan", None)
        mark_awaiting_consumed(context)
        context.user_data.pop("awaiting", None)
        await notify_callback(update.callback_query, "لغو شد.", intent=CallbackNoticeIntent.INFO)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:plan_select:"):
        parts = action.split(":")
        try:
            user_id = int(parts[2]) if len(parts) > 2 else 0
            new_plan = parts[3].strip().lower() if len(parts) > 3 else ""
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        if user_id <= 0:
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        if not db.valid_plan_name(new_plan):
            await notify_callback(update.callback_query, "نام پلن نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        row = db.get_user(user_id)
        if row is None:
            await notify_callback(update.callback_query, "کاربر پیدا نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        old_plan = row["plan"] or "free"
        context.user_data["pending_plan"] = {"user_id": user_id, "new_plan": new_plan, "old_plan": old_plan}
        # Clear any pending text-input awaiting; picker flow is callback-driven
        context.user_data.pop("awaiting", None)
        mark_awaiting_consumed(context)
        await _clear_awaiting_prompt(context)
        await notify_callback(update.callback_query)
        await _edit_or_send(
            update, context,
            f"پلن کاربر {user_id} از {old_plan} به {new_plan} تغییر کند؟",
            reply_markup=user_plan_confirm_keyboard(user_id, new_plan),
        )
        return
    if action.startswith("user:plan:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        if user_id <= 0:
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        # Primary UX: real plan picker — handler owns DB access (config/ is static)
        try:
            plans = db.list_plans()
        except Exception:
            logger.exception("user:plan list_plans failed for user %s", user_id)
            await notify_callback(update.callback_query, "خطا در دریافت پلن‌ها", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            await _edit_or_send(update, context, "خطا در دریافت پلن‌ها")
            return
        await notify_callback(update.callback_query)
        await _edit_or_send(
            update, context,
            f"پلن جدید را برای کاربر {user_id} انتخاب کنید:",
            reply_markup=user_plan_picker_keyboard(user_id, plans),
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
            context.user_data.pop("pending_dm", None)
            mark_awaiting_consumed(context)
            context.user_data.pop("awaiting", None)
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
        if user_id is None:
            try:
                _last = context.user_data.get("admin_last_user_id")
                user_id = int(_last) if _last is not None else None
            except Exception:
                user_id = None
        clear_admin_pending_state(context)
        await _clear_awaiting_prompt(context)
        await notify_callback(update.callback_query, "لغو شد.", intent=CallbackNoticeIntent.INFO)
        if user_id is not None:
            await _show_profile(update, context, user_id)
        else:
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
        msg = await _edit_or_send(
            update, context,
            f"متن پیام به کاربر {user_id} را دوباره بفرستید:",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
        _store_awaiting_msg(context, update, msg)
        return
    if action.startswith("user:msg:"):
        user_id = int(action.split(":", 2)[2])
        context.user_data["awaiting"] = f"admin_user_message:{user_id}"
        await notify_callback(update.callback_query)
        msg = await _edit_or_send(
            update, context,
            f"متن پیام به کاربر {user_id} را بفرستید:",
            reply_markup=admin_awaiting_inline_keyboard(),
        )
        _store_awaiting_msg(context, update, msg)
        return
    if action.startswith("user:block_confirm:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        pending = context.user_data.get("pending_block")
        if not pending or int(pending.get("user_id", -1)) != user_id:
            await notify_callback(update.callback_query, "پیش‌نمایشی یافت نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        context.user_data.pop("pending_block", None)
        mark_awaiting_consumed(context)
        context.user_data.pop("awaiting", None)
        db.set_user_blocked(user_id)
        await notify_callback(update.callback_query, "بلاک شد.", intent=CallbackNoticeIntent.SUCCESS)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:block_cancel:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        context.user_data.pop("pending_block", None)
        mark_awaiting_consumed(context)
        context.user_data.pop("awaiting", None)
        await notify_callback(update.callback_query, "لغو شد.", intent=CallbackNoticeIntent.INFO)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:block:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        # Q3 self-block guard: owner blocking themselves requires double confirm
        if is_owner(user_id):
            row = db.get_user(user_id)
            blocked = bool(row["bot_blocked"]) if row else False
            if not blocked:
                context.user_data["pending_block"] = {"user_id": user_id}
                await _edit_or_send(
                    update, context,
                    "⚠️ هشدار: در حال مسدود کردن خودتان (مالک ربات) هستید! آیا مطمئن هستید؟",
                    reply_markup=user_block_confirm_keyboard(user_id),
                )
                return
        db.set_user_blocked(user_id)
        await notify_callback(update.callback_query, "بلاک شد.", intent=CallbackNoticeIntent.SUCCESS)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:unblock:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        db.reset_user_blocked(user_id)
        await notify_callback(update.callback_query, "رفع بلاک شد.", intent=CallbackNoticeIntent.SUCCESS)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:reset:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        await _edit_or_send(
            update, context,
            "⚠️ ریست پیشرفت تمام لغات ذخیره‌شده، مرورها و جلسات این کاربر را حذف "
            "می‌کند. این کار غیرقابل‌بازگشت است. تایید می‌کنید؟",
            reply_markup=user_reset_confirm_keyboard(user_id),
        )
        return
    if action.startswith("user:reset_confirm:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
        db.reset_user_progress(user_id)
        await notify_callback(update.callback_query, "پیشرفت ریست شد.", intent=CallbackNoticeIntent.SUCCESS)
        await _show_profile(update, context, user_id)
        return
    if action.startswith("user:reset_cancel:"):
        try:
            user_id = int(action.split(":", 2)[2])
        except (IndexError, ValueError):
            await notify_callback(update.callback_query, "شناسه نامعتبر است.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            return
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
        await _clear_awaiting_prompt(context)
        context.user_data["awaiting"] = "admin_user_search"
        msg = await say(
            update, context,
            "کاربر پیدا نشد. دوباره بفرستید یا لغو کنید.",
            raw=RawFormat.PLAIN, mode="send",
        )
        _store_awaiting_msg(context, update, msg)
        return
    mark_awaiting_consumed(context)  # profile resolved (B5/Kilo CRITICAL)
    await _clear_awaiting_prompt(context)
    await _send_profile_message(update, context, row["user_id"])


async def _handle_user_set_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str, text: str):
    user_id = int(awaiting.split(":", 1)[1])
    plan = text.strip().lower()
    if not db.valid_plan_name(plan):
        await _clear_awaiting_prompt(context)
        context.user_data["awaiting"] = awaiting
        msg = await say(
            update, context,
            "نام پلن نامعتبر است (free، bronze، silver، gold، emerald).",
            raw=RawFormat.PLAIN, mode="send",
        )
        _store_awaiting_msg(context, update, msg)
        return
    # Q4 double-confirm: no DB write before confirm — show preview instead
    row = db.get_user(user_id)
    old_plan = (row["plan"] or "free") if row else "free"
    context.user_data["pending_plan"] = {"user_id": user_id, "new_plan": plan, "old_plan": old_plan}
    mark_awaiting_consumed(context)
    await _clear_awaiting_prompt(context)
    await say(
        update, context,
        f"پلن کاربر {user_id} از {old_plan} به {plan} تغییر کند؟",
        raw=RawFormat.PLAIN,
        keyboard=user_plan_confirm_keyboard(user_id, plan),
        mode="send",
    )


async def _handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str, text: str):
    user_id = int(awaiting.split(":", 1)[1])
    msg = text.strip()
    if not msg:
        await _clear_awaiting_prompt(context)
        context.user_data["awaiting"] = awaiting
        m = await say(
            update, context,
            "متن پیام خالی است. دوباره بفرستید یا لغو کنید.",
            raw=RawFormat.PLAIN, mode="send",
        )
        _store_awaiting_msg(context, update, m)
        return
    if len(msg) > 4000:
        await _clear_awaiting_prompt(context)
        context.user_data["awaiting"] = awaiting
        m = await say(update, context, "متن طولانی است (حداکثر ۴۰۰۰ کاراکتر). لطفاً کوتاه‌تر بفرستید.", raw=RawFormat.PLAIN, mode="send")
        _store_awaiting_msg(context, update, m)
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
    await _clear_awaiting_prompt(context)
    preview = html
    # Render preview to admin with format preservation.
    use_html = bool(preview and preview != msg)
    preview_text = f"{html_escape('👁 پیش‌نمایش پیام به کاربر ')}{html_escape(str(user_id))}{html_escape(':')}\n\n{preview}\n\n{html_escape('تایید می‌کنید؟')}"
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
