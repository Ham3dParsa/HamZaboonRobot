"""Admin AI domain module (Finding #7).

Migrate step: this module now DEFINES the standalone AI/preset/fallback/custom-test
handler logic moved out of the ``handlers.admin`` monolith. ``handlers.admin``
re-imports the symbols it dispatches on, and ``bot.py`` continues to import
``_edit_ai_preset`` via ``handlers.admin`` (unchanged call sites). Behavior is
byte-identical to the pre-split monolith. Nothing routes directly to this module
from ``bot.py``; dispatch flows through ``handlers.admin``.
"""

import asyncio
import hashlib
import re
from urllib.parse import quote, unquote

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from services import db
from services.utils.callback_codec import (
    resolve_field_alias,
    resolve_label_token,
    resolve_preset_token,
)
from services.ai import ai
from services.ai import prompts
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.helpers import _edit_or_send
from services.utils.formatting import html_escape
from config.catalog import GOALS, LANGUAGES, LEVELS
from config.keyboards import (
    BTN_BACK,
    IBTN_BACK,
    awaiting_inline_keyboard,
    admin_awaiting_inline_keyboard,
    ai_settings_keyboard,
    ai_presets_list_keyboard,
    ai_preset_view_keyboard,
    ai_preset_edit_keyboard,
    ai_fallback_keyboard,
    fallback_chain_keyboard,
    IBTN_FULL_EDIT_NEXT,
    IBTN_FULL_EDIT_BACK,
    IBTN_FULL_EDIT_SKIP,
    IBTN_FULL_EDIT_CANCEL_WIZARD,
    IBTN_FULL_EDIT_SAVE_ALL,
    IBTN_DELETE_CONFIRM,
    IBTN_DELETE_CANCEL,
    IBTN_GROUP_BATCH_KEY,
    IBTN_GROUP_SET_LABEL,
)

MAX_PRESET_NAME_LEN = 60
MAX_GROUP_LABEL_LEN = 40

_FIELD_HELP = {
    "name": "نام یکتای پریست. فقط حروف انگلیسی (a-z)، اعداد (0-9) و زیرخط (_) مجاز است. بعد از ذخیره قابل تغییر نیست.",
    "api_key": "کلید API سرویس‌دهنده (مثلاً sk-...). این کلید به‌صورت رمزنگاری‌شده در پایگاه داده ذخیره می‌شود.",
    "base_url": "آدرس سرور سازگار با OpenAI. نمونه: https://api.example.com/v1",
    "model": "نام دقیق مدل. نمونه: gpt-4o-mini یا gemini-2.0-flash-lite",
    "max_concurrency": "تعداد درخواست‌هایی که هم‌زمان به این سرویس‌دهنده فرستاده می‌شود. عدد ۲ یا ۳ معمول است.",
    "max_rpm": "بیشترین تعداد درخواست در هر دقیقه. صفر = بدون محدودیت.",
    "max_tpm": "بیشترین تعداد توکن ورودی و خروجی در هر دقیقه. صفر = بدون محدودیت.",
    "daily_batch_size": "تعداد کارت واژگان در هر دسته که یک‌جا از AI درخواست می‌شود. بین ۳ تا ۱۲.",
    "max_daily_req": "سقف تعداد درخواست به این پریست در هر روز. صفر = بدون محدودیت.",
    "timeout_seconds": "مدت زمان انتظار برای پاسخ از سرویس‌دهنده (به ثانیه). عدد اعشاری مجاز است.",
    "temperature": "میزان خلاقیت مدل. بین ۰.۰ (دقیق) تا ۲.۰ (خلاق). پیش‌فرض: ۰.۶",
    "max_output_tokens": "حداکثر تعداد توکن در هر پاسخ. پیش‌فرض: ۴۰۹۶",
    "priority": "اولویت در زنجیره فال‌بک. عدد کمتر = اولویت بیشتر. پریست با priority=۰ اولین نفری است که امتحان می‌شود.",
    "is_emergency": "آیا این پریست فقط برای مواقع اضطراری است؟ پریست‌های اضطراری همیشه بعد از پریست‌های عادی امتحان می‌شوند.",
    "in_fallback_chain": "آیا این پریست به‌صورت خودکار در زنجیره فال‌بک شرکت کند؟ اگر خاموش شود، فقط با انتخاب دستی قابل استفاده است.",
    "input_cost_per_million": "هزینه هر یک میلیون توکن ورودی (درخواست) به دلار. خالی = استفاده از مقدار سراسری تنظیم شده در داشبورد هزینه.",
    "output_cost_per_million": "هزینه هر یک میلیون توکن خروجی (پاسخ) به دلار. خالی = استفاده از مقدار سراسری.",
    "group_label": "برچسب دلخواه برای گروه‌بندی پریست‌هایی که کلید API مشترک دارند. نمونه: «سرویس‌دهنده اصلی» یا «پشتیبان رایگان»",
}


async def _show_ai_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main AI settings panel."""
    try:
        active_preset = db.get_active_preset()
    except db.NoActivePresetError:
        await _edit_or_send(
            update, context,
            "🤖 <b>تنظیمات هوش مصنوعی</b>\n\n"
            "⚠️ هیچ پیش‌تنظیم فعالی وجود ندارد.\n"
            "برای استفاده از هوش مصنوعی، از بخش «پیش‌تنظیم‌ها» یک پیش‌تنظیم بسازید و فعال کنید.",
            parse_mode=ParseMode.HTML,
            reply_markup=ai_settings_keyboard(),
        )
        return
    fallback_status = db.get_fallback_status()

    text = (
        "🤖 <b>تنظیمات هوش مصنوعی</b>\n\n"
        f"<b>پیش‌تنظیم فعال:</b> {html_escape(str(active_preset.get('name', 'gapgpt')))}\n"
        f"<b>مدل:</b> {html_escape(str(active_preset.get('model', '—')))}\n"
        f"<b>Base URL:</b> {html_escape(str(active_preset.get('base_url', '—')))}\n"
        f"<b>Batch Size:</b> {active_preset.get('daily_batch_size', 6)}\n"
        f"<b>Concurrency:</b> {active_preset.get('max_concurrency', 2)}\n"
        f"<b>RPM Limit:</b> {active_preset.get('max_rpm', 30)}\n\n"
    )

    if fallback_status.get("fallback_active"):
        text += (
            f"⚠️ <b>Fallback ACTIVE</b> since {html_escape(str(fallback_status.get('fallback_since', '?')))}\n"
            f"Primary: {html_escape(str(fallback_status.get('primary_preset', '—')))} → "
            f"Fallback: {html_escape(str(fallback_status.get('fallback_preset', '—')))}\n\n"
        )

    # Last successful preset per request kind (Rule #2)
    try:
        with db.get_conn() as conn:
            last_rows = conn.execute(
                "SELECT preset_name, request_kind FROM llm_requests "
                "WHERE request_kind IN ('daily_batch', 'grammar_tip', 'custom_word') "
                "AND outcome = 'success' "
                "AND created_at >= datetime('now', '-7 days') "
                "GROUP BY request_kind HAVING created_at = MAX(created_at)"
            ).fetchall()
        tracking = {row["request_kind"]: row["preset_name"] or "—" for row in last_rows}
        text += "📇 <b>آخرین درخواست‌ها:</b>\n"
        text += f"  Daily: {html_escape(tracking.get('daily_batch', '—'))}\n"
        text += f"  Grammar: {html_escape(tracking.get('grammar_tip', '—'))}\n"
        text += f"  Word: {html_escape(tracking.get('custom_word', '—'))}\n"
    except Exception:
        pass

    keyboard = ai_settings_keyboard()
    await _edit_or_send(update, context, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _show_ai_presets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all presets with pagination and view-mode toggle."""
    view_mode = context.user_data.get("preset_view_mode", "linear")
    if view_mode == "grouped":
        await _show_grouped_presets(update, context)
    else:
        await _show_linear_presets(update, context)


