"""Admin AI create leaf (REF2-T4, third).

Verbatim home of preset creation flow.
"""

import asyncio
import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from services import db
from services.ai import ai
from services.ai import preset_fields
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers import _clear_awaiting_prompt, _edit_or_send, _rotate_awaiting_msg
from services.send_pretty import Backend, Message, RawFormat, bold, code, italic, plain, say
from config.keyboards import admin_awaiting_inline_keyboard

from handlers.admin_ai_list import _show_ai_presets
from handlers.admin_ai_wizard import MAX_GROUP_LABEL_LEN


async def _add_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a new custom preset - start with name input."""
    context.user_data["awaiting"] = "admin_ai_preset_new_name"
    msg = Message()
    msg.add_line(plain("➕ "), bold("ایجاد پیش‌تنظیم جدید"))
    msg.add_line()
    msg.add_line(plain("نام پیش‌تنظیم را وارد کنید (مثال: my_openai):"))
    msg.add_line()
    msg.add_line(plain("💡 "), plain(preset_fields.PRESET_NAME_HINT_FA))
    sent = await say(update, context, msg, backend=Backend.HTML, keyboard=admin_awaiting_inline_keyboard())
    await _rotate_awaiting_msg(context, update, sent)

async def _handle_ai_preset_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle new preset name input."""
    name = preset_fields.validate_preset_name(text)
    if name is None:
        context.user_data["awaiting"] = "ai_preset_new_name"
        sent = await say(update, context, preset_fields.PRESET_NAME_ERROR_FA, raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
        await _rotate_awaiting_msg(context, update, sent)
        return

    existing = db.get_preset(name)
    if existing:
        context.user_data["awaiting"] = "ai_preset_new_name"
        sent = await say(update, context, "این نام از قبل وجود دارد.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
        await _rotate_awaiting_msg(context, update, sent)
        return

    # Begin the create flow: remember the pending name, then ask for priority.
    context.user_data["preset_create"] = {"name": name}
    context.user_data.pop("awaiting", None)
    await _show_create_priority(update, context)

async def _show_create_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for the new preset's fallback-chain priority (R14)."""
    state = context.user_data.setdefault("preset_create", {})
    name = state.get("name", "")
    buttons = [
        [
            InlineKeyboardButton("🔝 بالا (مقدم)", callback_data="admin:ai_preset:create:priority:top"),
        ],
        [
            InlineKeyboardButton("🔢 عدد دستی", callback_data="admin:ai_preset:create:priority:manual"),
            InlineKeyboardButton("⬇️ پایین (کم‌اولویت)", callback_data="admin:ai_preset:create:priority:bottom"),
        ],
        [InlineKeyboardButton("❌ لغو", callback_data="admin:ai_settings")],
    ]
    msg = Message()
    msg.add_line(plain("➕ "), bold("ایجاد پیش‌تنظیم جدید"), plain(" — "), code(str(name)))
    msg.add_line()
    msg.add_line(plain("🔢 "), bold("اولویت در زنجیره فال‌بک"))
    msg.add_line()
    msg.add_line(plain("جایگاه پیش‌تنظیم جدید در زنجیره فال‌بک را انتخاب کنید:"))
    msg.add_line(plain("• "), bold("بالا (مقدم)"), plain(" — اولین نفری که امتحان می‌شود"))
    msg.add_line(plain("• "), bold("پایین (کم‌اولویت)"), plain(" — آخرین نفری که امتحان می‌شود"))
    msg.add_line(plain("• "), bold("دستی"), plain(" — عدد اولویت دلخواه وارد کنید"))
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))

