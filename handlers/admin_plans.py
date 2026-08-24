"""Admin plans domain module (Finding #7, task 7.5).

Migrate step: the plan-manager handler logic now lives here instead of the admin
monolith. The admin monolith imports the plan functions from this module. All
behavior and callback strings are unchanged.
"""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from handlers.flows import mark_awaiting_consumed

from services import db, plan_fields, send_pretty
from services.send_pretty import RawFormat, say
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.formatting import html_escape
from services.utils.helpers import _edit_or_send
from config.keyboards import (
    admin_awaiting_inline_keyboard,
    awaiting_inline_keyboard,
    plan_manager_keyboard,
    plan_view_keyboard,
    plan_wizard_keyboard,
    plan_wizard_summary_keyboard,
)

TOTAL_PLAN_WIZARD_FIELDS = len(plan_fields.field_order())


async def _show_plan_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plans = db.list_plans(active_only=False)
    await _edit_or_send(
        update,
        context,
        "💳 مدیریت پلن‌ها\n\nیک پلن را انتخاب کن تا جزئیاتش را ببینی یا ویرایشش کنی:",
        reply_markup=plan_manager_keyboard(plans),
    )
    await notify_callback(update.callback_query)


async def _show_plan_view(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    plan = db.get_plan(name)
    if not plan:
        await notify_callback(update.callback_query, "پلن یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return await _show_plan_list(update, context)
    status = "✅ فعال" if plan.get("is_active") else "⭕ غیرفعال"
    text = (
        f"💳 <b>{html_escape(str(plan.get('display_name')))} ({html_escape(str(plan.get('name')))})</b>\n"
        f"وضعیت: {status}\n\n"
        f"• قیمت: {plan.get('price'):,} تومان\n"
        f"• سهمیه سؤال روزانه (جستجوی دستی واژه): {plan.get('query_quota')}\n"
        f"• جلسات روزانه: {plan.get('max_sessions')}\n"
        f"• کارت در هر جلسه: {plan.get('cards_per_session')}"
    )
    await _edit_or_send(
        update,
        context,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=plan_view_keyboard(name, bool(plan.get("is_active"))),
    )
    await notify_callback(update.callback_query)


async def _start_plan_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    plan = db.get_plan(name)
    if not plan:
        await notify_callback(update.callback_query, "پلن یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    context.user_data["plan_full_edit"] = {"plan": name, "field_idx": 0, "values": {}}
    context.user_data["awaiting"] = f"admin_plan_full_edit:{name}:0"
    await _show_plan_wizard_field(update, context, name, 0, plan)


async def _show_plan_wizard_field(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str, field_idx: int, plan: dict):
    field_name = plan_fields.field_order()[field_idx]
    current = plan.get(field_name)
    if current is None:
        current = ""
    group_header, group_hint = plan_fields.group_header(field_name)
    label = plan_fields.field_label(field_name)
    field_hint = plan_fields.field_hint(field_name)

    message = f"✏️ <b>ویرایش پلن {html_escape(str(name))} — گام {field_idx + 1} از {TOTAL_PLAN_WIZARD_FIELDS}</b>\n"
    if group_header:
        message += f"\n{group_header}\n"
    if group_hint:
        message += f"{group_hint}\n"
    message += f"\n<b>{label}</b>"
    if field_hint:
        message += f"\n<i>{field_hint}</i>"

    # Show the stored DB value always; additionally surface the value already
    # typed this wizard session (if any) so going back doesn't lose it visually.
    # Owner-typed values may contain HTML special chars, so escape before
    # interpolation into an HTML parse_mode message.
    wizard = context.user_data.get("plan_full_edit", {})
    pending = wizard.get("values", {}).get(field_name)
    if current != "":
        message += f"\nمقدار فعلی (DB): <code>{html_escape(str(current))}</code>"
    if pending is not None:
        message += f"\nمقدار در انتظار: <code>{html_escape(str(pending))}</code>"
    message += "\n\nمقدار جدید را ارسال کنید (یا خالی = رد کردن):"

    keyboard = plan_wizard_keyboard(name)
    context.user_data["awaiting"] = f"admin_plan_full_edit:{name}:{field_idx}"

    await _edit_or_send(update, context, message, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def _handle_plan_wizard_input(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str, field_idx: int, text: str):
    plan = db.get_plan(name)
    if not plan:
        await say(update, context, "پلن یافت نشد", raw=RawFormat.PLAIN, mode="send")
        return
    field_name = plan_fields.field_order()[field_idx]
    raw = text.strip()
    wizard = context.user_data.get("plan_full_edit", {})
    if wizard.get("plan") != name:
        await say(update, context, "ویزارد منقضی شده. دوباره شروع کنید.", raw=RawFormat.PLAIN, mode="send")
        return
    if raw:
        result = plan_fields.validate_value(field_name, raw)
        if result is None:
            context.user_data["awaiting"] = f"admin_plan_full_edit:{name}:{field_idx}"
            await say(update, context, "فرمت نامعتبر. لطفاً مقدار معتبر بفرستید.", raw=RawFormat.PLAIN, keyboard=awaiting_inline_keyboard(), mode="send")
            return
        wizard["values"][field_name] = result
    next_idx = field_idx + 1
    wizard["field_idx"] = next_idx
    if next_idx >= TOTAL_PLAN_WIZARD_FIELDS:
        await _show_plan_wizard_summary(update, context, name)
    else:
        context.user_data["awaiting"] = f"admin_plan_full_edit:{name}:{next_idx}"
        await _show_plan_wizard_field(update, context, name, next_idx, plan)


async def _handle_plan_wizard_next(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    wizard = context.user_data.get("plan_full_edit", {})
    if wizard.get("plan") != name:
        await notify_callback(update.callback_query, "ویزارد منقضی شده", intent=CallbackNoticeIntent.INFO)
        return
    current_idx = wizard.get("field_idx", 0)
    # Skip leaves the current field unchanged: discard any pending typed value
    # for it (so the DB value is used on save) and move to the next field.
    current_field = plan_fields.field_order()[current_idx]
    wizard.get("values", {}).pop(current_field, None)
    next_idx = current_idx + 1
    wizard["field_idx"] = next_idx
    plan = db.get_plan(name)
    if next_idx >= TOTAL_PLAN_WIZARD_FIELDS:
        await _show_plan_wizard_summary(update, context, name)
    else:
        context.user_data["awaiting"] = f"admin_plan_full_edit:{name}:{next_idx}"
        await _show_plan_wizard_field(update, context, name, next_idx, plan or {})


async def _handle_plan_wizard_back(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    # Move to the previous field; already-collected values for other fields
    # are preserved so the owner can re-enter one field without losing the rest.
    wizard = context.user_data.get("plan_full_edit", {})
    if wizard.get("plan") != name:
        await notify_callback(update.callback_query, "ویزارد منقضی شده", intent=CallbackNoticeIntent.INFO)
        return
    current_idx = wizard.get("field_idx", 0)
    if current_idx <= 0:
        await notify_callback(update.callback_query, "در اولین گام هستید", intent=CallbackNoticeIntent.INFO)
        return
    prev_idx = current_idx - 1
    plan = db.get_plan(name)
    wizard["field_idx"] = prev_idx
    context.user_data["awaiting"] = f"admin_plan_full_edit:{name}:{prev_idx}"
    await _show_plan_wizard_field(update, context, name, prev_idx, plan or {})


async def _handle_plan_wizard_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    context.user_data.pop("plan_full_edit", None)
    context.user_data.pop("awaiting", None)
    await notify_callback(update.callback_query, "ویرایش پلن لغو شد", intent=CallbackNoticeIntent.INFO)
    await _show_plan_view(update, context, name)


async def _show_plan_wizard_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    wizard = context.user_data.get("plan_full_edit", {})
    values = wizard.get("values", {})
    plan = db.get_plan(name) or {}
    lines = [f"📋 <b>خلاصه تغییرات برای {html_escape(str(plan.get('display_name', name)))}</b>\n"]
    changed = 0
    for field_name in plan_fields.field_order():
        if field_name in values:
            new_val = values[field_name]
            old_val = plan.get(field_name, "—")
            label = plan_fields.field_label(field_name)
            lines.append(f"• <b>{html_escape(str(label))}</b>: {html_escape(str(old_val))} → {html_escape(str(new_val))}")
            changed += 1
    if not changed:
        lines.append("هیچ تغییری اعمال نشد.")
    lines.append(f"\nتعداد تغییرات: {changed}")
    context.user_data.pop("awaiting", None)
    await _edit_or_send(
        update,
        context,
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=plan_wizard_summary_keyboard(name),
    )


async def _handle_plan_wizard_save(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    wizard = context.user_data.get("plan_full_edit", {})
    if wizard.get("plan") != name:
        await notify_callback(update.callback_query, "ویزارد منقضی شده", intent=CallbackNoticeIntent.INFO)
        return
    values = wizard.get("values", {})
    plan = db.get_plan(name)
    if not plan:
        await notify_callback(update.callback_query, "پلن یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    db.upsert_plan(**plan_fields.build_upsert_kwargs(plan, values))
    context.user_data.pop("plan_full_edit", None)
    context.user_data.pop("awaiting", None)
    await notify_callback(update.callback_query, "پلن ذخیره شد", intent=CallbackNoticeIntent.SUCCESS)
    await _show_plan_view(update, context, name)


async def _handle_plan_set_active(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    plan = db.get_plan(name)
    if not plan:
        await notify_callback(update.callback_query, "پلن یافت نشد", intent=CallbackNoticeIntent.IMPORTANT_ERROR)
        return
    db.set_plan_active(name, not bool(plan.get("is_active")))
    await _show_plan_view(update, context, name)


async def _handle_plans_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    """Route plan text-input awaiting states (``admin_set_plan``) to their handler.

    Mirrors the inline block that previously lived in the admin monolith's
    text-input dispatch. Registered in handlers/flows.py (R2). Behavior and
    awaiting strings are unchanged.
    """
    parts = text.split()
    if len(parts) != 2 or not db.valid_plan_name(parts[1].lower()):
        context.user_data["awaiting"] = "admin_set_plan"
        await say(update, context, "فرمت نامعتبر است. نمونه: `123456789 silver` یا `@username gold`", raw=RawFormat.PLAIN, mode="send")
        return
    target = db.find_user(parts[0])
    if not target:
        context.user_data["awaiting"] = "admin_set_plan"
        await say(update, context, "کاربر پیدا نشد؛ ابتدا باید کاربر /start را زده باشد.", raw=RawFormat.PLAIN, mode="send")
        return
    plan = parts[1].lower()
    previous_plan = target["plan"] or "free"
    plan_label = (db.get_plan(plan) or {}).get("display_name", plan)
    prev_label = (db.get_plan(previous_plan) or {}).get("display_name", previous_plan)
    db.set_plan(target["user_id"], plan)
    mark_awaiting_consumed(context)  # plan write is irreversible (B5/Kilo CRITICAL)
    await say(update, context, f"پلن کاربر {target['user_id']} از {prev_label} به {plan_label} تغییر کرد.", raw=RawFormat.PLAIN, mode="send")


async def handle_plan_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
) -> None:
    """Route plan admin callback sub-actions to their handlers.

    Mirrors the inline ``admin:plans`` / ``admin:set_plan`` / ``admin:plans:*``
    branches that previously lived in the admin monolith's ``_handle_admin_callback``.
    The owner check is performed by the caller. Behavior and action strings are unchanged.
    """
    if action == "plans":
        await _show_plan_list(update, context)
    elif action == "set_plan":
        context.user_data["awaiting"] = "admin_set_plan"
        await notify_callback(update.callback_query)
        await send_pretty.send(
            update.effective_chat.id,
            "فرمت را ارسال کنید:\n`user_id_or_username plan`\n\n"
            "مثال: `123456789 silver` یا `@username gold`\n"
            "پلن‌ها: free، bronze، silver، gold، emerald",
            bot=context.bot,
            raw=send_pretty.RawFormat.MDV2,
            keyboard=admin_awaiting_inline_keyboard(),
        )
    elif action.startswith("plans:view:"):
        name = action.split(":", 2)[2]
        await _show_plan_view(update, context, name)
    elif action.startswith("plans:edit:"):
        name = action.split(":", 2)[2]
        await _start_plan_wizard(update, context, name)
    elif action.startswith("plans:full_edit_back:"):
        name = action.split(":", 2)[2]
        await _handle_plan_wizard_back(update, context, name)
    elif action.startswith("plans:full_edit_skip:"):
        name = action.split(":", 2)[2]
        await _handle_plan_wizard_next(update, context, name)
    elif action.startswith("plans:full_edit_cancel:"):
        name = action.split(":", 2)[2]
        await _handle_plan_wizard_cancel(update, context, name)
    elif action.startswith("plans:full_edit_save:"):
        name = action.split(":", 2)[2]
        await _handle_plan_wizard_save(update, context, name)
    elif action.startswith("plans:set_active:"):
        name = action.split(":", 2)[2]
        await _handle_plan_set_active(update, context, name)


__all__ = [
    "TOTAL_PLAN_WIZARD_FIELDS",
    "handle_plan_callback",
    "_handle_plan_set_active",
    "_handle_plan_wizard_back",
    "_handle_plan_wizard_cancel",
    "_handle_plan_wizard_input",
    "_handle_plan_wizard_next",
    "_handle_plan_wizard_save",
    "_handle_plans_text_input",
    "_show_plan_list",
    "_show_plan_view",
    "_show_plan_wizard_field",
    "_show_plan_wizard_summary",
    "_start_plan_wizard",
]