def _key_hash(api_key: str) -> str:
    """Short hash of an API key for callback_data."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


def _resolve_preset_ref(ref: str) -> str:
    """Resolve a callback preset ref (hash token) back to a real preset name.

    Falls back to the raw ref when it is not a resolvable hash token (e.g. a
    legacy plain-name callback), so behavior stays backward compatible.
    """
    return resolve_preset_token(ref) or ref


def _resolve_label_ref(ref: str) -> str | None:
    """Resolve a callback group-label ref (hash token) back to a real label.

    Legacy plain-label callbacks are URL-decoded. An unresolved 12-character
    hash is stale and must not become a persisted group label.
    """
    resolved = resolve_label_token(ref)
    if resolved:
        return resolved
    raw_ref = unquote(ref)
    # A legacy plain label may itself be 12 hexadecimal characters, making it
    # otherwise indistinguishable from the compact callback token.
    if any(group["label"] == raw_ref for group in db.get_group_labels()):
        return raw_ref
    if re.fullmatch(r"[0-9a-f]{12}", ref):
        return None
    return raw_ref


def _detect_key_groups() -> list[dict]:
    """Group all presets by resolved API key. Returns list sorted by count desc."""
    presets = db.get_presets()
    groups_map: dict[str, dict] = {}
    for p in presets:
        resolved = db.resolve_preset_key(p)
        if not resolved:
            resolved = "__no_key__"
        if resolved not in groups_map:
            masked = db.mask_key(resolved) if resolved != "__no_key__" else resolved
            groups_map[resolved] = {
                "resolved_key": resolved,
                "masked_key": masked,
                "key_hash": _key_hash(resolved),
                "label": p.get("group_label", "") or "",
                "count": 0,
                "names": [],
            }
        groups_map[resolved]["count"] += 1
        groups_map[resolved]["names"].append(p["name"])
        if p.get("group_label") and not groups_map[resolved]["label"]:
            groups_map[resolved]["label"] = p["group_label"]

    groups = sorted(groups_map.values(), key=lambda g: -g["count"])
    return groups


def _render_preset_brief(preset: dict, active_name: str) -> str:
    """Render one brief, HTML-escaped preset line for list/chain views (R6/R8).

    Pure synchronous renderer (no awaits): every list site calls it inline to
    build an HTML parse_mode message without wrapping a coroutine. Emoji per the
    UI/UX dictionary: 🟢/⚫ toggle reflects the enabled state, and the ``[tags]``
    suffix marks 🎯 active preset, 🛡️ emergency tier, and custom. The name is
    escaped for ``ParseMode.HTML``. Single shared implementation so every list
    site renders identically.
    """
    name = preset.get("name", "?")
    toggle = "🟢" if preset.get("enabled", 1) else "⚫"
    tags = []
    if name == active_name:
        tags.append("🎯")
    if preset.get("is_emergency"):
        tags.append("🛡️")
    suffix = (f" [{' '.join(tags)}]" if tags else "")
    return f"{toggle} <b>{html_escape(str(name))}</b>{suffix}"


async def _show_linear_presets(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Show paginated linear preset list."""
    all_presets = db.get_presets()
    active_name = db.get_active_preset_name()
    per_page = 5
    total_pages = max(1, (len(all_presets) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    page_presets = all_presets[start:end]

    lines = ["📋 <b>لیست پیش‌تنظیم‌ها</b>\n"]
    for p in page_presets:
        lines.append(
            f"{_render_preset_brief(p, active_name)}\n"
            f"   Model: {html_escape(str(p.get('model', '—')))}\n"
            f"   URL: {html_escape(str(p.get('base_url', '—')))}\n"
            f"   Batch: {p.get('daily_batch_size', 6)} | Concurrency: {p.get('max_concurrency', 2)} | RPM: {p.get('max_rpm', 30)}"
        )

    if total_pages > 1:
        lines.append(f"\n📄 صفحه {page + 1} از {total_pages}")

    text = "\n\n".join(lines)

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_presets_list_keyboard(
            all_presets, active_name,
            page=page, total_pages=total_pages,
            view_mode="linear",
        )
    )


async def _show_grouped_presets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show presets grouped by API key."""
    groups = _detect_key_groups()
    active_name = db.get_active_preset_name()

    lines = ["📁 <b>پیش‌تنظیم‌ها بر اساس کلید API</b>\n"]
    for g in groups:
        label = g.get("label") or g.get("masked_key", "—")
        lines.append(
            f"📁 <b>{html_escape(label)}</b> ({g['count']} preset)\n"
            f"   🔑 {html_escape(g.get('masked_key', '—'))}"
        )

    text = "\n\n".join(lines) if groups else "هیچ گروهی یافت نشد."

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_presets_list_keyboard(
            [], active_name,
            view_mode="grouped",
            groups=groups,
        )
    )


async def _show_ai_preset_view(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """View/edit a single preset."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    active_name = db.get_active_preset_name()
    is_active = preset_name == active_name

    masked_key = db.mask_key(db.resolve_preset_key(preset))

    from services.db import get_preset_cost as _get_preset_cost
    cost = _get_preset_cost(preset_name)
    input_cost_str = f"{cost['input_cost_per_million']}" if cost['input_cost_per_million'] is not None else "— (global)"
    output_cost_str = f"{cost['output_cost_per_million']}" if cost['output_cost_per_million'] is not None else "— (global)"

    text = (
        f"📋 <b>پیش‌تنظیم: {html_escape(preset_name)}</b>\n\n"
        f"Model: {html_escape(str(preset.get('model', '—')))}\n"
        f"Base URL: {html_escape(str(preset.get('base_url', '—')))}\n"
        f"API Key: {html_escape(masked_key)}\n"
        f"Daily Batch Size: {preset.get('daily_batch_size', 6)}\n"
        f"Max Concurrency: {preset.get('max_concurrency', 2)}\n"
        f"Max RPM: {preset.get('max_rpm', 30)}\n"
        f"Timeout: {preset.get('timeout_seconds', 30)}s\n"
        f"Temperature: {preset.get('temperature', 0.6)}\n"
        f"Max Output Tokens: {preset.get('max_output_tokens', 4096)}\n"
        f"Input Cost: {input_cost_str} $/1M\n"
        f"Output Cost: {output_cost_str} $/1M\n"
    )

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_preset_view_keyboard(preset, active_name)
    )


async def _activate_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Activate a preset as primary."""
    success = db.activate_preset(preset_name)
    if success:
        await notify_callback(update.callback_query, f"پیش‌تنظیم {preset_name} فعال شد", intent=CallbackNoticeIntent.SUCCESS)
    else:
        await notify_callback(update.callback_query, "خطا در فعال‌سازی", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
    await _show_ai_preset_view(update, context, preset_name)


async def _edit_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Show field edit options for a preset."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    text = f"✏️ <b>ویرایش پیش‌تنظیم: {html_escape(preset_name)}</b>\nانتخاب فیلد برای تغییر:"

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_preset_edit_keyboard(preset_name, preset)
    )


async def _edit_ai_preset_field(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_name: str):
    """Prompt for new value of a field."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    current = preset.get(field_name, "")
    if current is None:
        current = ""
    context.user_data["awaiting"] = f"ai_preset_edit:{preset_name}:{field_name}"

    field_labels = {
        "base_url": "Base URL",
        "model": "Model Name",
        "api_key": "API Key (literal; stored encrypted)",
        "daily_batch_size": "Batch Size (integer)",
        "max_concurrency": "Concurrency (integer)",
        "max_rpm": "RPM Limit (integer)",
        "max_tpm": "Max TPM (integer, 0 = unlimited)",
        "max_daily_req": "Max Daily Requests (integer, 0 = unlimited)",
        "timeout_seconds": "Timeout in seconds (float)",
        "temperature": "Temperature (0.0-2.0)",
        "max_output_tokens": "Max Output Tokens (integer)",
        "is_emergency": "Is Emergency (0 or 1)",
        "name": "Preset Name (a-z, 0-9, _)",
        "input_cost_per_million": "Input Cost $/1M tokens (empty = global)",
        "output_cost_per_million": "Output Cost $/1M tokens (empty = global)",
        "in_fallback_chain": "In Fallback Chain (0 or 1)",
        "group_label": "Group Label (any text)",
    }

    help_text = _FIELD_HELP.get(field_name, "")
    message = (
        f"✏️ <b>{html_escape(field_labels.get(field_name, field_name))}</b>\n"
        f"مقدار فعلی: <code>{html_escape(str(current))}</code>\n\n"
        f"مقدار جدید را ارسال کنید:"
    )
    if help_text:
        message += f"\n\n💡 {help_text}"

    await _edit_or_send(
        update, context, message,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_awaiting_inline_keyboard()
    )


async def _handle_ai_preset_field_input(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_name: str, text: str):
    """Process field input for preset edit."""
    preset = db.get_preset(preset_name)
    if not preset:
        await update.message.reply_text("پیش‌تنظیم یافت نشد")
        return

    raw = text.strip()

    # Parse and validate based on field type
    try:
        if field_name in ("daily_batch_size", "max_concurrency", "max_rpm", "max_tpm", "max_daily_req", "max_output_tokens"):
            value = int(raw)
            if value < 0:
                raise ValueError
        elif field_name in ("timeout_seconds", "temperature"):
            value = float(raw)
        elif field_name == "is_emergency":
            value = int(raw)
            if value not in (0, 1):
                raise ValueError
        elif field_name == "name":
            value = raw.lower().replace(" ", "_")
            if not value or not all(c.isalnum() or c == "_" for c in value) or len(value) > MAX_PRESET_NAME_LEN:
                raise ValueError
            # Check uniqueness (skip if same as current)
            if value != preset_name and db.get_preset(value):
                context.user_data["awaiting"] = f"ai_preset_edit:{preset_name}:{field_name}"
                await update.message.reply_text("این نام از قبل وجود دارد. نام دیگری انتخاب کنید.", reply_markup=awaiting_inline_keyboard())
                return
        elif field_name in ("input_cost_per_million", "output_cost_per_million"):
            if raw == "":
                value = None
            else:
                value = float(raw)
                if value < 0:
                    raise ValueError
        elif field_name == "in_fallback_chain":
            value = int(raw)
            if value not in (0, 1):
                raise ValueError
        elif field_name == "group_label":
            value = raw
            if not value or len(value) > MAX_GROUP_LABEL_LEN:
                raise ValueError
        else:
            value = raw
    except ValueError:
        context.user_data["awaiting"] = f"ai_preset_edit:{preset_name}:{field_name}"
        await update.message.reply_text("فرمت نامعتبر. لطفاً مقدار معتبر بفرستید.", reply_markup=awaiting_inline_keyboard())
        return

    # Store in-memory (per preset)
    edits = context.user_data.setdefault("preset_edits", {})
    edits.setdefault(preset_name, {})[field_name] = value

    # Auto-delete user message containing plaintext API key
    if field_name == "api_key":
        try:
            await update.message.delete()
        except Exception:
            pass

    context.user_data.pop("awaiting", None)

    await update.message.reply_text(
        f"✅ <b>{html_escape(field_name)}</b> برای پیش‌تنظیم <b>{html_escape(preset_name)}</b> ثبت شد.",
        parse_mode=ParseMode.HTML
    )
    await _edit_ai_preset(update, context, preset_name)


WIZARD_FIELDS = [
    "name", "api_key", "base_url", "model",
    "max_concurrency", "max_rpm", "max_tpm", "daily_batch_size",
    "max_daily_req", "timeout_seconds", "temperature", "max_output_tokens",
    "priority", "is_emergency", "in_fallback_chain",
    "input_cost_per_million", "output_cost_per_million", "group_label",
]

WIZARD_GROUP_HEADERS = {
    0: "🆔 — گروه هویت (Identity):",
    4: "🔒 — گروه محدودیت‌ها (Limits):",
    12: "⛓️ — گروه فال‌بک (Fallback):",
    15: "💰 — گروه هزینه و برچسب (Cost & Label):",
}