async def _show_create_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for enabled status (R14). Test is offered only after fields are complete."""
    state = context.user_data.setdefault("preset_create", {})
    name = state.get("name", "")
    buttons = [
        [
            InlineKeyboardButton("🟢 فعال", callback_data="admin:ai_preset:create:status:on"),
            InlineKeyboardButton("⚫ غیرفعال", callback_data="admin:ai_preset:create:status:off"),
        ],
        [InlineKeyboardButton("❌ لغو", callback_data="admin:ai_settings")],
    ]
    msg = Message()
    msg.add_line(plain("⚙️ "), bold("وضعیت پیش‌تنظیم"), plain(" — "), code(str(name)))
    msg.add_line()
    msg.add_line(
        plain("پیش‌تنظیم جدید به‌صورت "), bold("غیرفعال"),
        plain(" ساخته می‌شود و تا وقتی آگاهانه فعالش نکنید، "
              "هیچ درخواستی را سرو نمی‌کند. وضعیت را انتخاب کنید:"),
    )
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))

async def _finish_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Persist the new preset and show the create summary (R14)."""
    state = context.user_data.setdefault("preset_create", {})
    name = state.get("name", "")
    if not name:
        # Guard against a lost/stale create state (e.g. tapping a stale summary
        # or toggle button without having entered a name) creating a preset with
        # an empty primary key.
        await notify_callback(update.callback_query, "جلسه ساخت پیش‌تنظیم منقضی شده", intent=CallbackNoticeIntent.INFO)
        context.user_data.pop("preset_create", None)
        context.user_data.pop("awaiting", None)
        await _show_ai_presets(update, context)
        return
    enabled = state.get("enabled", 0)
    rank = state.get("rank", _normal_chain_count())
    max_rank = _normal_chain_count()
    if rank < 0:
        rank = 0
    elif rank > max_rank:
        rank = max_rank
    db.set_preset(name=name, enabled=int(enabled))
    try:
        db.insert_preset_at_rank(name, int(rank))
    except ValueError:
        rank = max_rank
        db.insert_preset_at_rank(name, int(rank))
    context.user_data.pop("awaiting", None)
    preset = db.get_preset(name)
    status = "🟢 فعال" if preset.get("enabled", 0) else "⚫ غیرفعال"
    has_connection = bool(
        preset.get("base_url") and preset.get("model") and db.resolve_preset_key(preset)
    )
    buttons: list[list[InlineKeyboardButton]] = []
    if has_connection:
        buttons.append(
            [
                InlineKeyboardButton("🔁 تست اتصال", callback_data="admin:ai_preset:create:test"),
                InlineKeyboardButton("🔄 تغییر وضعیت", callback_data="admin:ai_preset:create:toggle_enable"),
            ]
        )
    else:
        buttons.append(
            [InlineKeyboardButton("🔄 تغییر وضعیت", callback_data="admin:ai_preset:create:toggle_enable")]
        )
    buttons.extend(
        [
            [InlineKeyboardButton("✏️ ادامه ویرایش کامل", callback_data=f"admin:ai_preset:full_edit:{_preset_ref(name)}")],
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_presets")],
        ]
    )
    msg = Message()
    msg.add_line(plain("✅ "), bold("پیش‌تنظیم ساخته شد"), plain(" — "), code(str(name)))
    msg.add_line()
    msg.add_line(plain("• وضعیت: "), plain(status))
    msg.add_line(plain("• اولویت زنجیره: "), code(str(preset.get('priority', 0))))
    msg.add_line(plain("• سفارشی: بله"))
    msg.add_line()
    msg.add_line(plain("می‌توانید اتصال را تست کنید، وضعیت را تغییر دهید، یا مستقیم وارد ویرایش کامل شوید."))
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))

def _normal_chain_count() -> int:
    """Number of enabled normal (non-emergency) in-fallback presets (R14)."""
    return sum(1 for p in db.get_fallback_chain_presets() if not p.get("is_emergency"))

