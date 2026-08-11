"""Help module — user-facing guide for HamZaboon.

Deep module: a small interface (``send_help_panel`` for commands/text,
``handle_help_callback`` for the inline panel) hides all help content and
keyboard construction behind a single data-driven registry (``HELP_SECTIONS``).
Adding or editing a help topic is a one-entry change in that registry; the
panel keyboard and the detail message are both derived from it, so the content
stays in one place (locality) and callers learn only two functions (leverage).
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import is_owner
from config.keyboards import main_menu
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.formatting import escape_mdv2
from services.utils.helpers import _edit_or_send, _send_with_retry

# Static, hardcoded learner-facing literals. The whole template is escaped via
# escape_mdv2; sentinels (@@BOT@@ / @@START@@) are MDV2-safe and replaced after
# escaping with already-escaped fragments, so the result is always valid
# MarkdownV2. There are no dynamic (AI/DB/user) values in help content.
_HELP_INTRO = (
    "سلام! من @@BOT@@ هستم — رباتی که با هوش مصنوعی بهت واژه، مثال و نکته‌ی "
    "گرامری یاد می‌ده و با مرور فاصله‌دار کمکت می‌کنه که چیزایی که یاد گرفتی "
    "رو فراموش نکنی.\n\n"
    "چطور استفاده کنم؟\n"
    "▫️ از دکمه‌های منوی پایین یا دستورات استفاده کن.\n"
    "▫️ با زدن @@START@@ تنظیماتت رو (زبان، هدف، سطح) تنظیم کن.\n\n"
    "برای جزئیات هر بخش، دکمه‌ی مربوطه رو بزن 👇"
)

# id, button label, bold heading, body — all raw Persian (escaped at build).
HELP_SECTIONS = [
    {
        "id": "study",
        "label": "📚 شروع مطالعه امروز",
        "title": "شروع مطالعه امروز",
        "body": (
            "با این بخش، کارت‌های آموزشیِ ساخته‌شده با هوش مصنوعی برات میاد "
            "(شامل واژه، معنی، مثال و تلفظ). واژه‌هایی که برای مرور موعدشون "
            "رسیده با سیستم فاصله‌دار (۴ دکمه: یادم نیامد/سخت بود/خوب بود/خیلی "
            "راحت بود) ارزیابی می‌شن تا بهتر تو ذهنت بمونن.\n\n"
            "روش: دکمه‌ی «📚 شروع مطالعه امروز» رو از منوی پایین بزن."
        ),
    },
    {
        "id": "ask",
        "label": "❓ پرسیدن یک واژه",
        "title": "پرسیدن یک واژه",
        "body": (
            "هر واژه یا عبارت کوتاهی رو بپرس تا هوش مصنوعی برات یه کارت کامل "
            "بسازه: معنی، مثال، تلفظ و ترجمه‌ی مثال‌ها. می‌تونی با دکمه‌ی "
            "«➕ افزودن به مرور» اون واژه رو به لیست مرورت اضافه کنی.\n\n"
            "روش: دکمه‌ی «❓ پرسیدن یک واژه» رو بزن و واژه‌ت رو بنویس."
        ),
    },
    {
        "id": "review",
        "label": "🔁 مرور واژه‌های ذخیره‌شده",
        "title": "مرور واژه‌های ذخیره‌شده",
        "body": (
            "واژه‌هایی که به مرور اضافه کردی اینجا جمع می‌شن. هر روز واژه‌هایی "
            "که موعد مرورشون رسیده برات میاد و با ۴ دکمه ارزیابی‌شون کن تا طبق "
            "الگوریتم فاصله‌دار (FSRS) زمانِ مرور بعدی تنظیم بشه.\n\n"
            "روش: از داخل «شروع مطالعه امروز» وارد مرور می‌شی."
        ),
    },
    {
        "id": "settings",
        "label": "⚙️ تنظیمات و پروفایل من",
        "title": "تنظیمات و پروفایل من",
        "body": (
            "از اینجا زبان هدف، هدف یادگیری (مثلاً سفر، کار، آزمون)، سطح زبان و "
            "نوع نمایش کارت‌ها رو تغییر بده. همچنین وضعیت اشتراک، استریک و "
            "واژه‌های آماده‌ی مرور رو ببین.\n\n"
            "روش: دکمه‌ی «⚙️ تنظیمات و پروفایل من» رو بزن."
        ),
    },
    {
        "id": "tts",
        "label": "🔊 تلفظ (TTS)",
        "title": "تلفظ (TTS)",
        "body": (
            "برای واژه‌ها و مثال‌ها تلفظ صوتی پخش می‌شه. این قابلیت بسته به "
            "تنظیمات ربات، معمولاً برای پلن‌های نقره‌ای و طلایی فعاله. دکمه‌ی 🔊 "
            "توی کارت‌های واژه نشون داده می‌شه."
        ),
    },
    {
        "id": "admin",
        "label": "🛠 مدیریت ربات",
        "title": "مدیریت ربات",
        "body": (
            "پنل مدیریت مخصوص مالک ربات: آمار کاربرها، تنظیم پلن‌ها، تنظیمات "
            "هوش مصنوعی و هزینه‌ها، ارسال پیام همگانی و غیره.\n\n"
            "دسترسی فقط برای مالک ربات فعاله."
        ),
        "owner_only": True,
    },
]

_HELP_BACK_LABEL = "↩️ بازگشت به راهنما"
_HELP_MENU_HINT = "🔻 برای بازگشت به منوی اصلی از دکمه‌های پایین استفاده کن:"


def _visible_sections(user_id: int) -> list[dict]:
    return [s for s in HELP_SECTIONS if not s.get("owner_only") or is_owner(user_id)]


def _build_intro() -> str:
    # Escape the whole template (covers literal . ! ( ) etc.), then inject
    # the already-escaped fragments. The '*' bold markers are added around the
    # bot name after escaping, so they stay as literal MarkdownV2 markers.
    escaped = escape_mdv2(_HELP_INTRO)
    bot = "*" + escape_mdv2("هم‌زبان") + "*"
    start = escape_mdv2("/start")
    return escaped.replace("@@BOT@@", bot).replace("@@START@@", start)


def _build_section_detail(section_id: str) -> str | None:
    for section in HELP_SECTIONS:
        if section["id"] == section_id:
            return f"*{escape_mdv2(section['title'])}*\n\n{escape_mdv2(section['body'])}"
    return None


def _panel_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(s["label"], callback_data=f"help:section:{s['id']}")]
        for s in _visible_sections(user_id)
    ]
    return InlineKeyboardMarkup(rows)


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(_HELP_BACK_LABEL, callback_data="help:back")]]
    )


async def send_help_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for /help and the 'راهنما' text command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    await _send_with_retry(
        context.bot,
        chat_id,
        _build_intro(),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_panel_keyboard(user_id),
    )
    # Restore the persistent reply menu so the user keeps the main keyboard.
    await _send_with_retry(
        context.bot,
        chat_id,
        _HELP_MENU_HINT,
        reply_markup=main_menu(is_owner(user_id)),
    )


async def handle_help_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
):
    """Dispatch for callback_data starting with 'help:'."""
    user_id = update.effective_user.id
    parts = data.split(":", 2)

    if len(parts) == 3 and parts[1] == "section":
        section_id = parts[2]
        # Enforce the same visibility rules as the panel (e.g. owner-only
        # sections must not be reachable by a crafted callback from a
        # non-owner). Look the section up via the visibility-filtered list.
        if not any(s["id"] == section_id for s in _visible_sections(user_id)):
            await notify_callback(
                update.callback_query,
                "این بخش دیگر موجود نیست.",
                intent=CallbackNoticeIntent.IMPORTANT_ERROR,
            )
            return
        detail = _build_section_detail(section_id)
        if detail is None:
            await notify_callback(
                update.callback_query,
                "این بخش دیگر موجود نیست.",
                intent=CallbackNoticeIntent.IMPORTANT_ERROR,
            )
            return
        await _edit_or_send(
            update,
            context,
            detail,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_back_keyboard(),
        )
        await notify_callback(update.callback_query)
        return

    if data == "help:back":
        await _edit_or_send(
            update,
            context,
            _build_intro(),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=_panel_keyboard(user_id),
        )
        await notify_callback(update.callback_query)
        return

    await notify_callback(
        update.callback_query,
        "عملیات ناموفق بود.",
        intent=CallbackNoticeIntent.IMPORTANT_ERROR,
    )