WIZARD_FIELD_LABELS = {
    "name": "نام پریست",
    "api_key": "API Key",
    "base_url": "Base URL",
    "model": "Model",
    "max_concurrency": "Concurrency",
    "max_rpm": "RPM Limit",
    "max_tpm": "حد توکن در دقیقه (TPM)",
    "daily_batch_size": "Batch Size",
    "max_daily_req": "سقف درخواست روزانه",
    "timeout_seconds": "Timeout (s)",
    "temperature": "Temperature",
    "max_output_tokens": "Max Output Tokens",
    "priority": "اولویت (Priority)",
    "is_emergency": "پریست اضطراری",
    "in_fallback_chain": "حضور در زنجیره فال‌بک",
    "input_cost_per_million": "هزینه ورودی ($/1M)",
    "output_cost_per_million": "هزینه خروجی ($/1M)",
    "group_label": "برچسب گروه",
}

TOTAL_WIZARD_FIELDS = len(WIZARD_FIELDS)


async def _start_full_edit_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Start the full preset edit wizard."""
    if any(context.user_data.get("preset_edits", {}).values()):
        await notify_callback(update.callback_query, "ابتدا تغییرات فعلی را ذخیره یا دور بریزید.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    context.user_data["full_edit"] = {"preset": preset_name, "field_idx": 0, "values": {}}
    context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:0"
    await _show_wizard_field(update, context, preset_name, 0, preset)


async def _show_wizard_field(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_idx: int, preset: dict):
    """Display a wizard field with prompt, Current (stored) and Draft (in-progress) values, and navigation."""
    field_name = WIZARD_FIELDS[field_idx]
    current = preset.get(field_name, "")
    if current is None:
        current = ""
    current_str = str(current)

    wizard = context.user_data.get("full_edit", {})
    draft = wizard.get("values", {}).get(field_name)
    draft_str = str(draft).strip() if draft is not None else None

    group_header = WIZARD_GROUP_HEADERS.get(field_idx, "")
    label = WIZARD_FIELD_LABELS.get(field_name, field_name)
    help_text = _FIELD_HELP.get(field_name, "")

    message = f"✏️ <b>ویرایش کامل — گام {field_idx + 1} از {TOTAL_WIZARD_FIELDS}</b>\n"
    if group_header:
        message += f"\n{group_header}\n"
    message += f"\n<b>{html_escape(label)}</b>"
    if draft_str:
        message += f"\nپیشنویس (در انتظار ذخیره): <code>{html_escape(draft_str)}</code>"
    if current_str:
        message += f"\nمقدار فعلی: <code>{html_escape(current_str)}</code>"
    else:
        message += "\nمقدار فعلی: <i>خالی</i>"
    if help_text:
        message += f"\n\n💡 {help_text}"
    message += "\n\nمقدار جدید را ارسال کنید (یا خالی = رد کردن):"

    from services.utils.callback_codec import preset_token
    preset_ref = preset_token(preset_name)
    buttons = []
    if field_idx > 0:
        buttons.append(InlineKeyboardButton(IBTN_FULL_EDIT_BACK, callback_data=f"admin:ai_preset:full_edit_back:{preset_ref}"))
    if field_idx < TOTAL_WIZARD_FIELDS - 1:
        buttons.append(InlineKeyboardButton(IBTN_FULL_EDIT_NEXT, callback_data=f"admin:ai_preset:full_edit_next:{preset_ref}"))
    buttons.append(InlineKeyboardButton(IBTN_FULL_EDIT_SKIP, callback_data=f"admin:ai_preset:full_edit_skip:{preset_ref}"))
    buttons.append(InlineKeyboardButton(IBTN_FULL_EDIT_CANCEL_WIZARD, callback_data=f"admin:ai_preset:full_edit_cancel:{preset_ref}"))

    # Add group label picker buttons when editing group_label
    if field_name == "group_label":
        existing_groups = db.get_group_labels()
        if existing_groups:
            from services.utils.callback_codec import label_token, preset_token
            # Add group picker buttons in rows of 2
            group_rows = []
            for g in existing_groups:
                g_label = g["label"]
                g_count = g["count"]
                group_rows.append(InlineKeyboardButton(
                    f"🏷️ {g_label} ({g_count})",
                    callback_data=f"admin:ai_preset:full_edit_pick_group:{preset_token(preset_name)}:{label_token(g_label)}"
                ))
            # Split into rows of 2
            keyboard_rows = [[group_rows[i], group_rows[i + 1]] if i + 1 < len(group_rows) else [group_rows[i]]
                             for i in range(0, len(group_rows), 2)]
            keyboard_rows.append(buttons)
            keyboard = InlineKeyboardMarkup(keyboard_rows)
        else:
            keyboard = InlineKeyboardMarkup([buttons])
    else:
        keyboard = InlineKeyboardMarkup([buttons])

    context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{field_idx}"

    await _edit_or_send(update, context, message, parse_mode=ParseMode.HTML, reply_markup=keyboard)


def _validate_wizard_value(field_name: str, raw: str, preset_name: str) -> tuple | None:
    """Validate a wizard field value. Returns (value,) or None on invalid."""
    try:
        if field_name in ("daily_batch_size", "max_concurrency", "max_rpm", "max_tpm", "max_daily_req", "max_output_tokens"):
            v = int(raw)
            if v < 0:
                return None
            return (v,)
        elif field_name in ("timeout_seconds", "temperature"):
            return (float(raw),)
        elif field_name == "is_emergency":
            v = int(raw)
            if v not in (0, 1):
                return None
            return (v,)
        elif field_name == "name":
            v = raw.lower().replace(" ", "_")
            if not v or not all(c.isalnum() or c == "_" for c in v) or len(v) > MAX_PRESET_NAME_LEN:
                return None
            if v != preset_name and db.get_preset(v):
                return None
            return (v,)
        elif field_name in ("input_cost_per_million", "output_cost_per_million"):
            if raw == "":
                return (None,)
            v = float(raw)
            if v < 0:
                return None
            return (v,)
        elif field_name == "in_fallback_chain":
            v = int(raw)
            if v not in (0, 1):
                return None
            return (v,)
        elif field_name == "priority":
            v = int(raw)
            if v < 0:
                return None
            return (v,)
        elif field_name == "group_label":
            if not raw or len(raw) > MAX_GROUP_LABEL_LEN:
                return None
            return (raw,)
        else:
            return (raw,)
    except (ValueError, TypeError):
        return None


async def _handle_full_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_idx: int, text: str):
    """Handle text input during full edit wizard."""
    preset = db.get_preset(preset_name)
    if not preset:
        await update.message.reply_text("پیش‌تنظیم یافت نشد")
        return

    field_name = WIZARD_FIELDS[field_idx]
    raw = text.strip()

    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await update.message.reply_text("ویزارد منقضی شده. دوباره شروع کنید.")
        return

    if raw:
        result = _validate_wizard_value(field_name, raw, preset_name)
        if result is None:
            context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{field_idx}"
            await update.message.reply_text("فرمت نامعتبر. لطفاً مقدار معتبر بفرستید.", reply_markup=awaiting_inline_keyboard())
            return
        wizard["values"][field_name] = result[0]

    next_idx = field_idx + 1
    wizard["field_idx"] = next_idx

    if next_idx >= TOTAL_WIZARD_FIELDS:
        await _show_wizard_summary(update, context, preset_name)
    else:
        context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{next_idx}"
        await _show_wizard_field(update, context, preset_name, next_idx, preset)


async def _handle_full_edit_next(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Advance to next field without saving current."""
    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await notify_callback(update.callback_query, "ویزارد منقضی شده", intent=CallbackNoticeIntent.INFO)
        return

    current_idx = wizard.get("field_idx", 0)
    next_idx = current_idx + 1
    wizard["field_idx"] = next_idx

    preset = db.get_preset(preset_name)
    if next_idx >= TOTAL_WIZARD_FIELDS:
        await _show_wizard_summary(update, context, preset_name)
    else:
        context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{next_idx}"
        await _show_wizard_field(update, context, preset_name, next_idx, preset or {})


