"""Admin AI fallback/usage leaf (REF2-T4, fourth).

Verbatim home of fallback and usage handlers plus text-input routing.
"""

import logging
from urllib.parse import quote, unquote

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from services import db
from services.ai import preset_fields
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers import _clear_awaiting_prompt, _edit_or_send
from services.send_pretty import Backend, Message, RawFormat, bold, code, italic, plain, say
from config.keyboards import admin_awaiting_inline_keyboard, ai_fallback_keyboard, fallback_chain_keyboard

from handlers.admin_ai_wizard import MAX_GROUP_LABEL_LEN
from handlers.admin_ai_list import _detect_key_groups, _resolve_preset_ref, _show_grouped_presets, _show_group_manager
from handlers.admin_ai_create import _handle_create_priority_manual


USAGE_PAGE_SIZE = 5

async def _show_ai_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show fallback configuration panel."""
    status = db.get_fallback_status()
    if status["fallback_active"]:
        active = db.get_preset(str(status["fallback_preset"])) or {}
        if bool(preset_fields.resolve(active, "is_emergency")):
            status_label = "🎯 🛡️ Emergency ACTIVE"
        else:
            status_label = "🎯 Fallback ACTIVE"
    else:
        status_label = "🎯 Primary Active"
    msg = Message()
    msg.add_line(plain("🔄 "), bold("مدیریت پیش‌تنظیم پشتیبان (Fallback)"))
    msg.add_line()
    msg.add_line(plain("Status: "), plain(status_label))
    msg.add_line(plain("Primary: "), plain(str(status['primary_preset'])))
    msg.add_line(plain("Fallback: "), plain(str(status['fallback_preset'])))
    msg.add_line(plain("Consecutive Failures: "), plain(str(status['consecutive_failures'])))
    if status["fallback_active"] and status["fallback_since"]:
        msg.add_line(plain("Fallback Since: "), plain(str(status['fallback_since'][:19])))

    await say(update, context, msg, backend=Backend.HTML, keyboard=ai_fallback_keyboard(
        status["primary_preset"],
        status["fallback_preset"],
        status["fallback_preset"] if status["fallback_active"] else status["primary_preset"]
    ))

async def _handle_ai_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Handle fallback actions."""
    if action == "ai_fallback:set_primary":
        await _show_fallback_preset_picker(update, context, "primary")
    elif action == "ai_fallback:set_fallback":
        await _show_fallback_preset_picker(update, context, "fallback")
    elif action.startswith("ai_fallback:pick_primary:"):
        name = _resolve_preset_ref(action.split(":")[2])
        db.set_setting("ai_primary_preset", name)
        await notify_callback(update.callback_query, f"Primary preset: {name}", intent=CallbackNoticeIntent.SUCCESS)
        await _show_ai_fallback(update, context)
    elif action.startswith("ai_fallback:pick_fallback:"):
        name = _resolve_preset_ref(action.split(":")[2])
        db.set_setting("ai_fallback_preset", name)
        await notify_callback(update.callback_query, f"Fallback preset: {name}", intent=CallbackNoticeIntent.SUCCESS)
        await _show_ai_fallback(update, context)
    elif action == "ai_fallback:reset":
        db.set_fallback_active(False)
        db.set_setting("ai_consecutive_failures", "0")
        await notify_callback(update.callback_query, "بازگشت به Primary", intent=CallbackNoticeIntent.INFO)
        await _show_ai_fallback(update, context)

