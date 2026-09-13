"""Admin AI list/view leaf (REF2-T4, second).

Verbatim home of preset list/view/edit and wizard UI handlers.
"""

import asyncio
import hashlib
import json
import logging
import re
from urllib.parse import quote, unquote

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import KeyboardButtonStyle
from telegram.ext import ContextTypes

from services import db
from services.utils.callback_codec import resolve_field_alias, resolve_label_token, resolve_preset_token
from services.ai import ai
from services.ai import preset_fields, prompts
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.formatting import to_persian_digits
from services.utils.confirm_summary import FieldDiff, build_confirm_message, pending_header, render_diffs
from services.utils.helpers import _clear_awaiting_prompt, _edit_or_send, _rotate_awaiting_msg
from services.send_pretty import Backend, Message, RawFormat, bold, code, italic, plain, say
from config.catalog import GOALS, LANGUAGES, LEVELS
from config.keyboards import (
    BTN_BACK,
    IBTN_BACK,
    admin_awaiting_inline_keyboard,
    preset_edit_awaiting_inline_keyboard,
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

from handlers.admin_ai_wizard import (
    FIELD_LABELS,
    MAX_GROUP_LABEL_LEN,
    TOTAL_WIZARD_FIELDS,
    WIZARD_FIELDS,
    WIZARD_GROUP_HEADERS,
    _FIELD_HELP,
    _preset_edit_diffs,
    _validate_wizard_value,
)


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
    msg.add_line()
    # T8 (U3): one cheap read — 24h req/token counts from the existing
    # preset_hourly_usage aggregate. No per-preset total / last-used getter
    # exists (llm_requests helpers have no preset_name filter), so those are
    # deliberately omitted rather than scanned. Missing rows → (0, 0).
    req_24h, tok_24h = db.get_hourly_usage(preset_name, hours_back=24)
    msg.add_line(plain("📊 "), bold("مصرف ۲۴ ساعته"))
    msg.add_line(
        plain("درخواست‌ها: "),
        plain(to_persian_digits(req_24h)),
        plain(" | توکن‌ها: "),
        plain(to_persian_digits(tok_24h)),
    )

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

async def _edit_ai_preset(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, just_staged: str | None = None):
    """Show field edit options for a preset."""
    preset = db.get_preset(preset_name)
    if not preset:
        await notify_callback(update.callback_query, "پیش‌تنظیم یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return

    edits = context.user_data.get("preset_edits", {}).get(preset_name, {})
    diffs = _preset_edit_diffs(preset, edits)

    msg = Message()
    if just_staged:
        # T9 (U4): staged line is the sole feedback (the text-path toast was
        # a proven no-op). It carries no count itself — the pending_header
        # line below carries it exactly once.
        msg.add_line(plain(f"✅ پیش‌نویس «{just_staged}» نگه داشته شد"))
        if diffs:
            msg.add_line(plain(pending_header(diffs)))
    msg.add_line(plain("✏️ "), bold("ویرایش پیش‌تنظیم: " + str(preset_name)))
    msg.add_line(plain("انتخاب فیلد برای تغییر:"))
    if diffs:
        if just_staged is None:
            msg.add_line(plain(pending_header(diffs)))
        for line in render_diffs(diffs):
            msg.add_line(*line)

    await say(update, context, msg, backend=Backend.RICH, keyboard=ai_preset_edit_keyboard(preset_name, diffs, has_group=bool(preset.get("group_label"))))

async def _edit_ai_preset_field(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_name: str):
    """Prompt for new value of a field."""
    if field_name not in preset_fields.PRESET_FIELDS:
        await notify_callback(update.callback_query, "فیلد نامعتبر است", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
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

    sent = await say(
        update, context, msg, backend=Backend.HTML,
        # preset_edit_awaiting_inline_keyboard() -> flow:back resumes the
        # preset-edit menu (preserves preset_edits); flow:cancel discards only
        # this preset's edits; admin:close is the close path (clears all
        # pending state). This aligns with the field-edit error-retry prompts.
        # Note: this intentionally differs from admin_awaiting_inline_keyboard(),
        # whose admin:cancel wiped ALL preset_edits (contract R3, owner-approved).
        keyboard=preset_edit_awaiting_inline_keyboard()
    )
    # R2: rotate — strip the previous prompt's keyboard before tracking this one.
    await _rotate_awaiting_msg(context, update, sent)

async def _handle_ai_preset_field_input(update: Update, context: ContextTypes.DEFAULT_TYPE, preset_name: str, field_name: str, text: str):
    """Process field input for preset edit."""
    preset = db.get_preset(preset_name)
    if not preset:
        await say(update, context, "پیش‌تنظیم یافت نشد", raw=RawFormat.PLAIN, mode="send")
        return

    if field_name not in preset_fields.PRESET_FIELDS:
        context.user_data.pop("awaiting", None)
        await say(update, context, "فیلد نامعتبر است.", raw=RawFormat.PLAIN, mode="send")
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
            value = preset_fields.validate_preset_name(raw)
            if value is None:
                raise ValueError
            # Check uniqueness (skip if same as current)
            if value != preset_name and db.get_preset(value):
                context.user_data["awaiting"] = f"ai_preset_edit:{preset_name}:{field_name}"
                sent = await say(update, context, "این نام از قبل وجود دارد. نام دیگری انتخاب کنید.", raw=RawFormat.PLAIN, keyboard=preset_edit_awaiting_inline_keyboard(), mode="send")
                await _rotate_awaiting_msg(context, update, sent)
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
        if field_name == "name":
            error_text = preset_fields.PRESET_NAME_ERROR_FA
        else:
            error_text = "فرمت نامعتبر. لطفاً مقدار معتبر بفرستید."
        sent = await say(update, context, error_text, raw=RawFormat.PLAIN, keyboard=preset_edit_awaiting_inline_keyboard(), mode="send")
        await _rotate_awaiting_msg(context, update, sent)
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
    # T9 (U4): dead toast removed — update.callback_query is always None on
    # the text-input path, so notify_callback was a proven no-op. The
    # re-rendered menu's just_staged line is the sole staged feedback.
    await _edit_ai_preset(update, context, preset_name, just_staged=label)

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
    await _rotate_awaiting_msg(context, update, sent)

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
    """Show summary of wizard changes and ask for confirmation (U5).

    Renders through the shared ``build_confirm_message`` seam with
    ``numbered=False`` (preserves the unnumbered wizard look) in
    ``WIZARD_FIELDS`` order via ``_preset_edit_diffs`` (api_key masked via
    the display owner, never plaintext). The keyboard stays the wizard's
    own save-all/cancel pair — the confirm dialog's routes are untouched.
    Backend is RICH: the shared per-field tables are ``Table`` spans,
    which have no HTML rendering (same switch as the T2 edit menu).
    """
    wizard = context.user_data.get("full_edit", {})
    values = wizard.get("values", {})
    preset = db.get_preset(preset_name) or {}

    diffs = _preset_edit_diffs(preset, values)
    msg = build_confirm_message(
        "📋 خلاصه تغییرات برای", f"«{preset_name}»", diffs, numbered=False
    )

    from services.utils.callback_codec import preset_token
    preset_ref = preset_token(preset_name)
    buttons = [
        InlineKeyboardButton(IBTN_FULL_EDIT_SAVE_ALL, callback_data=f"admin:ai_preset:full_edit_save:{preset_ref}", style=KeyboardButtonStyle.SUCCESS),
        InlineKeyboardButton(IBTN_FULL_EDIT_CANCEL_WIZARD, callback_data=f"admin:ai_preset:full_edit_cancel:{preset_ref}"),
    ]
    keyboard = InlineKeyboardMarkup([buttons])

    context.user_data.pop("awaiting", None)

    await say(update, context, msg, backend=Backend.RICH, keyboard=keyboard)

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
    conditional notes (🎯 active-preset warning; 🔑 api_key warning; ⛓️
    priority/fallback note only when those fields are dirty; 🚨
    is_emergency warning — fixed order 🎯→🔑→⛓️→🚨). Keyboard reuses the existing
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
    if not diffs:
        await notify_callback(update.callback_query, "تغییری برای ذخیره وجود ندارد", intent=CallbackNoticeIntent.INFO)
        return

    notes: list[str] = []
    # T9 (U4): fixed order 🎯→🔑→⛓️→🚨, confirm dialog only.
    if preset_name == db.get_active_preset_name():
        notes.append("🎯 این پیش‌تنظیم فعال است — تغییرات پس از ذخیره بلافاصله اعمال می‌شوند.")
    if "api_key" in edits:
        notes.append("🔑 کلید عوض می‌شود — درخواست‌های بعدی با کلید جدید ارسال می‌شوند.")
    if any(field in edits for field in ("priority", "in_fallback_chain")):
        notes.append("⛓️ تغییر اولویت یا زنجیره فال‌بک مسیر درخواست‌های بعدی را تغییر می‌دهد.")
    if "is_emergency" in edits:
        notes.append("🚨 پرچم اضطراری عوض می‌شود — مقصد مسیر اضطراری جابه‌جا می‌شود.")
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
    await notify_callback(update.callback_query, "✅ حذف از گروه نگه داشته شد (پیش‌نویس). برای اعمال، ذخیره را بزنید.", intent=CallbackNoticeIntent.SUCCESS)
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
            InlineKeyboardButton(IBTN_DELETE_CONFIRM, callback_data=f"admin:ai_preset:confirm_delete_yes:{preset_ref}", style=KeyboardButtonStyle.DANGER),
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

