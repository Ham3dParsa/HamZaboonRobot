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
import logging
import re
from urllib.parse import quote, unquote

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from handlers.flows import mark_awaiting_consumed

from services import db
from services.utils.callback_codec import (
    resolve_field_alias,
    resolve_label_token,
    resolve_preset_token,
)
from services.ai import ai
from services.ai import preset_fields, prompts
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.confirm_summary import FieldDiff, build_confirm_message, render_diffs
from services.utils.helpers import _clear_awaiting_prompt, _edit_or_send, _store_awaiting_msg
from services.utils.formatting import to_persian_digits
from services.send_pretty import Backend, Message, RawFormat, bold, code, italic, plain, say, table
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
    "reasoning_effort": "میزان تلاش استدلال: none (حذف از درخواست؛ برای مدل‌های بدون تفکر)، minimal (کمترین توکن، پیشنهادی برای Spark)، low، medium، high، xhigh. فقط وقتی none نیست ارسال می‌شود. Spark 1.3 همیشه فکر می‌کند و none با 400 خطا می‌دهد؛ از minimal یا low استفاده کنید.",
}

# Canonical all-English short label map. Single source of truth for the
# single-field edit prompt, the confirmation message, and the full-edit wizard.
FIELD_LABELS = {
    "base_url": "Base URL",
    "model": "Model",
    "api_key": "API Key",
    "daily_batch_size": "Batch Size",
    "max_concurrency": "Concurrency",
    "max_rpm": "RPM Limit",
    "max_tpm": "Max TPM",
    "max_daily_req": "Max Daily Requests",
    "timeout_seconds": "Timeout (s)",
    "temperature": "Temperature",
    "max_output_tokens": "Max Output Tokens",
    "is_emergency": "Is Emergency",
    "name": "Preset Name",
    "priority": "Priority",
    "input_cost_per_million": "Input Cost $/1M",
    "output_cost_per_million": "Output Cost $/1M",
    "in_fallback_chain": "In Fallback Chain",
    "group_label": "Group Label",
    "reasoning_effort": "Reasoning Effort",
}


async def _show_ai_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main AI settings panel."""
    try:
        active_preset = db.get_active_preset()
    except db.NoActivePresetError:
        msg = Message()
        msg.add_line(plain("🤖 "), bold("تنظیمات هوش مصنوعی"))
        msg.add_line()
        msg.add_line(plain("⚠️ هیچ پیش‌تنظیم فعالی وجود ندارد."))
        msg.add_line(plain("برای استفاده از هوش مصنوعی، از بخش «پیش‌تنظیم‌ها» یک پیش‌تنظیم بسازید و فعال کنید."))
        msg.set_keyboard(ai_settings_keyboard())
        await say(update, context, msg, backend=Backend.HTML)
        return
    fallback_status = db.get_fallback_status()

    msg = Message()
    msg.add_line(plain("🤖 "), bold("تنظیمات هوش مصنوعی"))
    msg.add_line()
    msg.add_line(bold("پیش‌تنظیم فعال:"), plain(" " + str(active_preset.get("name", "—"))))
    msg.add_line(bold("مدل:"), plain(" " + str(active_preset.get("model", "—"))))
    msg.add_line(bold("Base URL:"), plain(" " + str(active_preset.get("base_url", "—"))))
    msg.add_line(bold("Batch Size:"), plain(" " + str(preset_fields.resolve(active_preset, "daily_batch_size"))))
    msg.add_line(bold("Concurrency:"), plain(" " + str(preset_fields.resolve(active_preset, "max_concurrency"))))
    msg.add_line(bold("RPM Limit:"), plain(" " + str(preset_fields.resolve(active_preset, "max_rpm"))))
    msg.add_line()

    if fallback_status.get("fallback_active"):
        msg.add_line(
            plain("⚠️ "),
            bold("Fallback ACTIVE"),
            plain(" since "),
            plain(str(fallback_status.get("fallback_since", "?"))),
        )
        msg.add_line(
            plain("Primary: "),
            plain(str(fallback_status.get("primary_preset", "—"))),
            plain(" → Fallback: "),
            plain(str(fallback_status.get("fallback_preset", "—"))),
        )
        msg.add_line()

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
        msg.add_line(plain("📇 "), bold("آخرین درخواست‌ها:"))
        msg.add_line(plain("  Daily: "), plain(str(tracking.get("daily_batch", "—"))))
        msg.add_line(plain("  Grammar: "), plain(str(tracking.get("grammar_tip", "—"))))
        msg.add_line(plain("  Word: "), plain(str(tracking.get("custom_word", "—"))))
    except Exception:
        pass

    msg.set_keyboard(ai_settings_keyboard())
    await say(update, context, msg, backend=Backend.HTML)


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


def _preset_brief_spans(preset: dict, active_name: str) -> list:
    """Return the span list for one brief preset line (single source of truth).

    Pure synchronous renderer (no awaits). Emoji per the UI/UX dictionary:
    🟢/⚫ toggle reflects the enabled state, and the ``[tags]`` suffix marks
    🎯 active preset, 🛡️ emergency tier, and custom. Every list/chain site
    consumes these spans so each renders identically (R6/R8). 🔢 marks the
    rank-setting context (pick/enter a target priority rank); it is distinct
    from 🎯, which means the live/active routing target only.
    """
    name = preset.get("name", "?")
    toggle = "🟢" if preset.get("enabled", 1) else "⚫"
    tags = []
    if name == active_name:
        tags.append("🎯")
    if preset.get("is_emergency"):
        tags.append("🛡️")
    spans = [plain(f"{toggle} "), bold(str(name))]
    if tags:
        spans.append(plain(f" [{' '.join(tags)}]"))
    return spans


def _render_preset_brief(preset: dict, active_name: str) -> str:
    """Render one brief, HTML-escaped preset line (R6/R8) from the shared spans.

    Builds the HTML string from ``_preset_brief_spans`` so the linear and
    chain sites share one source of truth for the brief render.
    """
    msg = Message()
    msg.add_line(*_preset_brief_spans(preset, active_name))
    return msg.render(Backend.HTML)


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

    msg = Message()
    msg.add_line(plain("📋 "), bold("لیست پیش‌تنظیم‌ها"))
    msg.add_line()
    msg.add_line()
    for p in page_presets:
        msg.add_line(*_preset_brief_spans(p, active_name))
        msg.add_line(plain("   Model: "), plain(str(p.get("model", "—"))))
        msg.add_line(plain("   URL: "), plain(str(p.get("base_url", "—"))))
        msg.add_line(
            plain("   Batch: "),
            plain(str(preset_fields.resolve(p, "daily_batch_size"))),
            plain(" | Concurrency: "),
            plain(str(preset_fields.resolve(p, "max_concurrency"))),
            plain(" | RPM: "),
            plain(str(preset_fields.resolve(p, "max_rpm"))),
        )
        msg.add_line()
    if total_pages > 1:
        msg.add_line()
        msg.add_line(plain("📄 صفحه "), plain(str(page + 1)), plain(" از "), plain(str(total_pages)))

    msg.set_keyboard(
        ai_presets_list_keyboard(
            all_presets, active_name,
            page=page, total_pages=total_pages,
            view_mode="linear",
        )
    )
    await say(update, context, msg, backend=Backend.HTML)


async def _show_grouped_presets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show presets grouped by API key."""
    groups = _detect_key_groups()
    active_name = db.get_active_preset_name()

    msg = Message()
    if not groups:
        msg.add_line(plain("هیچ گروهی یافت نشد."))
    else:
        msg.add_line(plain("📁 "), bold("پیش‌تنظیم‌ها بر اساس کلید API"))
        for g in groups:
            label = g.get("label") or g.get("masked_key", "—")
            msg.add_line()
            msg.add_line(
                plain("📁 "),
                bold(str(label)),
                plain(f" ({g['count']} preset)"),
            )
            msg.add_line(plain("   🔑 "), plain(str(g.get("masked_key", "—"))))

    msg.set_keyboard(
        ai_presets_list_keyboard(
            [], active_name,
            view_mode="grouped",
            groups=groups,
        )
    )
    await say(update, context, msg, backend=Backend.HTML)