async def _show_fallback_preset_picker(update: Update, context: ContextTypes.DEFAULT_TYPE, which: str):
    """Show preset picker for primary/fallback."""
    from services.utils.callback_codec import preset_token
    presets = db.get_presets()
    buttons = [
        [InlineKeyboardButton(p["name"], callback_data=f"admin:ai_fallback:pick_{which}:{preset_token(p['name'])}")]
        for p in presets
    ]
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_fallback")])

    await _edit_or_send(
        update, context,
        f"پیش‌تنظیم {which.upper()} را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def _show_help_presets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help overview for presets."""
    msg = Message()
    msg.add_line(plain("❓ "), bold("راهنمای پریست‌های AI"))
    msg.add_line()
    msg.add_line(plain("هر پریست یک تنظیمات کامل برای اتصال به یک سرویس‌دهنده AI است."))
    msg.add_line()
    msg.add_line(bold("فیلدهای اصلی:"))
    msg.add_line(plain("• name: نام یکتای پریست (حروف انگلیسی، اعداد، زیرخط، نقطه، خط‌تیره؛ حداکثر ۶۰ کاراکتر)"))
    msg.add_line(plain("• api_key: کلید API (مقدار ثابت؛ به‌صورت رمزنگاری‌شده ذخیره می‌شود)"))
    msg.add_line(plain("• base_url: آدرس سرور (سازگار با OpenAI)"))
    msg.add_line(plain("• model: نام دقیق مدل"))
    msg.add_line()
    msg.add_line(bold("محدودیت‌ها:"))
    msg.add_line(plain("• max_concurrency: تعداد درخواست هم‌زمان"))
    msg.add_line(plain("• max_rpm: سقف درخواست در دقیقه (0 = بی‌محدودیت)"))
    msg.add_line(plain("• max_tpm: سقف توکن در دقیقه (0 = بی‌محدودیت)"))
    msg.add_line(plain("• max_daily_req: سقف درخواست روزانه (0 = بی‌محدودیت)"))
    msg.add_line()
    msg.add_line(bold("زنجیره فال‌بک:"))
    msg.add_line(plain("پریست‌ها بر اساس priority (کم→زیاد) و is_emergency مرتب می‌شوند."))
    msg.add_line(plain("پریست‌های عادی اول امتحان می‌شوند، سپس اضطراری."))
    msg.add_line(plain("in_fallback_chain=0 یعنی پریست در زنجیره شرکت نمی‌کند."))
    msg.add_line()
    msg.add_line(bold("گروه‌بندی:"))
    msg.add_line(plain("پریست‌هایی که کلید API مشترک دارند در یک گروه قرار می‌گیرند."))
    msg.add_line(plain("group_label برای نام‌گذاری گروه‌ها استفاده می‌شود."))
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")]
    ]))

async def _show_help_fallback_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help for fallback chain."""
    msg = Message()
    msg.add_line(plain("❓ "), bold("راهنمای زنجیره فال‌بک"))
    msg.add_line()
    msg.add_line(plain("ترتیب زنجیره:"))
    msg.add_line(plain("۱. پریست‌های عادی (is_emergency=0) بر اساس priority (از کم به زیاد)"))
    msg.add_line(plain("۲. پریست‌های اضطراری (is_emergency=1) بر اساس priority"))
    msg.add_line()
    msg.add_line(plain("پریست‌های با in_fallback_chain=0 در زنجیره نمایش داده نمی‌شوند."))
    msg.add_line()
    msg.add_line(bold("دکمه‌ها:"))
    msg.add_line(plain("• ⬆/⬇: جابه‌جایی دستی (تغییر priority)"))
    msg.add_line(plain("• 🟢/⚫: فعال/غیرفعال کردن پریست"))
    msg.add_line(plain("• 🛡️: تبدیل به پریست اضطراری"))
    msg.add_line(plain("• 🔢: پرش به رتبه دلخواه در گروه"))
    msg.add_line()
    msg.add_line(plain("پریست اضطراری همیشه بعد از همه پریست‌های عادی امتحان می‌شود."))
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ بازگشت به زنجیره", callback_data="admin:fallback_chain")]
    ]))

async def _show_fallback_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show and manage the fallback chain order."""
    chain = db.get_fallback_chain_presets()
    msg = Message()
    msg.add_line(plain("⛓️ "), bold("زنجیره فال‌بک"))
    msg.add_line()
    msg.add_line(
        plain("ترتیب: پریست‌های عادی (is_emergency=0) بر اساس priority (از کم به زیاد)، "),
        plain("سپس پریست‌های اضطراری (is_emergency=1)."),
    )
    msg.add_line(plain("پریست‌های با in_fallback_chain=0 در این زنجیره نمایش داده نمی‌شوند."))
    msg.add_line()
    for i, preset in enumerate(chain):
        name = preset.get("name", "?")
        is_emergency = preset_fields.resolve(preset, "is_emergency")
        status = "🛡️ اضطراری" if is_emergency else "🟢 فعال"
        msg.add_line(plain(f"{i+1}. "), bold(str(name)), plain(f" — {status}"))

    await say(update, context, msg, backend=Backend.HTML, keyboard=fallback_chain_keyboard(chain))

