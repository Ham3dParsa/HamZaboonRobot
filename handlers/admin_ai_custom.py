"""Admin AI custom-test leaf (REF2-T4, fifth).

Verbatim home of custom-test wizard and central callback router.
Last leaf so it can import earlier leaves at top level without forward deps.
"""

import asyncio
import json
import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from services import db
from services.utils.callback_codec import resolve_field_alias, resolve_label_token, resolve_preset_token
from services.ai import ai
from services.ai import preset_fields, prompts
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.formatting import to_persian_digits
from services.utils.helpers import _clear_awaiting_prompt, _edit_or_send, _rotate_awaiting_msg
from services.send_pretty import Backend, Message, RawFormat, bold, code, italic, plain, say
from config.catalog import GOALS, LANGUAGES, LEVELS
from config.keyboards import admin_awaiting_inline_keyboard

from handlers.admin_ai_wizard import _validate_wizard_value
from handlers.admin_ai_list import (
    _activate_ai_preset,
    _confirm_delete_no,
    _confirm_delete_yes,
    _confirm_save_preset,
    _delete_ai_preset,
    _detach_ai_preset_group,
    _detect_key_groups,
    _discard_all_preset_changes,
    _duplicate_ai_preset,
    _edit_ai_preset,
    _edit_ai_preset_field,
    _handle_full_edit_back,
    _handle_full_edit_cancel,
    _handle_full_edit_next,
    _handle_full_edit_pick_group,
    _handle_full_edit_save,
    _handle_full_edit_skip,
    _handle_group_batch_key,
    _handle_group_manager_clear,
    _handle_group_manager_rename,
    _handle_group_set_label,
    _handle_group_view,
    _key_hash,
    _preset_brief_spans,
    _render_preset_brief,
    _resolve_label_ref,
    _resolve_preset_ref,
    _save_ai_preset,
    _show_ai_preset_view,
    _show_ai_presets,
    _show_ai_settings,
    _show_group_manager,
    _show_grouped_presets,
    _show_linear_presets,
    _start_full_edit_wizard,
    _toggle_preset_view_mode,
)
from handlers.admin_ai_create import (
    _add_ai_preset,
    _handle_ai_preset_new_name,
    _handle_create_priority_choice,
    _handle_create_status_choice,
    _handle_create_test,
    _handle_create_toggle_enable,
    _preset_ref,
    _show_create_priority,
    _test_ai_connection,
    _test_ai_preset,
)
from handlers.admin_ai_fallback import (
    _handle_ai_fallback,
    _handle_fallback_rank,
    _show_ai_fallback,
    _show_fallback_chain,
    _show_fallback_usage_details,
    _show_help_fallback_chain,
    _show_help_presets,
    _show_usage_page,
)


async def _start_custom_test_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the custom test wizard."""
    context.user_data["custom_test_state"] = {"step": "prompt"}
    context.user_data["awaiting"] = "ai_custom_test_prompt"

    msg = Message()
    msg.add_line(plain("🧪 "), bold("تست سفارشی کارت"))
    msg.add_line()
    msg.add_line(plain("مرحله ۱/۵: متن تست را وارد کنید:"))
    msg.add_line(italic("مثال: یک کارت واژگان برای سطح مبتدی بساز"))
    msg.add_line(plain("پرامپت سیستمی به‌صورت خودکار همان پرامپت تولید است."))
    base_keyboard = admin_awaiting_inline_keyboard()
    rows = [list(row) for row in base_keyboard.inline_keyboard]
    rows.append(
        [InlineKeyboardButton("⏭ رد شدن (متن پیش‌فرض)", callback_data="admin:ai_custom_test:prompt:skip")]
    )
    await say(update, context, msg, backend=Backend.HTML, keyboard=InlineKeyboardMarkup(rows))

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
        system_prompt = prompts.daily_batch_system_prompt(
            lang,
            goal,
            level,
            preset_fields.resolve(active_preset, "daily_batch_size"),
            compact=prompts.card_output_is_compact(),
        )
        try:
            result = await asyncio.to_thread(
                ai.custom_test_card,
                system_prompt=system_prompt,
                user_prompt=prompt,
                lang=lang,
                goal=goal,
                level=level,
                preset=active_preset,
            )
        except (json.JSONDecodeError, ai.CardValidationError) as exc:
            # A weird test text can make the model return non-JSON; report it
            # instead of crashing the wizard with an unhandled exception.
            results.append((
                "Current Config",
                None,
                f"{type(exc).__name__}: مدل خروجی معتبر برنگرداند؛ با «تست مجدد» و متن ساده‌تر تلاش کنید.",
            ))
        except Exception as exc:
            # Operational failure (auth/network/rate-limit/config): show the
            # real cause, same class+message pattern as _test_ai_connection.
            detail = str(exc).strip().replace("\n", " ")[:160]
            results.append(("Current Config", None, f"{type(exc).__name__}: {detail}"))
        else:
            results.append(("Current Config", result, None))

    if target in ("candidate", "ab"):
        # Candidate already validated above (fail-fast, zero provider calls).
        candidate_prompt = prompts.daily_batch_system_prompt(
            lang,
            goal,
            level,
            preset_fields.resolve(candidate, "daily_batch_size"),
            compact=prompts.card_output_is_compact(),
        )
        try:
            result = await asyncio.to_thread(
                ai.custom_test_card,
                system_prompt=candidate_prompt,
                user_prompt=prompt,
                lang=lang,
                goal=goal,
                level=level,
                preset=candidate,
            )
        except (json.JSONDecodeError, ai.CardValidationError) as exc:
            results.append((
                f"Candidate ({candidate_name})",
                None,
                f"{type(exc).__name__}: مدل خروجی معتبر برنگرداند؛ با «تست مجدد» و متن ساده‌تر تلاش کنید.",
            ))
        except Exception as exc:
            detail = str(exc).strip().replace("\n", " ")[:160]
            results.append((f"Candidate ({candidate_name})", None, f"{type(exc).__name__}: {detail}"))
        else:
            results.append((f"Candidate ({candidate_name})", result, None))

    # Format results
    msg = Message()
    msg.add_line(plain("🧪 "), bold("نتیجه تست سفارشی"))
    for label, card, error in results:
        msg.add_line()
        msg.add_line(bold(str(label)))
        if error is None and not isinstance(card, dict):
            error = f"خروجی نامعتبر: {type(card).__name__}"
        if error is not None:
            msg.add_line(plain("❌ خطا در "), bold(str(label)), plain(":"))
            msg.add_line(plain(str(error)))
        else:
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
    if action == "ai_custom_test:prompt:skip":
        # Step 1/5 skipped: drop any stale prompt so _run_custom_test falls
        # back to the default test text; the system prompt is always production.
        state = context.user_data.get("custom_test_state", {})
        state.pop("prompt", None)
        context.user_data["custom_test_state"] = state
        await _custom_test_step_lang(update, context)
    elif action == "ai_custom_test:lang":
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