async def _handle_create_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lightweight ping test of the pending (or just-created) preset (R14)."""
    state = context.user_data.get("preset_create", {})
    name = state.get("name", "")
    preset = db.get_preset(name)
    # Fail-closed guard: all three connection fields must be present and resolvable.
    resolved_key = db.resolve_preset_key(preset) if preset else ""
    if not (preset and preset.get("base_url") and preset.get("model") and resolved_key):
        msg = Message()
        msg.add_line(plain("⚠️ "), bold("تست اتصال برای پیش‌تنظیم تازه"))
        msg.add_line()
        msg.add_line(
            plain("این پیش‌تنظیم هنوز base_url / model / api_key ندارد، پس اتصال واقعی "
                  "امکان‌پذیر نیست. ابتدا فیلدها را در ویرایش کامل پر کنید، سپس تست بگیرید.")
        )
        msg.add_line(plain("این صرفاً یک یادآوری است و مشکلی در ساخت پیش‌تنظیم نیست."))
        buttons = [
            [InlineKeyboardButton("🔄 تغییر وضعیت", callback_data="admin:ai_preset:create:toggle_enable")],
            [InlineKeyboardButton("✏️ ادامه ویرایش کامل", callback_data=f"admin:ai_preset:full_edit:{_preset_ref(name)}")],
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_presets")],
        ]
        await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))
        return
    await notify_callback(update.callback_query, "در حال تست اتصال...", intent=CallbackNoticeIntent.INFO)
    msg = Message()
    result = await asyncio.to_thread(
        ai.test_connection,
        preset.get("base_url", ""),
        resolved_key,
        preset.get("model", ""),
        preset_fields.resolve(preset, "timeout_seconds"),
        preset_fields.resolve(preset, "reasoning_effort"),
    )
    if result["success"]:
        msg.add_line(plain("✅ "), bold("اتصال موفق"))
        msg.add_line(plain("تأخیر: "), plain(str(result['latency_ms'])), plain(" ms"))
    else:
        msg.add_line(plain("❌ "), bold("خطا در اتصال"))
        msg.add_line(plain("خطا: "), plain(str(result.get('error_class', ''))), plain(": "), plain(str(result.get('error_message', ''))))
    buttons = [
        [
            InlineKeyboardButton("🔄 تغییر وضعیت", callback_data="admin:ai_preset:create:toggle_enable"),
        ],
        [
            InlineKeyboardButton("✏️ ادامه ویرایش کامل", callback_data=f"admin:ai_preset:full_edit:{_preset_ref(name)}"),
        ],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_presets")],
    ]
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))

async def _handle_create_toggle_enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Flip the just-created preset's enabled state from the summary (R14)."""
    state = context.user_data.setdefault("preset_create", {})
    name = state.get("name", "")
    preset = db.get_preset(name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    new_enabled = not preset.get("enabled", 0)
    try:
        db.set_preset_enabled(name, new_enabled)
    except ValueError:
        await notify_callback(
            update.callback_query,
            "نمی‌توان آخرین پیش‌تنظیم فعال را غیرفعال کرد.",
            intent=CallbackNoticeIntent.IMPORTANT_ERROR,
        )
        return
    state["enabled"] = int(new_enabled)
    await _finish_create(update, context)

async def _test_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Test connection for any existing preset (detail view)."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    resolved_key = db.resolve_preset_key(preset)
    from services.utils.callback_codec import preset_token

    preset_ref = preset_token(preset_name)
    if not (preset.get("base_url") and preset.get("model") and resolved_key):
        msg = Message()
        msg.add_line(plain("⚠️ "), bold("اتصال ممکن نیست"))
        msg.add_line(plain("base_url / model / api_key کامل نیست. اول در ویرایش کامل پر کنید."))
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✏️ ادامه ویرایش کامل", callback_data=f"admin:ai_preset:full_edit:{preset_ref}")],
                [InlineKeyboardButton("↩️ بازگشت", callback_data=f"admin:ai_preset:view:{preset_ref}")],
            ]
        )
        await say(update, context, msg, backend=Backend.HTML, keyboard=keyboard)
        return
    await notify_callback(update.callback_query, "در حال تست اتصال...", intent=CallbackNoticeIntent.INFO)
    result = await asyncio.to_thread(
        ai.test_connection,
        preset.get("base_url", ""),
        resolved_key,
        preset.get("model", ""),
        preset_fields.resolve(preset, "timeout_seconds"),
        preset_fields.resolve(preset, "reasoning_effort"),
    )
    msg = Message()
    if result["success"]:
        msg.add_line(plain("✅ "), bold("اتصال موفق"))
        msg.add_line(plain("تأخیر: "), plain(str(result["latency_ms"])), plain(" ms"))
    else:
        msg.add_line(plain("❌ "), bold("خطا در اتصال"))
        msg.add_line(plain("خطا: "), plain(str(result.get("error_class", ''))), plain(": "), plain(str(result.get("error_message", ""))))
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔁 تست مجدد", callback_data=f"admin:ai_preset:test:{preset_ref}")],
            [InlineKeyboardButton("↩️ بازگشت", callback_data=f"admin:ai_preset:view:{preset_ref}")],
        ]
    )
    await say(update, context, msg, backend=Backend.HTML, keyboard=keyboard)