async def _handle_full_edit_pick_group(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, label: str | None):
    """Handle group label picker selection in wizard."""
    if label is None:
        await notify_callback(update.callback_query, "برچسب گروه یافت نشد. دوباره ویرایش را باز کنید.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await notify_callback(update.callback_query, "ویزارد منقضی شده", intent=CallbackNoticeIntent.INFO)
        return

    wizard["values"]["group_label"] = label
    current_idx = wizard.get("field_idx", 0)
    next_idx = current_idx + 1
    wizard["field_idx"] = next_idx

    preset = db.get_preset(preset_name)
    if next_idx >= TOTAL_WIZARD_FIELDS:
        await _show_wizard_summary(update, context, preset_name)
    else:
        context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{next_idx}"
        await notify_callback(update.callback_query, f"✅ {label}", intent=CallbackNoticeIntent.SUCCESS)
        await _show_wizard_field(update, context, preset_name, next_idx, preset or {})


async def _handle_full_edit_skip(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Skip current field and advance."""
    await _handle_full_edit_next(update, context, preset_name)


async def _handle_full_edit_back(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """R5: move back one field without saving current. Disabled on the first field."""
    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await notify_callback(update.callback_query, "ویزارد منقضی شده", intent=CallbackNoticeIntent.INFO)
        return

    current_idx = wizard.get("field_idx", 0)
    if current_idx <= 0:
        await notify_callback(update.callback_query, "در گام اول هستید", intent=CallbackNoticeIntent.INFO)
        return

    prev_idx = current_idx - 1
    wizard["field_idx"] = prev_idx
    preset = db.get_preset(preset_name)
    context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{prev_idx}"
    await _show_wizard_field(update, context, preset_name, prev_idx, preset or {})


async def _handle_full_edit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Cancel the full edit wizard."""
    context.user_data.pop("full_edit", None)
    context.user_data.pop("awaiting", None)
    await notify_callback(update.callback_query, "ویرایش کامل لغو شد", intent=CallbackNoticeIntent.INFO)
    await _edit_ai_preset(update, context, preset_name)


async def _show_wizard_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Show summary of wizard changes and ask for confirmation."""
    wizard = context.user_data.get("full_edit", {})
    values = wizard.get("values", {})
    preset = db.get_preset(preset_name) or {}

    lines = [f"📋 <b>خلاصه تغییرات برای {html_escape(preset_name)}</b>\n"]
    changed = 0
    for field_name in WIZARD_FIELDS:
        if field_name in values:
            new_val = values[field_name]
            old_val = preset.get(field_name, "—")
            label = WIZARD_FIELD_LABELS.get(field_name, field_name)
            lines.append(f"• <b>{html_escape(label)}</b>: {html_escape(str(old_val))} → {html_escape(str(new_val))}")
            changed += 1

    if not changed:
        lines.append("هیچ تغییری اعمال نشد.")

    lines.append(f"\nتعداد تغییرات: {changed}")
    text = "\n".join(lines)

    from services.utils.callback_codec import preset_token
    preset_ref = preset_token(preset_name)
    buttons = [
        InlineKeyboardButton(IBTN_FULL_EDIT_SAVE_ALL, callback_data=f"admin:ai_preset:full_edit_save:{preset_ref}"),
        InlineKeyboardButton(IBTN_FULL_EDIT_CANCEL_WIZARD, callback_data=f"admin:ai_preset:full_edit_cancel:{preset_ref}"),
    ]
    keyboard = InlineKeyboardMarkup([buttons])

    context.user_data.pop("awaiting", None)

    await _edit_or_send(update, context, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _handle_full_edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Save all wizard changes."""
    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await notify_callback(update.callback_query, "ویزارد منقضی شده", intent=CallbackNoticeIntent.INFO)
        return

    values = wizard.get("values", {})
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    new_name = values.get("name", preset_name)
    rename = new_name != preset_name

    db.set_preset(
        name=new_name,
        base_url=values.get("base_url", preset.get("base_url", "")),
        model=values.get("model", preset.get("model", "")),
        api_key=values.get("api_key", preset.get("api_key", "")),
        daily_batch_size=int(values.get("daily_batch_size", preset.get("daily_batch_size", 6))),
        max_concurrency=int(values.get("max_concurrency", preset.get("max_concurrency", 2))),
        max_rpm=int(values.get("max_rpm", preset.get("max_rpm", 30))),
        max_tpm=int(values.get("max_tpm", preset.get("max_tpm", 0))),
        max_daily_req=int(values.get("max_daily_req", preset.get("max_daily_req", 0))),
        timeout_seconds=float(values.get("timeout_seconds", preset.get("timeout_seconds", 30.0))),
        temperature=float(values.get("temperature", preset.get("temperature", 0.6))),
        max_output_tokens=int(values.get("max_output_tokens", preset.get("max_output_tokens", 4096))),
        is_emergency=int(values.get("is_emergency", preset.get("is_emergency", 0))),
        input_cost_per_million=values.get("input_cost_per_million", preset.get("input_cost_per_million")),
        output_cost_per_million=values.get("output_cost_per_million", preset.get("output_cost_per_million")),
        in_fallback_chain=int(values.get("in_fallback_chain", preset.get("in_fallback_chain", 1))),
        group_label=values.get("group_label", preset.get("group_label", "")),
    )

    if rename:
        db.delete_preset(preset_name)

    context.user_data.pop("full_edit", None)
    context.user_data.pop("awaiting", None)

    await notify_callback(update.callback_query, f"پیش‌تنظیم {new_name} ذخیره شد", intent=CallbackNoticeIntent.SUCCESS)
    await _show_ai_preset_view(update, context, new_name)


async def _toggle_preset_view_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle between linear and grouped preset view."""
    current = context.user_data.get("preset_view_mode", "linear")
    new_mode = "grouped" if current == "linear" else "linear"
    context.user_data["preset_view_mode"] = new_mode
    await notify_callback(update.callback_query, f"حالت نمایش: {'گروهی' if new_mode == 'grouped' else 'خطی'}", intent=CallbackNoticeIntent.INFO)
    await _show_ai_presets(update, context)


async def _handle_group_view(update: Update, context: ContextTypes.DEFAULT_TYPE, key_hash: str):
    """Show details for a specific group."""
    groups = _detect_key_groups()
    target = next((g for g in groups if g["key_hash"] == key_hash), None)
    if not target:
        await notify_callback(update.callback_query, "گروه یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    names = target["names"]
    presets = [db.get_preset(n) for n in names if db.get_preset(n)]
    active_name = db.get_active_preset_name()

    lines = [f"📁 <b>گروه: {html_escape(str(target.get('label') or target['masked_key']))}</b>\n"]
    lines.append(f"🔑 کلید: {html_escape(target['masked_key'])}")
    lines.append(f"تعداد: {target['count']} preset\n")
    for p in presets:
        lines.append(f"{_render_preset_brief(p, active_name)} — {html_escape(str(p.get('model', '—')))}")

    text = "\n".join(lines)

    buttons = [
        [
            InlineKeyboardButton(IBTN_GROUP_BATCH_KEY, callback_data=f"admin:ai_preset:group_batch_key:{key_hash}"),
            InlineKeyboardButton(IBTN_GROUP_SET_LABEL, callback_data=f"admin:ai_preset:group_set_label:{key_hash}"),
        ],
        [InlineKeyboardButton(BTN_BACK, callback_data="admin:ai_presets")],
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    await _edit_or_send(update, context, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _handle_group_batch_key(update: Update, context: ContextTypes.DEFAULT_TYPE, key_hash: str):
    """Start awaiting flow for batch API key update."""
    context.user_data["awaiting"] = f"admin_group_batch_key:{key_hash}"
    await _edit_or_send(
        update, context,
        "🔑 کلید API جدید را برای همه اعضای این گروه ارسال کنید:",
        reply_markup=admin_awaiting_inline_keyboard(),
    )


async def _handle_group_set_label(update: Update, context: ContextTypes.DEFAULT_TYPE, key_hash: str):
    """Start awaiting flow for group label update."""
    context.user_data["awaiting"] = f"admin_group_set_label:{key_hash}"
    await _edit_or_send(
        update, context,
        "🏷️ برچسب جدید گروه را ارسال کنید:",
        reply_markup=admin_awaiting_inline_keyboard(),
    )


async def _show_group_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show group manager — list all group_labels with preset counts."""
    groups = db.get_group_labels()
    lines = ["🏷️ <b>مدیریت گروه‌ها</b>\n\n"]
    if not groups:
        lines.append("هیچ گروهی تعریف نشده است.\nبرای گروه‌بندی، از فیلد group_label استفاده کنید.")
    else:
        for g in groups:
            lines.append(f"• <b>{html_escape(g['label'])}</b> — {g['count']} پریست")
    lines.append("")

    buttons = []
    from services.utils.callback_codec import label_token
    for g in groups:
        buttons.append([
            InlineKeyboardButton(f"✏️ {g['label']}", callback_data=f"admin:ai_preset:group_manager_rename:{label_token(g['label'])}"),
            InlineKeyboardButton(f"🗑️ حذف برچسب", callback_data=f"admin:ai_preset:group_manager_clear:{label_token(g['label'])}"),
        ])
    buttons.append([InlineKeyboardButton(IBTN_BACK, callback_data="admin:ai_settings")])

    await _edit_or_send(update, context, "".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def _handle_group_manager_rename(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    """Start rename flow for a group label."""
    context.user_data["awaiting"] = f"admin_group_manager_rename:{quote(label)}"
    await _edit_or_send(
        update, context,
        f"✏️ نام جدید برای گروه <b>{html_escape(label)}</b> را ارسال کنید:\n"
        "(خالی = انصراف)",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_awaiting_inline_keyboard(),
    )


async def _handle_group_manager_clear(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    """Clear a group label from all presets."""
    db.clear_group_label(label)
    await notify_callback(update.callback_query, f"✅ برچسب «{label}» از همه پریست‌ها حذف شد", intent=CallbackNoticeIntent.SUCCESS)
    await _show_group_manager(update, context)


async def _confirm_save_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Show confirmation dialog before saving."""
    edits = context.user_data.get("preset_edits", {}).get(preset_name, {})
    if not edits:
        await notify_callback(update.callback_query, "تغییری برای ذخیره وجود ندارد", intent=CallbackNoticeIntent.INFO)
        return

    from config.keyboards import IBTN_SAVE_CONFIRM, IBTN_SAVE_CANCEL
    from services.utils.callback_codec import preset_token
    preset_ref = preset_token(preset_name)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(IBTN_SAVE_CONFIRM, callback_data=f"admin:ai_preset:confirm_save_yes:{preset_ref}"),
            InlineKeyboardButton(IBTN_SAVE_CANCEL, callback_data=f"admin:ai_preset:confirm_save_no:{preset_ref}"),
        ]
    ])
    await _edit_or_send(
        update, context,
        f"⚠️ <b>آیا از ذخیره تغییرات برای «{html_escape(preset_name)}» مطمئنید؟</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _discard_all_preset_changes(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Discard all pending edits for a preset."""
    context.user_data.setdefault("preset_edits", {}).pop(preset_name, None)
    await notify_callback(update.callback_query, "همه تغییرات دور ریخته شد", intent=CallbackNoticeIntent.INFO)
    await _show_ai_preset_view(update, context, preset_name)


async def _detach_ai_preset_group(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Stage removal of one custom preset from its group until Save is confirmed."""
    if context.user_data.get("full_edit"):
        await notify_callback(update.callback_query, "ابتدا ویرایش کامل را تمام یا لغو کنید.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم قابل ویرایش یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    if not preset.get("group_label"):
        await notify_callback(update.callback_query, "این پیش‌تنظیم در گروهی نیست", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    edits = context.user_data.setdefault("preset_edits", {})
    edits.setdefault(preset_name, {})["group_label"] = ""
    await notify_callback(update.callback_query, "✅ حذف از گروه ثبت شد. برای اعمال، ذخیره را بزنید.", intent=CallbackNoticeIntent.SUCCESS)
    await _edit_ai_preset(update, context, preset_name)


async def _save_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Save all pending changes for a preset to the database."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    # Read in-memory edits for this preset
    edits = context.user_data.get("preset_edits", {}).get(preset_name, {})
    if not edits:
        await notify_callback(update.callback_query, "تغییری برای ذخیره وجود ندارد", intent=CallbackNoticeIntent.INFO)
        return

    # Handle rename: if name changed, use new name as key
    new_name = edits.get("name", preset_name)
    rename = new_name != preset_name
    removing_group = (
        edits.get("group_label") == "" and bool(preset.get("group_label"))
    )

    # Apply to preset from in-memory edits + existing values as fallback
    try:
        db.set_preset(
            name=new_name,
            base_url=edits.get("base_url", preset.get("base_url", "")),
            model=edits.get("model", preset.get("model", "")),
            api_key=edits.get("api_key", preset.get("api_key", "")),
            daily_batch_size=int(edits.get("daily_batch_size", preset.get("daily_batch_size", 6))),
            max_concurrency=int(edits.get("max_concurrency", preset.get("max_concurrency", 2))),
            max_rpm=int(edits.get("max_rpm", preset.get("max_rpm", 30))),
            max_tpm=int(edits.get("max_tpm", preset.get("max_tpm", 0))),
            max_daily_req=int(edits.get("max_daily_req", preset.get("max_daily_req", 0))),
            timeout_seconds=float(edits.get("timeout_seconds", preset.get("timeout_seconds", 30.0))),
            temperature=float(edits.get("temperature", preset.get("temperature", 0.6))),
            max_output_tokens=int(edits.get("max_output_tokens", preset.get("max_output_tokens", 4096))),
            is_emergency=int(edits.get("is_emergency", preset.get("is_emergency", 0))),
            input_cost_per_million=edits.get("input_cost_per_million", preset.get("input_cost_per_million")),
            output_cost_per_million=edits.get("output_cost_per_million", preset.get("output_cost_per_million")),
            in_fallback_chain=int(edits.get("in_fallback_chain", preset.get("in_fallback_chain", 1))),
            group_label=edits.get("group_label", preset.get("group_label", "")),
            previous_name=preset_name,
            remove_orphaned_group_key=removing_group,
        )
    except ValueError:
        await notify_callback(update.callback_query, "این نام هم‌اکنون توسط پیش‌تنظیم دیگری استفاده می‌شود.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    # The database transaction already removed the old row when renamed.
    if rename:
        # Move pending edits to new name key
        context.user_data.setdefault("preset_edits", {}).pop(preset_name, None)

    # Clear in-memory edits for this preset
    context.user_data.setdefault("preset_edits", {}).pop(new_name, None)

    await notify_callback(update.callback_query, f"پیش‌تنظیم {new_name} ذخیره شد", intent=CallbackNoticeIntent.SUCCESS)
    await _show_ai_preset_view(update, context, new_name)


async def _delete_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """R3: first step of two-step delete — show an inline confirmation."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    active_name = db.get_active_preset_name()
    if preset_name == active_name:
        await notify_callback(update.callback_query, "نمی‌توان پیش‌تنظیم فعال را حذف کرد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    from services.utils.callback_codec import preset_token
    preset_ref = preset_token(preset_name)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(IBTN_DELETE_CONFIRM, callback_data=f"admin:ai_preset:confirm_delete_yes:{preset_ref}"),
            InlineKeyboardButton(IBTN_DELETE_CANCEL, callback_data=f"admin:ai_preset:confirm_delete_no:{preset_ref}"),
        ],
        [InlineKeyboardButton(BTN_BACK, callback_data=f"admin:ai_preset:view:{preset_ref}")],
    ])
    await _edit_or_send(
        update, context,
        f"⚠️ <b>آیا از حذف پیش‌تنظیم «{html_escape(preset_name)}» مطمئنید؟</b>\nاین عمل بازگشت‌پذیر نیست.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def _confirm_delete_yes(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """R3: second step — actually delete after owner confirmed."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    active_name = db.get_active_preset_name()
    if preset_name == active_name:
        await notify_callback(update.callback_query, "نمی‌توان پیش‌تنظیم فعال را حذف کرد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    db.delete_preset(preset_name)
    await notify_callback(update.callback_query, f"پیش‌تنظیم {preset_name} حذف شد", intent=CallbackNoticeIntent.SUCCESS)
    await _show_ai_presets(update, context)


async def _confirm_delete_no(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """R3: cancel delete — return to the preset detail view."""
    await notify_callback(update.callback_query, "حذف لغو شد", intent=CallbackNoticeIntent.INFO)
    await _show_ai_preset_view(update, context, preset_name)


async def _duplicate_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """R4: clone a preset into a new name; default `<old> (copy)`, then offer a rename."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    new_name = f"{preset_name} (copy)"
    try:
        db.clone_preset(preset_name, new_name)
    except ValueError as exc:
        await notify_callback(update.callback_query, str(exc), intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    await notify_callback(update.callback_query, f"نسخه کپی «{new_name}» ساخته شد", intent=CallbackNoticeIntent.SUCCESS)
    await _show_ai_preset_view(update, context, new_name)


async def _add_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a new custom preset - start with name input."""
    context.user_data["awaiting"] = "admin_ai_preset_new_name"
    await _edit_or_send(
        update, context,
        "➕ <b>ایجاد پیش‌تنظیم جدید</b>\n\n"
        "نام پیش‌تنظیم را وارد کنید (مثال: my_openai):",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_awaiting_inline_keyboard()
    )


async def _handle_ai_preset_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle new preset name input."""
    name = text.strip().lower().replace(" ", "_")
    if not name or not all(c.isalnum() or c == "_" for c in name) or len(name) > MAX_PRESET_NAME_LEN:
        context.user_data["awaiting"] = "ai_preset_new_name"
        await update.message.reply_text("نام نامعتبر. فقط حروف، اعداد و زیرخط مجاز است و حداکثر ۶۰ کاراکتر.", reply_markup=awaiting_inline_keyboard())
        return

    existing = db.get_preset(name)
    if existing:
        context.user_data["awaiting"] = "ai_preset_new_name"
        await update.message.reply_text("این نام از قبل وجود دارد.", reply_markup=awaiting_inline_keyboard())
        return

    # Begin the create flow: remember the pending name, then ask for priority.
    context.user_data["preset_create"] = {"name": name}
    context.user_data.pop("awaiting", None)
    await _show_create_priority(update, context)


# ======== R14 Create Flow ========

CREATE_PRIORITY_PROMPT = (
    "🎯 <b>اولویت در زنجیره فال‌بک</b>\n\n"
    "جایگاه پیش‌تنظیم جدید در زنجیره فال‌بک را انتخاب کنید:\n"
    "• <b>بالا (مقدم)</b> — اولین نفری که امتحان می‌شود\n"
    "• <b>پایین (کم‌اولویت)</b> — آخرین نفری که امتحان می‌شود\n"
    "• <b>دستی</b> — عدد اولویت دلخواه وارد کنید"
)


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
    await _edit_or_send(
        update, context,
        f"➕ <b>ایجاد پیش‌تنظیم جدید</b> — <code>{html_escape(name)}</code>\n\n" + CREATE_PRIORITY_PROMPT,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _show_create_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt for enabled status + a lightweight ping test (R14)."""
    state = context.user_data.setdefault("preset_create", {})
    name = state.get("name", "")
    buttons = [
        [
            InlineKeyboardButton("🟢 فعال", callback_data="admin:ai_preset:create:status:on"),
            InlineKeyboardButton("⚫ غیرفعال", callback_data="admin:ai_preset:create:status:off"),
        ],
        [
            InlineKeyboardButton("🔁 تست اتصال سبک", callback_data="admin:ai_preset:create:test"),
        ],
        [InlineKeyboardButton("❌ لغو", callback_data="admin:ai_settings")],
    ]
    await _edit_or_send(
        update, context,
        f"⚙️ <b>وضعیت پیش‌تنظیم</b> — <code>{html_escape(name)}</code>\n\n"
        "پیش‌تنظیم جدید به‌صورت <b>غیرفعال</b> ساخته می‌شود و تا وقتی آگاهانه فعالش نکنید، "
        "هیچ درخواستی را سرو نمی‌کند. وضعیت را انتخاب کنید (می‌توانید پیش از آن اتصال را تست کنید):",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


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
    buttons = [
        [
            InlineKeyboardButton("🔁 تست اتصال", callback_data="admin:ai_preset:create:test"),
            InlineKeyboardButton("🔄 تغییر وضعیت", callback_data="admin:ai_preset:create:toggle_enable"),
        ],
        [
            InlineKeyboardButton("✏️ ادامه ویرایش کامل", callback_data=f"admin:ai_preset:full_edit:{_preset_ref(name)}"),
        ],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_presets")],
    ]
    await _edit_or_send(
        update, context,
        f"✅ <b>پیش‌تنظیم ساخته شد</b> — <code>{html_escape(name)}</code>\n\n"
        f"• وضعیت: {status}\n"
        f"• اولویت زنجیره: <code>{preset.get('priority', 0)}</code>\n"
        f"• سفارشی: بله\n\n"
        "می‌توانید اتصال را تست کنید، وضعیت را تغییر دهید، یا مستقیم وارد ویرایش کامل شوید.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def _normal_chain_count() -> int:
    """Number of enabled normal (non-emergency) in-fallback presets (R14)."""
    return sum(1 for p in db.get_fallback_chain_presets() if not p.get("is_emergency"))


async def _handle_create_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lightweight ping test of the pending (or just-created) preset (R14)."""
    state = context.user_data.get("preset_create", {})
    name = state.get("name", "")
    preset = db.get_preset(name)
    await notify_callback(update.callback_query, "در حال تست اتصال...", intent=CallbackNoticeIntent.INFO)
    if preset and (preset.get("base_url") or preset.get("model") or preset.get("api_key")):
        result = await asyncio.to_thread(
            ai.test_connection,
            base_url=preset.get("base_url", ""),
            api_key=db.resolve_preset_key(preset),
            model=preset.get("model", ""),
            timeout=preset.get("timeout_seconds", 30.0),
        )
        if result["success"]:
            body = f"✅ <b>اتصال موفق</b>\nتأخیر: {result['latency_ms']} ms"
        else:
            body = f"❌ <b>خطا در اتصال</b>\nخطا: {html_escape(str(result.get('error_message', '')))}"
    else:
        body = (
            "⚠️ <b>تست اتصال برای پیش‌تنظیم تازه</b>\n\n"
            "این پیش‌تنظیم هنوز base_url / model / api_key ندارد، پس اتصال واقعی "
            "امکان‌پذیر نیست. ابتدا فیلدها را در ویرایش کامل پر کنید، سپس تست بگیرید.\n"
            "این صرفاً یک یادآوری است و مشکلی در ساخت پیش‌تنظیم نیست."
        )
    buttons = [
        [
            InlineKeyboardButton("🔄 تغییر وضعیت", callback_data="admin:ai_preset:create:toggle_enable"),
        ],
        [
            InlineKeyboardButton("✏️ ادامه ویرایش کامل", callback_data=f"admin:ai_preset:full_edit:{_preset_ref(name)}"),
        ],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_presets")],
    ]
    await _edit_or_send(update, context, body, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


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
        await update.callback_query.edit_message_text(
            "🔢 <b>عدد اولویت دستی</b> را وارد کنید (عدد کمتر = اولویت بیشتر):",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_awaiting_inline_keyboard(),
        )
    else:
        await notify_callback(update.callback_query, "انتخاب نامعتبر", intent=CallbackNoticeIntent.IMPORTANT_ERROR)


async def _handle_create_priority_manual(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Apply a manually-entered priority number (R14)."""
    state = context.user_data.setdefault("preset_create", {})
    try:
        rank = int(text.strip())
    except ValueError:
        context.user_data["awaiting"] = f"ai_preset_create_priority:{state.get('name', '')}"
        await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید.", reply_markup=admin_awaiting_inline_keyboard())
        return
    max_rank = _normal_chain_count()
    if rank < 0:
        context.user_data["awaiting"] = f"ai_preset_create_priority:{state.get('name', '')}"
        await update.message.reply_text("عدد اولویت نمی‌تواند منفی باشد.", reply_markup=admin_awaiting_inline_keyboard())
        return
    if rank > max_rank:
        # Clamp to the lowest slot so a value beyond the current chain size is
        # simply appended last instead of causing a broken ValueError mid-flow.
        rank = max_rank
        await update.message.reply_text(
            f"عدد واردشده از جایگاه‌های قابل استفاده بیشتر بود؛ پیش‌تنظیم در آخرین جایگاه (رتبه {max_rank}) قرار می‌گیرد."
        )
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
        await _edit_or_send(
            update, context,
            "⚠️ هیچ پیش‌تنظیم فعالی برای تست اتصال وجود ندارد.\n"
            "اول یک پیش‌تنظیم را فعال کنید (یا در پنل AI یک پیش‌تنظیم جدید بسازید).",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ بازگشت به تنظیمات AI", callback_data="admin:ai_settings")]
            ]),
        )
        return
    result = await asyncio.to_thread(
        ai.test_connection,
        base_url=active.get("base_url", ""),
        api_key=db.resolve_preset_key(active),
        model=active.get("model", ""),
        timeout=active.get("timeout_seconds", 30.0),
    )

    if result["success"]:
        text = (
            f"✅ <b>اتصال موفق</b>\n"
            f"Latency: {result['latency_ms']} ms\n"
            f"Model: {html_escape(str(result.get('model', '')))}\n"
            f"Tokens: {html_escape(str(result.get('usage', '')))}"
        )
    else:
        text = (
            f"❌ <b>خطا در اتصال</b>\n"
            f"Error: {html_escape(str(result.get('error_class', '')))}: {html_escape(str(result.get('error_message', '')))}\n"
            f"Latency: {result['latency_ms']} ms"
        )

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 تست مجدد", callback_data="admin:ai_test_connection")],
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
        ])
    )


# ======== Custom Test Wizard ========

async def _start_custom_test_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the custom test wizard."""
    context.user_data["custom_test_state"] = {"step": "prompt"}
    context.user_data["awaiting"] = "ai_custom_test_prompt"

    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی کارت</b>\n\n"
        "مرحله ۱/۵: پرامپت سیستم (یا متن تست) را وارد کنید:\n"
        "<i>مثال: یک کارت واژگان برای سطح مبتدی بساز</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_awaiting_inline_keyboard()
    )


async def _custom_test_step_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("custom_test_state", {})
    state["step"] = "lang"
    context.user_data["custom_test_state"] = state
    context.user_data.pop("awaiting", None)

    buttons = [
        [InlineKeyboardButton(opt.name_fa, callback_data=f"admin:ai_custom_test:lang:{opt.code}")]
        for opt in LANGUAGES.values()
    ]
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - مرحله ۲/۵</b>\n\n"
        "زبان مقصد را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _custom_test_step_goal(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    state = context.user_data.get("custom_test_state", {})
    state["lang"] = lang
    state["step"] = "goal"
    context.user_data["custom_test_state"] = state

    buttons = [
        [InlineKeyboardButton(opt.name_fa, callback_data=f"admin:ai_custom_test:goal:{opt.code}")]
        for opt in GOALS.values()
    ]
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - مرحله ۳/۵</b>\n\n"
        "هدف یادگیری را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _custom_test_step_level(update: Update, context: ContextTypes.DEFAULT_TYPE, goal: str):
    state = context.user_data.get("custom_test_state", {})
    state["goal"] = goal
    state["step"] = "level"
    context.user_data["custom_test_state"] = state

    buttons = [
        [InlineKeyboardButton(f"{opt.name_fa} ({opt.cefr})", callback_data=f"admin:ai_custom_test:level:{opt.code}")]
        for opt in LEVELS.values()
    ]
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - مرحله ۴/۵</b>\n\n"
        "سطح زبان را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _custom_test_step_target(update: Update, context: ContextTypes.DEFAULT_TYPE, level: str):
    state = context.user_data.get("custom_test_state", {})
    state["level"] = level
    state["step"] = "target"
    context.user_data["custom_test_state"] = state

    try:
        active_preset = db.get_active_preset()
    except db.NoActivePresetError:
        await _edit_or_send(
            update, context,
            "⚠️ هیچ پیش‌تنظیم فعالی برای تست «جدید» وجود ندارد.\n"
            "اول یک پیش‌تنظیم را فعال کنید یا فقط گزینه «پیش‌تنظیم کاندیدا» را انتخاب کنید.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔸 پیش‌تنظیم کاندیدا", callback_data="admin:ai_custom_test:target:candidate")],
                [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
            ]),
        )
        return
    buttons = [
        [InlineKeyboardButton("🔹 پیکربندی فعلی", callback_data="admin:ai_custom_test:target:current")],
        [InlineKeyboardButton("🔸 پیش‌تنظیم کاندیدا", callback_data="admin:ai_custom_test:target:candidate")],
        [InlineKeyboardButton("⚖️ مقایسه A/B", callback_data="admin:ai_custom_test:target:ab")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
    ]
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - مرحله ۵/۵</b>\n\n"
        "هدف تست را انتخاب کنید:\n"
        f"- فعلی: {html_escape(str(active_preset.get('name', 'gapgpt')))}\n"
        f"- کاندیدا: پیش‌تنظیم دیگری را انتخاب کنید",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _run_custom_test(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str):
    """Execute the custom test."""
    state = context.user_data.get("custom_test_state", {})
    prompt = state.get("prompt", "یک کارت واژگان بساز")
    lang = state.get("lang", "en")
    goal = state.get("goal", "general")
    level = state.get("level", "beginner")

    await notify_callback(update.callback_query, "در حال اجرای تست...", intent=CallbackNoticeIntent.INFO)

    system_prompt = prompts.daily_batch_system_prompt(lang, goal, level, compact=False)

    results = []

    if target in ("current", "ab"):
        try:
            active_preset = db.get_active_preset()
        except db.NoActivePresetError:
            await _edit_or_send(
                update, context,
                "⚠️ هیچ پیش‌تنظیم فعالی برای تست «پیکربندی فعلی» وجود ندارد.\n"
                "ابتدا یک پیش‌تنظیم را فعال کنید.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
                ]),
            )
            return
        result = await asyncio.to_thread(
            ai.custom_test_card,
            system_prompt=system_prompt,
            user_prompt=prompt,
            lang=lang,
            goal=goal,
            level=level,
            preset=active_preset,
        )
        results.append(("Current Config", result))

    if target in ("candidate", "ab"):
        candidate_name = state.get("candidate_preset", "gapgpt")
        candidate = db.get_preset(candidate_name) or db.get_preset("gapgpt") or {}
        result = await asyncio.to_thread(
            ai.custom_test_card,
            system_prompt=system_prompt,
            user_prompt=prompt,
            lang=lang,
            goal=goal,
            level=level,
            preset=candidate,
        )
        results.append((f"Candidate ({candidate_name})", result))

    # Format results
    lines = ["🧪 <b>نتیجه تست سفارشی</b>\n"]
    for label, card in results:
        lines.append(f"<b>{html_escape(label)}</b>")
        lines.append(f"Word: {html_escape(str(card.get('word', '?')))}")
        lines.append(f"Meaning: {html_escape(str(card.get('fa_meaning', '?')))}")
        lines.append(f"Examples: {html_escape(str(card.get('examples', [])))}")
        lines.append("")

    lines.append("🧪 این تست روی پیکربندی پیش‌تنظیم اجرا شد، نه مسیر تولید.")

    await _edit_or_send(
        update, context,
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 تست مجدد", callback_data="admin:ai_custom_test")],
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
        ])
    )
    context.user_data.pop("custom_test_state", None)


async def _handle_custom_test_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Route wizard callbacks."""
    if action == "ai_custom_test:lang":
        pass
    elif action.startswith("ai_custom_test:lang:"):
        await _custom_test_step_goal(update, context, action.split(":")[2])
    elif action.startswith("ai_custom_test:goal:"):
        await _custom_test_step_level(update, context, action.split(":")[2])
    elif action.startswith("ai_custom_test:level:"):
        await _custom_test_step_target(update, context, action.split(":")[2])
    elif action.startswith("ai_custom_test:target:"):
        target = action.split(":")[2]
        if target in ("candidate", "ab"):
            state = context.user_data.get("custom_test_state", {})
            state["target"] = target
            context.user_data["custom_test_state"] = state
            await _custom_test_step_preset(update, context)
        else:
            await _run_custom_test(update, context, target)
    elif action.startswith("ai_custom_test:preset:"):
        state = context.user_data.get("custom_test_state", {})
        state["candidate_preset"] = _resolve_preset_ref(action.split(":")[2])
        context.user_data["custom_test_state"] = state
        await _run_custom_test(update, context, state.get("target", "candidate"))


async def _custom_test_step_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show preset picker for custom test."""
    from services.utils.callback_codec import preset_token
    presets = db.get_presets()
    buttons = [
        [InlineKeyboardButton(p["name"], callback_data=f"admin:ai_custom_test:preset:{preset_token(p['name'])}")]
        for p in presets
    ]
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_custom_test")])
    await _edit_or_send(
        update, context,
        "🧪 <b>تست سفارشی - انتخاب پیش‌تنظیم</b>\n\n"
        "پیش‌تنظیم کاندیدا را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def _show_ai_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show fallback configuration panel."""
    status = db.get_fallback_status()
    if status["fallback_active"]:
        active = db.get_preset(str(status["fallback_preset"])) or {}
        if bool(active.get("is_emergency", 0)):
            status_label = "🎯 🛡️ Emergency ACTIVE"
        else:
            status_label = "🎯 Fallback ACTIVE"
    else:
        status_label = "🎯 Primary Active"
    text = (
        "🔄 <b>مدیریت پیش‌تنظیم پشتیبان (Fallback)</b>\n\n"
        f"Status: {status_label}\n"
        f"Primary: {html_escape(str(status['primary_preset']))}\n"
        f"Fallback: {html_escape(str(status['fallback_preset']))}\n"
        f"Consecutive Failures: {status['consecutive_failures']}\n"
    )
    if status["fallback_active"] and status["fallback_since"]:
        text += f"Fallback Since: {html_escape(str(status['fallback_since'][:19]))}\n"

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=ai_fallback_keyboard(
            status["primary_preset"],
            status["fallback_preset"],
            status["fallback_preset"] if status["fallback_active"] else status["primary_preset"]
        )
    )


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
    text = (
        "❓ <b>راهنمای پریست‌های AI</b>\n\n"
        "هر پریست یک تنظیمات کامل برای اتصال به یک سرویس‌دهنده AI است.\n\n"
        "<b>فیلدهای اصلی:</b>\n"
        "• name: نام یکتای پریست (فقط حروف انگلیسی، اعداد، زیرخط)\n"
        "• api_key: کلید API (مقدار ثابت؛ به‌صورت رمزنگاری‌شده ذخیره می‌شود)\n"
        "• base_url: آدرس سرور (سازگار با OpenAI)\n"
        "• model: نام دقیق مدل\n\n"
        "<b>محدودیت‌ها:</b>\n"
        "• max_concurrency: تعداد درخواست هم‌زمان\n"
        "• max_rpm: سقف درخواست در دقیقه (0 = بی‌محدودیت)\n"
        "• max_tpm: سقف توکن در دقیقه (0 = بی‌محدودیت)\n"
        "• max_daily_req: سقف درخواست روزانه (0 = بی‌محدودیت)\n\n"
        "<b>زنجیره فال‌بک:</b>\n"
        "پریست‌ها بر اساس priority (کم→زیاد) و is_emergency مرتب می‌شوند.\n"
        "پریست‌های عادی اول امتحان می‌شوند، سپس اضطراری.\n"
        "in_fallback_chain=0 یعنی پریست در زنجیره شرکت نمی‌کند.\n\n"
        "<b>گروه‌بندی:</b>\n"
        "پریست‌هایی که کلید API مشترک دارند در یک گروه قرار می‌گیرند.\n"
        "group_label برای نام‌گذاری گروه‌ها استفاده می‌شود."
    )
    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")]
        ])
    )