async def _show_ai_preset_view(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """View/edit a single preset."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    active_name = db.get_active_preset_name()
    is_active = preset_name == active_name

    masked_key = preset_fields.display_value(preset, "api_key")

    from services.db import get_preset_cost as _get_preset_cost
    cost = _get_preset_cost(preset_name)
    input_cost_str = f"{cost['input_cost_per_million']}" if cost['input_cost_per_million'] is not None else "— (global)"
    output_cost_str = f"{cost['output_cost_per_million']}" if cost['output_cost_per_million'] is not None else "— (global)"

    msg = Message()
    msg.add_line(plain("📋 "), bold("پیش‌تنظیم: " + str(preset_name)))
    msg.add_line()
    msg.add_line(plain("Model: "), plain(str(preset.get("model", "—"))))
    msg.add_line(plain("Base URL: "), plain(str(preset.get("base_url", "—"))))
    msg.add_line(plain("API Key: "), plain(masked_key))
    msg.add_line(plain("Daily Batch Size: "), plain(str(preset_fields.resolve(preset, "daily_batch_size"))))
    msg.add_line(plain("Max Concurrency: "), plain(str(preset_fields.resolve(preset, "max_concurrency"))))
    msg.add_line(plain("Max RPM: "), plain(str(preset_fields.resolve(preset, "max_rpm"))))
    msg.add_line(plain("Timeout: "), plain(str(preset_fields.resolve(preset, "timeout_seconds"))), plain("s"))
    msg.add_line(plain("Temperature: "), plain(str(preset_fields.resolve(preset, "temperature"))))
    msg.add_line(plain("Max Output Tokens: "), plain(str(preset_fields.resolve(preset, "max_output_tokens"))))
    msg.add_line(plain("Input Cost: "), plain(input_cost_str), plain(" $/1M"))
    msg.add_line(plain("Output Cost: "), plain(output_cost_str), plain(" $/1M"))

    msg.set_keyboard(ai_preset_view_keyboard(preset, active_name))
    await say(update, context, msg, backend=Backend.HTML)


async def _activate_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Activate a preset as primary."""
    log = logging.getLogger(__name__)
    preset = db.get_preset(preset_name)
    if not preset:
        log.warning("activate failed: preset not found %s", preset_name)
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        await _show_ai_preset_view(update, context, preset_name)
        return
    # If disabled, enable first so activation can succeed (new presets are created disabled)
    if not preset_fields.resolve(preset, "enabled"):
        try:
            db.set_preset_enabled(preset_name, True)
            log.info("auto-enabled preset %s for activation", preset_name)
        except Exception as exc:
            log.exception("auto-enable failed for %s: %s", preset_name, exc)
            await notify_callback(update.callback_query, "فعال‌سازی ممکن نیست: فعال کردن پیش‌تنظیم ناموفق بود", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
            await _show_ai_preset_view(update, context, preset_name)
            return
    try:
        success = db.activate_preset(preset_name)
    except Exception as exc:
        log.exception("activate_preset raised for %s", preset_name)
        await notify_callback(update.callback_query, f"خطا در فعال‌سازی: {type(exc).__name__}", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        await _show_ai_preset_view(update, context, preset_name)
        return
    if success:
        await notify_callback(update.callback_query, f"پیش‌تنظیم {preset_name} فعال شد", intent=CallbackNoticeIntent.SUCCESS)
    else:
        fresh = db.get_preset(preset_name)
        log.warning("activate_preset returned False for %s (enabled=%s)", preset_name, fresh.get("enabled") if fresh else None)
        await notify_callback(update.callback_query, "خطا در فعال‌سازی: پیش‌تنظیم فعال نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
    await _show_ai_preset_view(update, context, preset_name)


def _preset_edit_diffs(preset: dict, edits: dict) -> list[FieldDiff]:
    """Build dirty-field diffs in WIZARD_FIELDS order (single-field preset_edits flow).

    Old/new display strings come from the canonical
    ``preset_fields.display_value`` owner (D1): stored ``api_key`` resolved +
    masked (never plaintext), staged drafts override and are masked too.
    Empty values render as "—". Labels use the canonical
    FIELD_LABELS map. The per-field table block renders through the shared
    ``render_diffs`` seam (same bold label + vertical قبلی/جدید table as
    ``build_confirm_message``); the edit
    menu keeps its own chrome (title + picker prompt + pending header), so it
    consumes the shared FieldDiff list instead of the confirm-dialog message.
    """
    diffs: list[FieldDiff] = []
    ordered = [f for f in WIZARD_FIELDS if f in edits]
    ordered += [f for f in edits if f not in WIZARD_FIELDS]
    for field_name in ordered:
        old_str = preset_fields.display_value(preset, field_name)
        new_str = preset_fields.display_value(preset, field_name, edits[field_name])
        diffs.append(
            FieldDiff(
                label=FIELD_LABELS.get(field_name, field_name),
                old=old_str,
                new=new_str,
            )
        )
    return diffs


async def _edit_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Show field edit options for a preset."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    edits = context.user_data.get("preset_edits", {}).get(preset_name, {})
    diffs = _preset_edit_diffs(preset, edits)

    msg = Message()
    msg.add_line(plain("✏️ "), bold("ویرایش پیش‌تنظیم: " + str(preset_name)))
    msg.add_line(plain("انتخاب فیلد برای تغییر:"))
    if diffs:
        msg.add_line(plain(f"{to_persian_digits(len(diffs))} تغییر در انتظار — هنوز ذخیره نشده"))
        for line in render_diffs(diffs):
            msg.add_line(*line)

    await say(update, context, msg, backend=Backend.RICH, keyboard=ai_preset_edit_keyboard(preset_name, preset, edits))


async def _edit_ai_preset_field(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_name: str):
    """Prompt for new value of a field."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    context.user_data["awaiting"] = f"ai_preset_edit:{preset_name}:{field_name}"

    help_text = _FIELD_HELP.get(field_name, "")

    # D1: current value through the display owner — api_key renders masked
    # (never plaintext/ciphertext shape), empty renders "—".
    current_str = preset_fields.display_value(preset, field_name)

    msg = Message()
    msg.add_line(plain("✏️ "), bold(FIELD_LABELS.get(field_name, field_name)))
    msg.add_line(plain("مقدار فعلی: "), code(current_str))
    msg.add_line()
    msg.add_line(plain("مقدار جدید را ارسال کنید:"))
    if help_text:
        msg.add_line()
        msg.add_line(plain("💡 "), plain(help_text))

    await say(
        update, context, msg, backend=Backend.HTML,
        # awaiting_inline_keyboard() -> flow:back resumes the preset-edit menu
        # (preserves preset_edits); flow:cancel discards only this preset's
        # edits. This aligns with the field-edit error-retry prompts. Note: this
        # intentionally differs from admin_awaiting_inline_keyboard(), whose
        # admin:cancel wiped ALL preset_edits (contract R3, owner-approved).
        keyboard=awaiting_inline_keyboard()
    )


async def _handle_ai_preset_field_input(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_name: str, text: str):
    """Process field input for preset edit."""
    preset = db.get_preset(preset_name)
    if not preset:
        await say(update, context, "پیش‌تنظیم یافت نشد", raw=RawFormat.PLAIN, mode="send")
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
                await say(update, context, "این نام از قبل وجود دارد. نام دیگری انتخاب کنید.", raw=RawFormat.PLAIN, keyboard=awaiting_inline_keyboard(), mode="send")
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
        elif field_name == "priority":
            value = int(raw)
            if value < 0:
                raise ValueError
        elif field_name == "group_label":
            value = raw
            if not value or len(value) > MAX_GROUP_LABEL_LEN:
                raise ValueError
        elif field_name == "reasoning_effort":
            value = raw.strip().lower()
            if value not in ("none", "minimal", "low", "medium", "high", "xhigh"):
                raise ValueError
        else:
            value = raw
    except ValueError:
        context.user_data["awaiting"] = f"ai_preset_edit:{preset_name}:{field_name}"
        await say(update, context, "فرمت نامعتبر. لطفاً مقدار معتبر بفرستید.", raw=RawFormat.PLAIN, keyboard=awaiting_inline_keyboard(), mode="send")
        return

    # Store in-memory (per preset)
    edits = context.user_data.setdefault("preset_edits", {})
    edits.setdefault(preset_name, {})[field_name] = value

    # Auto-delete user message containing plaintext API key
    if field_name == "api_key":
        try:
            await update.message.delete()
        except Exception as exc:
            logging.getLogger(__name__).debug("delete api_key message failed: %s", exc)

    context.user_data.pop("awaiting", None)

    label = FIELD_LABELS.get(field_name, field_name)
    await notify_callback(
        update.callback_query,
        f"✅ {label} ثبت شد",
        intent=CallbackNoticeIntent.SUCCESS,
    )
    await _edit_ai_preset(update, context, preset_name)


WIZARD_FIELDS = [
    "name", "api_key", "base_url", "model",
    "max_concurrency", "max_rpm", "max_tpm", "daily_batch_size",
    "max_daily_req", "timeout_seconds", "temperature", "max_output_tokens",
    "priority", "is_emergency", "in_fallback_chain",
    "input_cost_per_million", "output_cost_per_million", "group_label",
    "reasoning_effort",
]

WIZARD_GROUP_HEADERS = {
    0: "🆔 — گروه هویت (Identity):",
    4: "🔒 — گروه محدودیت‌ها (Limits):",
    12: "⛓️ — گروه فال‌بک (Fallback):",
    15: "💰 — گروه هزینه و برچسب (Cost & Label):",
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
    # D1: stored + draft values through the display owner (single mask rule —
    # the old divergent `len > 4` wizard threshold is deleted). "—" marks empty.
    current_str = preset_fields.display_value(preset, field_name)

    wizard = context.user_data.get("full_edit", {})
    values = wizard.get("values", {})
    # Empty/whitespace-only drafts render no "پیشنویس" line (pinned by
    # test_wizard_empty_draft_not_rendered / whitespace variant); a real
    # draft renders through the display owner.
    if field_name in values:
        raw_draft = values[field_name]
        if raw_draft is None or str(raw_draft).strip() == "":
            draft_str = None
        else:
            draft_str = preset_fields.display_value(preset, field_name, raw_draft)
    else:
        draft_str = None

    group_header = WIZARD_GROUP_HEADERS.get(field_idx, "")
    label = FIELD_LABELS.get(field_name, field_name)
    help_text = _FIELD_HELP.get(field_name, "")

    msg = Message()
    msg.add_line(plain("✏️ "), bold(f"ویرایش کامل — گام {field_idx + 1} از {TOTAL_WIZARD_FIELDS}"))
    if group_header:
        msg.add_line()
        msg.add_line(plain(group_header))
    msg.add_line()
    msg.add_line(bold(label))
    if draft_str:
        msg.add_line(plain("پیشنویس (در انتظار ذخیره): "), code(draft_str))
    if current_str != "—":
        msg.add_line(plain("مقدار فعلی: "), code(current_str))
    else:
        msg.add_line(plain("مقدار فعلی: "), italic("خالی"))
    if help_text:
        msg.add_line()
        msg.add_line(plain("💡 "), plain(help_text))
    msg.add_line()
    msg.add_line(plain("مقدار جدید را ارسال کنید (یا خالی = رد کردن):"))

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

    sent = await say(update, context, msg, backend=Backend.HTML, keyboard=keyboard)
    _store_awaiting_msg(context, update, sent)


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
        elif field_name == "reasoning_effort":
            v = raw.strip().lower()
            if v not in ("none", "minimal", "low", "medium", "high", "xhigh"):
                return None
            return (v,)
        else:
            return (raw,)
    except (ValueError, TypeError):
        return None


async def _handle_full_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_idx: int, text: str):
    """Handle text input during full edit wizard."""
    preset = db.get_preset(preset_name)
    if not preset:
        await say(update, context, "پیش‌تنظیم یافت نشد", raw=RawFormat.PLAIN, mode="send")
        return

    field_name = WIZARD_FIELDS[field_idx]
    raw = text.strip()

    # Delete user message containing plaintext API key immediately
    if field_name == "api_key" and raw:
        try:
            await update.message.delete()
        except Exception as exc:
            logging.getLogger(__name__).debug("delete wizard api_key msg failed: %s", exc)

    wizard = context.user_data.get("full_edit", {})
    if wizard.get("preset") != preset_name:
        await say(update, context, "ویزارد منقضی شده. دوباره شروع کنید.", raw=RawFormat.PLAIN, mode="send")
        return

    if raw:
        result = _validate_wizard_value(field_name, raw, preset_name)
        if result is None:
            await _clear_awaiting_prompt(context)
            context.user_data["awaiting"] = f"ai_preset_full_edit:{preset_name}:{field_idx}"
            await _show_wizard_field(update, context, preset_name, field_idx, preset)
            return
        wizard["values"][field_name] = result[0]

    next_idx = field_idx + 1
    wizard["field_idx"] = next_idx

    await _clear_awaiting_prompt(context)
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
    await _clear_awaiting_prompt(context)
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
    await _clear_awaiting_prompt(context)
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
    await _clear_awaiting_prompt(context)
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

    msg = Message()
    msg.add_line(plain("📋 "), bold("خلاصه تغییرات برای " + str(preset_name)))
    msg.add_line()
    changed = 0
    for field_name in WIZARD_FIELDS:
        if field_name in values:
            # D1: old/new through the display owner (api_key masked, empty "—").
            old_val = preset_fields.display_value(preset, field_name)
            new_val = preset_fields.display_value(preset, field_name, values[field_name])
            label = FIELD_LABELS.get(field_name, field_name)
            msg.add_line(
                plain("• "), bold(label),
                plain(f": {old_val} → {new_val}"),
            )
            changed += 1

    if not changed:
        msg.add_line(plain("هیچ تغییری اعمال نشد."))

    msg.add_line()
    msg.add_line(plain("تعداد تغییرات: "), plain(str(changed)))

    from services.utils.callback_codec import preset_token
    preset_ref = preset_token(preset_name)
    buttons = [
        InlineKeyboardButton(IBTN_FULL_EDIT_SAVE_ALL, callback_data=f"admin:ai_preset:full_edit_save:{preset_ref}"),
        InlineKeyboardButton(IBTN_FULL_EDIT_CANCEL_WIZARD, callback_data=f"admin:ai_preset:full_edit_cancel:{preset_ref}"),
    ]
    keyboard = InlineKeyboardMarkup([buttons])

    context.user_data.pop("awaiting", None)

    await say(update, context, msg, backend=Backend.HTML, keyboard=keyboard)


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

    try:
        db.set_preset(
            name=new_name,
            base_url=values.get("base_url", preset.get("base_url", "")),
            model=values.get("model", preset.get("model", "")),
            api_key=values.get("api_key", preset_fields.resolve(preset, "api_key")),
            daily_batch_size=int(values.get("daily_batch_size", preset_fields.resolve(preset, "daily_batch_size"))),
            max_concurrency=int(values.get("max_concurrency", preset_fields.resolve(preset, "max_concurrency"))),
            max_rpm=int(values.get("max_rpm", preset_fields.resolve(preset, "max_rpm"))),
            max_tpm=int(values.get("max_tpm", preset_fields.resolve(preset, "max_tpm"))),
            max_daily_req=int(values.get("max_daily_req", preset_fields.resolve(preset, "max_daily_req"))),
            timeout_seconds=float(values.get("timeout_seconds", preset_fields.write_value(preset, "timeout_seconds"))),
            temperature=float(values.get("temperature", preset_fields.write_value(preset, "temperature"))),
            max_output_tokens=int(values.get("max_output_tokens", preset_fields.write_value(preset, "max_output_tokens"))),
            is_emergency=int(values.get("is_emergency", preset_fields.resolve(preset, "is_emergency"))),
            input_cost_per_million=values.get("input_cost_per_million", preset_fields.resolve(preset, "input_cost_per_million")),
            output_cost_per_million=values.get("output_cost_per_million", preset_fields.resolve(preset, "output_cost_per_million")),
            in_fallback_chain=int(values.get("in_fallback_chain", preset_fields.resolve(preset, "in_fallback_chain"))),
            group_label=values.get("group_label", preset_fields.resolve(preset, "group_label")),
            reasoning_effort=(values.get("reasoning_effort") or preset_fields.resolve(preset, "reasoning_effort") or "none"),
        )
    except db.MasterKeyRequiredError:
        await notify_callback(update.callback_query, "برای ذخیره کلید API باید AI_MASTER_KEY در سرور پیکربندی شود.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    if rename:
        db.delete_preset(preset_name)

    context.user_data.pop("full_edit", None)
    context.user_data.pop("awaiting", None)

    await notify_callback(update.callback_query, f"پیش‌تنظیم {new_name} ذخیره شد", intent=CallbackNoticeIntent.SUCCESS)
    await _show_ai_preset_view(update, context, new_name)


async def _toggle_preset_view_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str | None = None):
    """Set or toggle preset view mode (O-view-mode).

    When mode is 'linear' or 'grouped' the payload is honored directly
    (keyboards.py emits the target mode). Invalid/None payload falls back to
    toggle for backward compatibility.
    """
    if mode in ("linear", "grouped"):
        new_mode = mode
    else:
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

    msg = Message()
    msg.add_line(plain("📁 "), bold("گروه: " + str(target.get('label') or target['masked_key'])))
    msg.add_line()
    msg.add_line(plain("🔑 کلید: "), plain(str(target['masked_key'])))
    msg.add_line(plain("تعداد: "), plain(str(target['count'])), plain(" preset"))
    msg.add_line()
    for p in presets:
        msg.add_line(*_preset_brief_spans(p, active_name), plain(" — "), plain(str(p.get('model', '—'))))

    buttons = [
        [
            InlineKeyboardButton(IBTN_GROUP_BATCH_KEY, callback_data=f"admin:ai_preset:group_batch_key:{key_hash}"),
            InlineKeyboardButton(IBTN_GROUP_SET_LABEL, callback_data=f"admin:ai_preset:group_set_label:{key_hash}"),
        ],
        [InlineKeyboardButton(BTN_BACK, callback_data="admin:ai_presets")],
    ]
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))


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
    msg = Message()
    msg.add_line(plain("🏷️ "), bold("مدیریت گروه‌ها"))
    msg.add_line()
    if not groups:
        msg.add_line(plain("هیچ گروهی تعریف نشده است."))
        msg.add_line(plain("برای گروه‌بندی، از فیلد group_label استفاده کنید."))
    else:
        for g in groups:
            msg.add_line(plain("• "), bold(str(g['label'])), plain(f" — {g['count']} پریست"))
    msg.add_line()

    buttons = []
    from services.utils.callback_codec import label_token
    for g in groups:
        buttons.append([
            InlineKeyboardButton(f"✏️ {g['label']}", callback_data=f"admin:ai_preset:group_manager_rename:{label_token(g['label'])}"),
            InlineKeyboardButton(f"🗑️ حذف برچسب", callback_data=f"admin:ai_preset:group_manager_clear:{label_token(g['label'])}"),
        ])
    buttons.append([InlineKeyboardButton(IBTN_BACK, callback_data="admin:ai_settings")])

    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))


async def _handle_group_manager_rename(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    """Start rename flow for a group label."""
    context.user_data["awaiting"] = f"admin_group_manager_rename:{quote(label)}"
    msg = Message()
    msg.add_line(plain("✏️ نام جدید برای گروه "), bold(str(label)), plain(" را ارسال کنید:"))
    msg.add_line(plain("(خالی = انصراف)"))
    await say(update, context, msg, backend=Backend.HTML, keyboard=admin_awaiting_inline_keyboard())


async def _handle_group_manager_clear(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str):
    """Clear a group label from all presets."""
    db.clear_group_label(label)
    await notify_callback(update.callback_query, f"✅ برچسب «{label}» از همه پریست‌ها حذف شد", intent=CallbackNoticeIntent.SUCCESS)
    await _show_group_manager(update, context)


async def _confirm_save_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str):
    """Show the save-preview confirmation (concept C, R3).

    Builds the dialog via the shared ``build_confirm_message`` helper:
    ``⚠️ تأیید ذخیره — «{name}»`` + numbered per-field vertical old/new
    tables in ``WIZARD_FIELDS`` order (via ``_preset_edit_diffs``; api_key
    values pre-masked, never plaintext) + Persian-digit dirty count +
    conditional notes (🎯 active-preset warning; priority/fallback note only
    when those fields are dirty). Keyboard reuses the existing
    ``confirm_save_yes``/``confirm_save_no`` callbacks plus the existing
    ``ai_preset:edit`` route — no new callback prefixes.
    """
    edits = context.user_data.get("preset_edits", {}).get(preset_name, {})
    if not edits:
        await notify_callback(update.callback_query, "تغییری برای ذخیره وجود ندارد", intent=CallbackNoticeIntent.INFO)
        return

    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    diffs = _preset_edit_diffs(preset, edits)
    notes: list[str] = []
    if preset_name == db.get_active_preset_name():
        notes.append("🎯 این پیش‌تنظیم فعال است — تغییرات پس از ذخیره بلافاصله اعمال می‌شوند.")
    if any(field in edits for field in ("priority", "in_fallback_chain")):
        notes.append("⛓️ تغییر اولویت یا زنجیره فال‌بک مسیر درخواست‌های بعدی را تغییر می‌دهد.")
    msg = build_confirm_message("⚠️ تأیید ذخیره —", f"«{preset_name}»", diffs, notes=notes, numbered=True)

    from config.keyboards import IBTN_BACK_TO_EDIT, IBTN_SAVE_CANCEL, IBTN_SAVE_CONFIRM
    from services.utils.callback_codec import preset_token
    preset_ref = preset_token(preset_name)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(IBTN_SAVE_CONFIRM, callback_data=f"admin:ai_preset:confirm_save_yes:{preset_ref}"),
            InlineKeyboardButton(IBTN_SAVE_CANCEL, callback_data=f"admin:ai_preset:confirm_save_no:{preset_ref}"),
        ],
        [
            InlineKeyboardButton(IBTN_BACK_TO_EDIT, callback_data=f"admin:ai_preset:edit:{preset_ref}"),
        ],
    ])
    await say(update, context, msg, backend=Backend.RICH, keyboard=keyboard)


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
            priority=int(edits.get("priority", preset_fields.resolve(preset, "priority"))),
            base_url=edits.get("base_url", preset.get("base_url", "")),
            model=edits.get("model", preset.get("model", "")),
            api_key=edits.get("api_key", preset_fields.resolve(preset, "api_key")),
            daily_batch_size=int(edits.get("daily_batch_size", preset_fields.resolve(preset, "daily_batch_size"))),
            max_concurrency=int(edits.get("max_concurrency", preset_fields.resolve(preset, "max_concurrency"))),
            max_rpm=int(edits.get("max_rpm", preset_fields.resolve(preset, "max_rpm"))),
            max_tpm=int(edits.get("max_tpm", preset_fields.resolve(preset, "max_tpm"))),
            max_daily_req=int(edits.get("max_daily_req", preset_fields.resolve(preset, "max_daily_req"))),
            timeout_seconds=float(edits.get("timeout_seconds", preset_fields.write_value(preset, "timeout_seconds"))),
            temperature=float(edits.get("temperature", preset_fields.write_value(preset, "temperature"))),
            max_output_tokens=int(edits.get("max_output_tokens", preset_fields.write_value(preset, "max_output_tokens"))),
            is_emergency=int(edits.get("is_emergency", preset_fields.resolve(preset, "is_emergency"))),
            input_cost_per_million=edits.get("input_cost_per_million", preset_fields.resolve(preset, "input_cost_per_million")),
            output_cost_per_million=edits.get("output_cost_per_million", preset_fields.resolve(preset, "output_cost_per_million")),
            in_fallback_chain=int(edits.get("in_fallback_chain", preset_fields.resolve(preset, "in_fallback_chain"))),
            group_label=edits.get("group_label", preset_fields.resolve(preset, "group_label")),
            reasoning_effort=(edits.get("reasoning_effort") or preset_fields.resolve(preset, "reasoning_effort") or "none"),
            previous_name=preset_name,
            remove_orphaned_group_key=removing_group,
        )
    except ValueError:
        await notify_callback(update.callback_query, "این نام هم‌اکنون توسط پیش‌تنظیم دیگری استفاده می‌شود.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    except db.MasterKeyRequiredError:
        await notify_callback(update.callback_query, "برای ذخیره کلید API باید AI_MASTER_KEY در سرور پیکربندی شود.", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
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
    msg = Message()
    msg.add_line(plain("⚠️ "), bold(f"آیا از حذف پیش‌تنظیم «{preset_name}» مطمئنید؟"))
    msg.add_line(plain("این عمل بازگشت‌پذیر نیست."))
    await say(update, context, msg, backend=Backend.HTML, keyboard=keyboard)


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
    msg = Message()
    msg.add_line(plain("➕ "), bold("ایجاد پیش‌تنظیم جدید"))
    msg.add_line()
    msg.add_line(plain("نام پیش‌تنظیم را وارد کنید (مثال: my_openai):"))
    await say(update, context, msg, backend=Backend.HTML, keyboard=admin_awaiting_inline_keyboard())


async def _handle_ai_preset_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle new preset name input."""
    name = text.strip().lower().replace(" ", "_")
    if not name or not all(c.isalnum() or c == "_" for c in name) or len(name) > MAX_PRESET_NAME_LEN:
        context.user_data["awaiting"] = "ai_preset_new_name"
        await say(update, context, "نام نامعتبر. فقط حروف، اعداد و زیرخط مجاز است و حداکثر ۶۰ کاراکتر.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
        return

    existing = db.get_preset(name)
    if existing:
        context.user_data["awaiting"] = "ai_preset_new_name"
        await say(update, context, "این نام از قبل وجود دارد.", raw=RawFormat.PLAIN, keyboard=admin_awaiting_inline_keyboard(), mode="send")
        return

    # Begin the create flow: remember the pending name, then ask for priority.
    context.user_data["preset_create"] = {"name": name}
    context.user_data.pop("awaiting", None)
    await _show_create_priority(update, context)


# ======== R14 Create Flow ========


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


# ======== Custom Test Wizard ========

async def _start_custom_test_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the custom test wizard."""
    context.user_data["custom_test_state"] = {"step": "prompt"}
    context.user_data["awaiting"] = "ai_custom_test_prompt"

    msg = Message()
    msg.add_line(plain("🧪 "), bold("تست سفارشی کارت"))
    msg.add_line()
    msg.add_line(plain("مرحله ۱/۵: پرامپت سیستم (یا متن تست) را وارد کنید:"))
    msg.add_line(italic("مثال: یک کارت واژگان برای سطح مبتدی بساز"))
    await say(update, context, msg, backend=Backend.HTML, keyboard=admin_awaiting_inline_keyboard())


async def _custom_test_step_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("custom_test_state", {})
    state["step"] = "lang"
    context.user_data["custom_test_state"] = state
    context.user_data.pop("awaiting", None)

    buttons = [
        [InlineKeyboardButton(opt.name_fa, callback_data=f"admin:ai_custom_test:lang:{opt.code}")]
        for opt in LANGUAGES.values()
    ]
    msg = Message()
    msg.add_line(plain("🧪 "), bold("تست سفارشی - مرحله ۲/۵"))
    msg.add_line()
    msg.add_line(plain("زبان مقصد را انتخاب کنید:"))
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))


async def _custom_test_step_goal(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str):
    state = context.user_data.get("custom_test_state", {})
    state["lang"] = lang
    state["step"] = "goal"
    context.user_data["custom_test_state"] = state

    buttons = [
        [InlineKeyboardButton(opt.name_fa, callback_data=f"admin:ai_custom_test:goal:{opt.code}")]
        for opt in GOALS.values()
    ]
    msg = Message()
    msg.add_line(plain("🧪 "), bold("تست سفارشی - مرحله ۳/۵"))
    msg.add_line()
    msg.add_line(plain("هدف یادگیری را انتخاب کنید:"))
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))


async def _custom_test_step_level(update: Update, context: ContextTypes.DEFAULT_TYPE, goal: str):
    state = context.user_data.get("custom_test_state", {})
    state["goal"] = goal
    state["step"] = "level"
    context.user_data["custom_test_state"] = state

    buttons = [
        [InlineKeyboardButton(f"{opt.name_fa} ({opt.cefr})", callback_data=f"admin:ai_custom_test:level:{opt.code}")]
        for opt in LEVELS.values()
    ]
    msg = Message()
    msg.add_line(plain("🧪 "), bold("تست سفارشی - مرحله ۴/۵"))
    msg.add_line()
    msg.add_line(plain("سطح زبان را انتخاب کنید:"))
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))


async def _custom_test_step_target(update: Update, context: ContextTypes.DEFAULT_TYPE, level: str):
    state = context.user_data.get("custom_test_state", {})
    state["level"] = level
    state["step"] = "target"
    context.user_data["custom_test_state"] = state

    try:
        active_preset = db.get_active_preset()
    except db.NoActivePresetError:
        msg = Message()
        msg.add_line(plain("⚠️ "), plain("هیچ پیش‌تنظیم فعالی برای تست «جدید» وجود ندارد."))
        msg.add_line(plain("اول یک پیش‌تنظیم را فعال کنید یا فقط گزینه «پیش‌تنظیم کاندیدا» را انتخاب کنید."))
        await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔸 پیش‌تنظیم کاندیدا", callback_data="admin:ai_custom_test:target:candidate")],
            [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
        ]))
        return
    buttons = [
        [InlineKeyboardButton("🔹 پیکربندی فعلی", callback_data="admin:ai_custom_test:target:current")],
        [InlineKeyboardButton("🔸 پیش‌تنظیم کاندیدا", callback_data="admin:ai_custom_test:target:candidate")],
        [InlineKeyboardButton("⚖️ مقایسه A/B", callback_data="admin:ai_custom_test:target:ab")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
    ]
    msg = Message()
    msg.add_line(plain("🧪 "), bold("تست سفارشی - مرحله ۵/۵"))
    msg.add_line()
    msg.add_line(plain("هدف تست را انتخاب کنید:"))
    msg.add_line(plain("- فعلی: "), plain(str(active_preset.get('name', '—'))))
    msg.add_line(plain("- کاندیدا: پیش‌تنظیم دیگری را انتخاب کنید"))
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))


async def _run_custom_test(update: Update, context: ContextTypes.DEFAULT_TYPE, target: str):
    """Execute the custom test."""
    state = context.user_data.get("custom_test_state", {})
    prompt = state.get("prompt", "یک کارت واژگان بساز")
    lang = state.get("lang", "en")
    goal = state.get("goal", "general")
    level = state.get("level", "beginner")

    await notify_callback(update.callback_query, "در حال اجرای تست...", intent=CallbackNoticeIntent.INFO)

    system_prompt = prompts.daily_batch_system_prompt(
        lang, goal, level, compact=prompts.card_output_is_compact()
    )

    results = []

    # Fail fast on a missing candidate BEFORE any provider call: for
    # target="ab" the current-config call below is paid, so validating the
    # candidate first avoids burning one AI call whose result is discarded
    # by the early return.
    candidate_name = None
    candidate = None
    if target in ("candidate", "ab"):
        candidate_name = state.get("candidate_preset")
        candidate = db.get_preset(candidate_name) if candidate_name else None
        if not candidate:
            await notify_callback(
                update.callback_query,
                "پیش‌تنظیم کاندیدا انتخاب نشده است.",
                intent=CallbackNoticeIntent.IMPORTANT_ERROR,
            )
            msg = Message()
            msg.add_line(plain("⚠️ "), plain("پیش‌تنظیم کاندیدا انتخاب نشده است."))
            if candidate_name:
                msg.add_line(plain("نام درخواستی: "), code(str(candidate_name)))
            msg.add_line(plain("یک پیش‌تنظیم کاندیدا را انتخاب کنید."))
            await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
            ]))
            return

    if target in ("current", "ab"):
        try:
            active_preset = db.get_active_preset()
        except db.NoActivePresetError:
            msg = Message()
            msg.add_line(plain("⚠️ "), plain("هیچ پیش‌تنظیم فعالی برای تست «پیکربندی فعلی» وجود ندارد."))
            msg.add_line(plain("ابتدا یک پیش‌تنظیم را فعال کنید."))
            await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
            ]))
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
        # Candidate already validated above (fail-fast, zero provider calls).
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
    msg = Message()
    msg.add_line(plain("🧪 "), bold("نتیجه تست سفارشی"))
    for label, card in results:
        msg.add_line()
        msg.add_line(bold(str(label)))
        msg.add_line(plain("Word: "), plain(str(card.get('word', '?'))))
        msg.add_line(plain("Meaning: "), plain(str(card.get('fa_meaning', '?'))))
        msg.add_line(plain("Examples: "), plain(str(card.get('examples', []))))

    msg.add_line()
    msg.add_line(plain("🧪 این تست روی پیکربندی پیش‌تنظیم اجرا شد، نه مسیر تولید."))

    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 تست مجدد", callback_data="admin:ai_custom_test")],
        [InlineKeyboardButton("↩️ بازگشت", callback_data="admin:ai_settings")],
    ]))
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
    msg = Message()
    msg.add_line(plain("🧪 "), bold("تست سفارشی - انتخاب پیش‌تنظیم"))
    msg.add_line()
    msg.add_line(plain("پیش‌تنظیم کاندیدا را انتخاب کنید:"))
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(buttons))

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
    msg.add_line(plain("• name: نام یکتای پریست (فقط حروف انگلیسی، اعداد، زیرخط)"))
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


USAGE_PAGE_SIZE = 5


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
    elif action.startswith("ai_preset:test:"):
        preset_name = _resolve_preset_ref(action.split(":", 2)[2])
        await _test_ai_preset(update, context, preset_name)
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
        await _toggle_preset_view_mode(update, context, mode)
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
    text-input dispatch. Registered in handlers/flows.py (R2). Behavior and
    awaiting strings are unchanged.
    """
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