async def _handle_create_priority_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE, choice: str
):
    """Apply the priority choice, then move to the status prompt (R14)."""
    state = context.user_data.setdefault("preset_create", {})
    if choice == "top":
        state["rank"] = 0
        await _show_create_status(update, context)
    elif choice == "bottom":
        state["rank"] = _normal_chain_count()
        await _show_create_status(update, context)
    elif choice == "manual":
        context.user_data["awaiting"] = f"ai_preset_create_priority:{state.get('name', '')}"
        msg = Message()
        msg.add_line(plain("🔢 "), bold("عدد اولویت دستی"), plain(" را وارد کنید (عدد کمتر = اولویت بیشتر):"))
        await say(update, context, msg, backend=Backend.HTML, keyboard=admin_awaiting_inline_keyboard())
    else:
        await notify_callback(update.callback_query, "انتخاب نامعتبر", intent=CallbackNoticeIntent.IMPORTANT_ERROR)

async def _handle_create_priority_manual(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Apply a manually-entered priority number (R14)."""
    state = context.user_data.setdefault("preset_create", {})
    try:
        rank = int(text.strip())
    except ValueError:
        context.user_data["awaiting"] = f"ai_preset_create_priority:{state.get('name', '')}"
        await say(update, context, "لطفاً یک عدد معتبر وارد کنید.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
        return
    max_rank = _normal_chain_count()
    if rank < 0:
        context.user_data["awaiting"] = f"ai_preset_create_priority:{state.get('name', '')}"
        await say(update, context, "عدد اولویت نمی‌تواند منفی باشد.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
        return
    if rank > max_rank:
        # Clamp to the lowest slot so a value beyond the current chain size is
        # simply appended last instead of causing a broken ValueError mid-flow.
        rank = max_rank
        await say(update, context, f"عدد واردشده از جایگاه‌های قابل استفاده بیشتر بود؛ پیش‌تنظیم در آخرین جایگاه (رتبه {max_rank}) قرار می‌گیرد.", raw=RawFormat.PLAIN, mode="send")
    state["rank"] = rank
    context.user_data.pop("awaiting", None)
    await _show_create_status(update, context)

async def _handle_create_status_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE, choice: str
):
    """Record the enabled status then persist and show the summary (R14)."""
    state = context.user_data.setdefault("preset_create", {})
    state["enabled"] = 1 if choice == "on" else 0
    context.user_data.pop("awaiting", None)
    await _finish_create(update, context)

def _preset_ref(name: str) -> str:
    from services.utils.callback_codec import preset_token
    return preset_token(name)

async def _test_ai_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test current AI connection."""
    await notify_callback(update.callback_query, "در حال تست اتصال...", intent=CallbackNoticeIntent.INFO)
    try:
        active = db.get_active_preset()
    except db.NoActivePresetError:
        msg = Message()
        msg.add_line(plain("⚠️ "), plain("هیچ پیش‌تنظیم فعالی برای تست اتصال وجود ندارد."))
        msg.add_line(plain("اول یک پیش‌تنظیم را فعال کنید (یا در پنل AI یک پیش‌تنظیم جدید بسازید)."))
        await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ بازگشت به تنظیمات AI", callback_data="admin:ai_settings")]
        ]))
        return
    result = await asyncio.to_thread(
        ai.test_connection,
        active.get("base_url", ""),
        db.resolve_preset_key(active),
        active.get("model", ""),
        preset_fields.resolve(active, "timeout_seconds"),
        preset_fields.resolve(active, "reasoning_effort"),
    )

    msg = Message()
    if result["success"]:
        msg.add_line(plain("✅ "), bold("اتصال موفق"))
        msg.add_line(plain("Latency: "), plain(str(result['latency_ms'])), plain(" ms"))
        msg.add_line(plain("Model: "), plain(str(result.get('model', ''))))
        msg.add_line(plain("Tokens: "), plain(str(result.get('usage', ''))))
    else:
        msg.add_line(plain("❌ "), bold("خطا در اتصال"))
        msg.add_line(plain("Error: "), plain(str(result.get('error_class', ''))), plain(": "), plain(str(result.get('error_message', ''))))
        msg.add_line(plain("Latency: "), plain(str(result['latency_ms'])), plain(" ms"))

    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 تست مجدد", callback_data="admin:ai_test_connection")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
    ]))