async def _show_help_fallback_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help for fallback chain."""
    text = (
        "❓ <b>راهنمای زنجیره فال‌بک</b>\n\n"
        "ترتیب زنجیره:\n"
        "۱. پریست‌های عادی (is_emergency=0) بر اساس priority (از کم به زیاد)\n"
        "۲. پریست‌های اضطراری (is_emergency=1) بر اساس priority\n\n"
        "پریست‌های با in_fallback_chain=0 در زنجیره نمایش داده نمی‌شوند.\n\n"
        "<b>دکمه‌ها:</b>\n"
        "• ⬆/⬇: جابه‌جایی دستی (تغییر priority)\n"
        "• 🟢/⚫: فعال/غیرفعال کردن پریست\n"
        "• 🛡️: تبدیل به پریست اضطراری\n"
        "• 🎯: پرش به رتبه دلخواه در گروه\n\n"
        "پریست اضطراری همیشه بعد از همه پریست‌های عادی امتحان می‌شود."
    )
    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ بازگشت به زنجیره", callback_data="admin:fallback_chain")]
        ])
    )


async def _show_fallback_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show and manage the fallback chain order."""
    chain = db.get_fallback_chain_presets()
    text = (
        "⛓️ <b>زنجیره فال‌بک</b>\n\n"
        "ترتیب: پریست‌های عادی (is_emergency=0) بر اساس priority (از کم به زیاد)، "
        "سپس پریست‌های اضطراری (is_emergency=1).\n"
        "پریست‌های با in_fallback_chain=0 در این زنجیره نمایش داده نمی‌شوند.\n\n"
    )
    for i, preset in enumerate(chain):
        name = preset.get("name", "?")
        is_emergency = preset.get("is_emergency", 0)
        status = "🛡️ اضطراری" if is_emergency else "🟢 فعال"
        text += f"{i+1}. <b>{html_escape(name)}</b> — {status}\n"

    await _edit_or_send(
        update, context, text,
        parse_mode=ParseMode.HTML,
        reply_markup=fallback_chain_keyboard(chain)
    )