def _usage_rows() -> list[tuple[str, str, str]]:
    """Return (status_icon, name, detail) rows ordered by name."""
    rows = []
    for p in db.get_presets():
        name = p["name"]
        req_count, token_count = db.get_hourly_usage(name, hours_back=24)
        max_daily = preset_fields.resolve(p, "max_daily_req")
        status = "🔋" if req_count < max_daily or max_daily == 0 else "🪫"
        daily_str = f"{req_count}/{max_daily}" if max_daily > 0 else f"{req_count}/∞"
        rows.append((status, name, f"{daily_str} req, {token_count} توکن"))
    return rows

def _usage_page_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"admin:fallback:usage_page:{page - 1}:prev"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"admin:fallback:usage_page:{page + 1}:next"))
    rows = [buttons] if buttons else []
    rows.append([InlineKeyboardButton("↩️ بازگشت به زنجیره", callback_data="admin:fallback_chain")])
    return InlineKeyboardMarkup(rows)

def _render_usage_page(page: int) -> tuple[str, InlineKeyboardMarkup]:
    rows = _usage_rows()
    total = len(rows)
    total_pages = max(1, (total + USAGE_PAGE_SIZE - 1) // USAGE_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    if total == 0:
        return "هیچ داده‌ای یافت نشد.", _usage_page_keyboard(0, 1)
    start = page * USAGE_PAGE_SIZE
    slice_rows = rows[start:start + USAGE_PAGE_SIZE]
    msg = Message()
    msg.add_line(plain("📊 "), bold("مصرف ۲۴ ساعته پریست‌ها"), plain(f" (صفحه {page + 1}/{total_pages})"))
    msg.add_line()
    for status, name, detail in slice_rows:
        msg.add_line(plain(status), plain(" "), bold(str(name)), plain(": "), plain(detail))
    return msg.render(Backend.HTML), _usage_page_keyboard(page, total_pages)

async def _show_fallback_usage_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """R7: Show daily consumption for all presets, paginated."""
    text, keyboard = _render_usage_page(0)
    await say(update, context, text, raw=RawFormat.HTML, keyboard=keyboard)

async def _show_usage_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    """R7: show a specific usage page."""
    text, keyboard = _render_usage_page(page)
    await say(update, context, text, raw=RawFormat.HTML, keyboard=keyboard)

async def _handle_fallback_rank(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Start awaiting flow for rank jump input."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    group_is_emergency = bool(preset_fields.resolve(preset, "is_emergency"))
    group_label = "اضطراری" if group_is_emergency else "عادی"
    chain = db.get_fallback_chain_presets()
    group_chain = [p for p in chain if bool(preset_fields.resolve(p, "is_emergency")) == group_is_emergency]
    max_rank = len(group_chain)

    context.user_data["awaiting"] = f"ai_fallback_rank:{preset_name}"
    await _edit_or_send(
        update, context,
        f"🔢 رتبه جدید در گروه «{group_label}» را وارد کنید (۱ تا {max_rank}):",
        reply_markup=admin_awaiting_inline_keyboard(),
    )

async def _handle_ai_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    awaiting: str,
    text: str,
) -> None:
    """Route AI/preset text-input awaiting states to their handlers.

    Mirrors the inline blocks that previously lived in the admin monolith's
    text-input dispatch. Registered in handlers/flows.py (R2). Behavior and
    awaiting strings are unchanged.
    """
    from handlers.flows import mark_awaiting_consumed
    if awaiting.startswith("admin_group_batch_key:"):
        key_hash = awaiting.split(":", 1)[1]
        # Delete user message containing plaintext key
        try:
            await update.message.delete()
        except Exception as exc:
            logging.getLogger(__name__).debug("delete batch key msg failed: %s", exc)
        groups = _detect_key_groups()
        target = next((g for g in groups if g["key_hash"] == key_hash), None)
        if target:
            try:
                db.set_preset_api_key_batch(target["names"], text.strip())
            except db.MasterKeyRequiredError:
                context.user_data.pop("awaiting", None)
                await say(update, context, "برای ذخیره کلید API باید AI_MASTER_KEY در سرور پیکربندی شود.", raw=RawFormat.PLAIN, mode="send")
                return
        mark_awaiting_consumed(context)  # batch key write is irreversible (B5/Kilo CRITICAL)
        context.user_data.pop("awaiting", None)
        await say(update, context, "✅ کلید API برای همه اعضای گروه به‌روز شد.", raw=RawFormat.PLAIN, mode="send")
        await _show_grouped_presets(update, context)
        return

    if awaiting.startswith("admin_group_set_label:"):
        key_hash = awaiting.split(":", 1)[1]
        new_label = text.strip()
        if not new_label or len(new_label) > MAX_GROUP_LABEL_LEN:
            context.user_data["awaiting"] = awaiting
            await say(update, context, f"برچسب نامعتبر. برچسب باید بین ۱ تا {MAX_GROUP_LABEL_LEN} کاراکتر باشد.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
            return
        groups = _detect_key_groups()
        target = next((g for g in groups if g["key_hash"] == key_hash), None)
        if target:
            db.set_preset_group_label_batch(target["names"], new_label)
        mark_awaiting_consumed(context)  # group-label write is irreversible (B5/Kilo CRITICAL)
        context.user_data.pop("awaiting", None)
        await say(update, context, "✅ برچسب گروه برای همه اعضا تنظیم شد.", raw=RawFormat.PLAIN, mode="send")
        await _show_grouped_presets(update, context)
        return

    if awaiting.startswith("admin_group_manager_rename:"):
        old_label = unquote(awaiting.split(":", 1)[1])
        new_label = text.strip()
        if new_label:
            if len(new_label) > MAX_GROUP_LABEL_LEN:
                context.user_data["awaiting"] = awaiting
                await say(update, context, f"برچسب نامعتبر. برچسب باید حداکثر {MAX_GROUP_LABEL_LEN} کاراکتر باشد.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
                return
            db.rename_group_label(old_label, new_label)
            mark_awaiting_consumed(context)  # rename is irreversible (B5/Kilo CRITICAL)
            context.user_data.pop("awaiting", None)
            await say(update, context, f"✅ برچسب «{old_label}» به «{new_label}» تغییر نام یافت.", raw=RawFormat.PLAIN, mode="send")
        else:
            context.user_data.pop("awaiting", None)
            await say(update, context, "انصراف از تغییر نام.", raw=RawFormat.PLAIN, mode="send")
        await _show_group_manager(update, context)
        return

    if awaiting.startswith("ai_preset_create_priority:"):
        await _handle_create_priority_manual(update, context, text)
        return

    if awaiting.startswith("ai_fallback_rank:"):
        preset_name = awaiting.split(":", 1)[1]
        try:
            target_rank = int(text.strip())
        except ValueError:
            context.user_data["awaiting"] = awaiting
            await say(update, context, "لطفاً یک عدد معتبر وارد کنید.", raw=RawFormat.PLAIN, mode="send")
            return
        preset = db.get_preset(preset_name)
        if not preset:
            await say(update, context, "پیش‌تنظیم یافت نشد", raw=RawFormat.PLAIN, mode="send")
            return
        group_is_emergency = bool(preset_fields.resolve(preset, "is_emergency"))
        chain = db.get_fallback_chain_presets()
        count = len(chain)
        try:
            db.reindex_preset_priority(preset_name, target_rank, group_is_emergency)
        except ValueError as e:
            await say(update, context, str(e), raw=RawFormat.PLAIN, mode="send")
            return
        mark_awaiting_consumed(context)  # priority reindex succeeded (B5/Kilo CRITICAL)
        context.user_data.pop("awaiting", None)
        await say(update, context, f"✅ رتبه {preset_name} به {target_rank} تغییر یافت.", raw=RawFormat.PLAIN, mode="send")
        await _show_fallback_chain(update, context)
        return