USAGE_PAGE_SIZE = 5


def _usage_rows() -> list[tuple[str, str, str]]:
    """Return (status_icon, name, detail) rows ordered by name."""
    rows = []
    for p in db.get_presets():
        name = p["name"]
        req_count, token_count = db.get_hourly_usage(name, hours_back=24)
        max_daily = p.get("max_daily_req", 0)
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
    lines = [f"📊 <b>مصرف ۲۴ ساعته پریست‌ها</b> (صفحه {page + 1}/{total_pages})\n"]
    for status, name, detail in slice_rows:
        lines.append(f"{status} <b>{html_escape(name)}</b>: {detail}")
    return "\n".join(lines), _usage_page_keyboard(page, total_pages)


async def _show_fallback_usage_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """R7: Show daily consumption for all presets, paginated."""
    text, keyboard = _render_usage_page(0)
    await _edit_or_send(update, context, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _show_usage_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    """R7: show a specific usage page."""
    text, keyboard = _render_usage_page(page)
    await _edit_or_send(update, context, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _handle_fallback_rank(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Start awaiting flow for rank jump input."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    group_is_emergency = bool(preset.get("is_emergency", 0))
    group_label = "اضطراری" if group_is_emergency else "عادی"
    chain = db.get_fallback_chain_presets()
    group_chain = [p for p in chain if bool(p.get("is_emergency", 0)) == group_is_emergency]
    max_rank = len(group_chain)

    context.user_data["awaiting"] = f"ai_fallback_rank:{preset_name}"
    await _edit_or_send(
        update, context,
        f"🎯 رتبه جدید در گروه «{group_label}» را وارد کنید (۱ تا {max_rank}):",
        reply_markup=admin_awaiting_inline_keyboard(),
    )


async def handle_ai_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
) -> None:
    """Route AI/preset/fallback admin callback sub-actions to their handlers.

    Mirrors the inline ``admin:ai_*`` / ``admin:fallback*`` / ``admin:help:*``
    branches that previously lived in the admin monolith's ``_handle_admin_callback``.
    The owner check is performed by the caller. Behavior and action strings are unchanged.
    """
    if action == "ai_settings":
        await _show_ai_settings(update, context)
    elif action == "ai_presets":
        await _show_ai_presets(update, context)
    elif action.startswith("ai_preset:view:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _show_ai_preset_view(update, context, preset_name)
    elif action.startswith("ai_preset:activate:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _activate_ai_preset(update, context, preset_name)
    elif action.startswith("ai_preset:edit:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _edit_ai_preset(update, context, preset_name)
    elif action.startswith("ai_preset:edit_field:"):
        # format: ai_preset:edit_field:preset_ref:field_alias
        parts = action.split(":", 3)
        if len(parts) == 4:
            preset_name = _resolve_preset_ref(parts[2])
            field_name = resolve_field_alias(parts[3])
            await _edit_ai_preset_field(update, context, preset_name, field_name)
    elif action.startswith("ai_preset:full_edit:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _start_full_edit_wizard(update, context, preset_name)
    elif action.startswith("ai_preset:full_edit_next:"):
        parts = action.split(":", 3)
        if len(parts) >= 3:
            preset_name = _resolve_preset_ref(parts[2])
            await _handle_full_edit_next(update, context, preset_name)
    elif action.startswith("ai_preset:full_edit_back:"):
        parts = action.split(":", 3)
        if len(parts) >= 3:
            preset_name = _resolve_preset_ref(parts[2])
            await _handle_full_edit_back(update, context, preset_name)
    elif action.startswith("ai_preset:full_edit_skip:"):
        parts = action.split(":", 3)
        if len(parts) >= 3:
            preset_name = _resolve_preset_ref(parts[2])
            await _handle_full_edit_skip(update, context, preset_name)
    elif action.startswith("ai_preset:full_edit_cancel:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _handle_full_edit_cancel(update, context, preset_name)
    elif action.startswith("ai_preset:full_edit_pick_group:"):
        # format: ai_preset:full_edit_pick_group:preset_ref:label_ref
        parts = action.split(":", 3)
        if len(parts) == 4:
            preset_name = _resolve_preset_ref(parts[2])
            label = _resolve_label_ref(parts[3])
            await _handle_full_edit_pick_group(update, context, preset_name, label)
    elif action.startswith("ai_preset:full_edit_save:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _handle_full_edit_save(update, context, preset_name)
    elif action.startswith("ai_preset:save:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _confirm_save_preset(update, context, preset_name)
    elif action.startswith("ai_preset:confirm_save_yes:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _save_ai_preset(update, context, preset_name)
    elif action.startswith("ai_preset:confirm_save_no:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _edit_ai_preset(update, context, preset_name)
    elif action.startswith("ai_preset:discard_all:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _discard_all_preset_changes(update, context, preset_name)
    elif action.startswith("ai_preset:detach_group:"):
        preset_name = resolve_preset_token(action.split(":", 2)[2])
        if not preset_name:
            await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        else:
            await _detach_ai_preset_group(update, context, preset_name)
    elif action.startswith("ai_preset:delete:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _delete_ai_preset(update, context, preset_name)
    elif action.startswith("ai_preset:confirm_delete_yes:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _confirm_delete_yes(update, context, preset_name)
    elif action.startswith("ai_preset:confirm_delete_no:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _confirm_delete_no(update, context, preset_name)
    elif action.startswith("ai_preset:duplicate:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _duplicate_ai_preset(update, context, preset_name)
    elif action == "ai_preset:add":
        await _add_ai_preset(update, context)
    elif action.startswith("ai_preset:create:priority:"):
        choice = action.split(":", 3)[3]
        await _handle_create_priority_choice(update, context, choice)
    elif action.startswith("ai_preset:create:status:"):
        choice = action.split(":", 3)[3]
        await _handle_create_status_choice(update, context, choice)
    elif action == "ai_preset:create:test":
        await _handle_create_test(update, context)
    elif action == "ai_preset:create:toggle_enable":
        await _handle_create_toggle_enable(update, context)
    elif action.startswith("ai_preset:page:"):
        page = int(action.split(":", 2)[2])
        await _show_linear_presets(update, context, page)
    elif action.startswith("ai_preset:view_mode:"):
        mode = action.split(":", 2)[2]
        await _toggle_preset_view_mode(update, context)
    elif action.startswith("ai_preset:group:"):
        key_hash = action.split(":", 2)[2]
        await _handle_group_view(update, context, key_hash)
    elif action.startswith("ai_preset:group_batch_key:"):
        key_hash = action.split(":", 2)[2]
        await _handle_group_batch_key(update, context, key_hash)
    elif action.startswith("ai_preset:group_set_label:"):
        key_hash = action.split(":", 2)[2]
        await _handle_group_set_label(update, context, key_hash)
    elif action == "ai_preset:group_manager":
        await _show_group_manager(update, context)
    elif action.startswith("ai_preset:group_manager_rename:"):
        parts = action.split(":", 2)
        if len(parts) == 3:
            label = _resolve_label_ref(parts[2])
            if label is None:
                await notify_callback(update.callback_query, "برچسب گروه یافت نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            else:
                await _handle_group_manager_rename(update, context, label)
    elif action.startswith("ai_preset:group_manager_clear:"):
        parts = action.split(":", 2)
        if len(parts) == 3:
            label = _resolve_label_ref(parts[2])
            if label is None:
                await notify_callback(update.callback_query, "برچسب گروه یافت نشد.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            else:
                await _handle_group_manager_clear(update, context, label)
    elif action == "ai_test_connection":
        await _test_ai_connection(update, context)
    elif action == "ai_custom_test":
        await _start_custom_test_wizard(update, context)
    elif action.startswith("ai_custom_test:"):
        await _handle_custom_test_wizard(update, context, action)
    elif action == "ai_fallback":
        await _show_ai_fallback(update, context)
    elif action.startswith("ai_fallback:"):
        await _handle_ai_fallback(update, context, action)
    elif action == "fallback_chain":
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:move_up:"):
        name = _resolve_preset_ref(action.split(":", 2)[2])
        chain = db.get_enabled_presets_ordered()
        idx = next((i for i, p in enumerate(chain) if p["name"] == name), None)
        if idx and idx > 0:
            above = chain[idx - 1]
            tmp = above["priority"]
            db.set_preset_priority(above["name"], chain[idx]["priority"])
            db.set_preset_priority(name, tmp)
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:move_down:"):
        name = _resolve_preset_ref(action.split(":", 2)[2])
        chain = db.get_enabled_presets_ordered()
        idx = next((i for i, p in enumerate(chain) if p["name"] == name), None)
        if idx is not None and idx < len(chain) - 1:
            below = chain[idx + 1]
            tmp = below["priority"]
            db.set_preset_priority(below["name"], chain[idx]["priority"])
            db.set_preset_priority(name, tmp)
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:toggle:"):
        name = _resolve_preset_ref(action.split(":", 2)[2])
        preset = db.get_preset(name)
        if preset:
            db.set_preset_enabled(name, not preset.get("enabled", 1))
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:set_emergency:"):
        name = _resolve_preset_ref(action.split(":", 2)[2])
        chain = db.get_enabled_presets_ordered()
        for p in chain:
            db.set_preset_emergency(p["name"], p["name"] == name)
        await _show_fallback_chain(update, context)
    elif action.startswith("fallback:rank:"):
        name = _resolve_preset_ref(action.split(":", 2)[2])
        await _handle_fallback_rank(update, context, name)
    elif action == "fallback:usage_details":
        await _show_fallback_usage_details(update, context)
    elif action.startswith("fallback:usage_page:"):
        parts = action.split(":")
        try:
            page = int(parts[2])
        except (ValueError, IndexError):
            page = 0
        await _show_usage_page(update, context, page)
    elif action == "help:presets":
        await _show_help_presets(update, context)
    elif action == "help:fallback_chain":
        await _show_help_fallback_chain(update, context)


async def _handle_ai_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    awaiting: str,
    text: str,
) -> None:
    """Route AI/preset text-input awaiting states to their handlers.

    Mirrors the inline blocks that previously lived in the admin monolith's
    ``_handle_admin_text_input``. Behavior and awaiting strings are unchanged.
    """
    if awaiting.startswith("admin_group_batch_key:"):
        key_hash = awaiting.split(":", 1)[1]
        groups = _detect_key_groups()
        target = next((g for g in groups if g["key_hash"] == key_hash), None)
        if target:
            db.set_preset_api_key_batch(target["names"], text.strip())
        context.user_data.pop("awaiting", None)
        await update.message.reply_text("✅ کلید API برای همه اعضای گروه به‌روز شد.")
        await _show_grouped_presets(update, context)
        return

    if awaiting.startswith("admin_group_set_label:"):
        key_hash = awaiting.split(":", 1)[1]
        new_label = text.strip()
        if not new_label or len(new_label) > MAX_GROUP_LABEL_LEN:
            context.user_data["awaiting"] = awaiting
            await update.message.reply_text(
                f"برچسب نامعتبر. برچسب باید بین ۱ تا {MAX_GROUP_LABEL_LEN} کاراکتر باشد.",
                reply_markup=admin_awaiting_inline_keyboard(),
            )
            return
        groups = _detect_key_groups()
        target = next((g for g in groups if g["key_hash"] == key_hash), None)
        if target:
            db.set_preset_group_label_batch(target["names"], new_label)
        context.user_data.pop("awaiting", None)
        await update.message.reply_text("✅ برچسب گروه برای همه اعضا تنظیم شد.")
        await _show_grouped_presets(update, context)
        return

    if awaiting.startswith("admin_group_manager_rename:"):
        old_label = unquote(awaiting.split(":", 1)[1])
        new_label = text.strip()
        if new_label:
            if len(new_label) > MAX_GROUP_LABEL_LEN:
                context.user_data["awaiting"] = awaiting
                await update.message.reply_text(
                    f"برچسب نامعتبر. برچسب باید حداکثر {MAX_GROUP_LABEL_LEN} کاراکتر باشد.",
                    reply_markup=admin_awaiting_inline_keyboard(),
                )
                return
            db.rename_group_label(old_label, new_label)
            context.user_data.pop("awaiting", None)
            await update.message.reply_text(f"✅ برچسب «{old_label}» به «{new_label}» تغییر نام یافت.")
        else:
            context.user_data.pop("awaiting", None)
            await update.message.reply_text("انصراف از تغییر نام.")
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
            await update.message.reply_text("لطفاً یک عدد معتبر وارد کنید.")
            return
        preset = db.get_preset(preset_name)
        if not preset:
            await update.message.reply_text("پیش‌تنظیم یافت نشد")
            return
        group_is_emergency = bool(preset.get("is_emergency", 0))
        chain = db.get_fallback_chain_presets()
        count = len(chain)
        try:
            db.reindex_preset_priority(preset_name, target_rank, group_is_emergency)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return
        context.user_data.pop("awaiting", None)
        await update.message.reply_text(f"✅ رتبه {preset_name} به {target_rank} تغییر یافت.")
        await _show_fallback_chain(update, context)
        return
