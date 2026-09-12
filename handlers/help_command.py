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

from config import feature_audience, is_owner
from config.keyboards import main_menu
from services.routing import register
from services.utils.callback_notifications import CallbackNoticeIntent, notify_callback
from services.utils.formatting import escape_mdv2
from services.utils.helpers import _edit_or_send, _send_with_retry

# Static, hardcoded learner-facing literals. Sentinels (@@BOT@@ / @@START@@)
# and guillemets (« ») are tokenized into spans by _render_help_template, which
# scopes escaping to leaf content — the result is always valid MarkdownV2.
# There are no dynamic (AI/DB/user) values in help content.
_HELP_INTRO = (
    "سلام! من @@BOT@@ هستم — رباتی که با هوش مصنوعی بهت واژه، مثال و نکته‌ی "
    "گرامری یاد می‌ده و با مرور فاصله‌دار کمکت می‌کنه که چیزایی که یاد گرفتی "
    "رو فراموش نکنی.\n\n"
    "چطور استفاده کنم؟\n"
    "▫️ از دکمه‌های منوی پایین یا دستورات استفاده کن.\n"
    "▫️ با زدن @@START@@ تنظیماتت رو (زبان، هدف، سطح) تنظیم کن.\n\n"
    "برای جزئیات هر بخش، دکمه‌ی مربوطه رو بزن 👇"
)

# id, button label, bold heading, body — all raw Persian (tokenized at build).
# Bold emphasis inside a body uses guillemets (« ») — see _help_guillemets.
HELP_SECTIONS = [
    {
        "id": "about",
        "label": "\U0001F331 درباره هم‌زبان",
        "title": "درباره هم‌زبان",
        "body": (
            "\U0001F331 «درووود! من هم‌زبانم» 👋\n\n"
            "همون‌طور که از اسمم پیداست، قراره هم‌زبونت باشم تو مسیر یادگیری زبان 💬\n\n"
            "\U0001F4DA هر روز که یه نشست مطالعه شروع می‌کنی:\n"
            "✨ کلمه‌های جدید یادت می‌دم\n"
            "🔁 کلمه‌هایی که تازه یاد گرفتی و ممکنه یادت بره رو، دقیقاً سروقت آماده مرور می‌کنم\n\n"
            "\U0001F5C2 تو هر کارت اینا رو می‌بینی:\n"
            "\U0001F4D6 معنی + توضیح کوتاه\n"
            "✍️ دو مثال کاربردی\n"
            "\U0001F3AD مترادف‌ها / متضادها\n"
            "\U0001F4DD نکته‌های گرامری مرتبط\n"
            "\U0001F50A امکان شنیدن تلفظ\n\n"
            "\U0001F3AF هدف اصلیم: کمکت کنم واقعاً با زبانی که داری یاد می‌گیری درگیر بشی، نه این که فقط حفظ کنی و فراموش کنی.\n\n"
            "«همه‌چیز در این سفر شخصی‌سازی شده‌ست:»\n"
            "   ⚙️ زبان، هدف (مثل ✈️ مهاجرت، \U0001F4DA کنکور) و سطحت رو بهم بگو تا محتوا مخصوص خودت بشه.\n"
            "   ❓ هر کلمه‌ی جدید یا سختی که دیدی رو بپرس؛ کارت کاملشو می‌سازم و می‌تونی تو جعبه‌ی مرورت بذاری تا در جلسات آینده بهت یادش بدم! \U0001F4E5"
        ),
    },
    {
        "id": "settings",
        "label": "👤 پروفایل و تنظیمات",
        "title": "پروفایل و تنظیمات",
        "body": (
            "اینجا همه‌چیز دست خودته:\n"
            "▫️ زبان و هدفت (مثل مهاجرت، کار یا آزمون)\n"
            "▫️ سطحت\n"
            "▫️ تیک‌های نمایش کارت — هر ردیف رو بزن تا ✅ یا ⭕ شه\n\n"
            "مواردی که مدیر قفل کرده با 🔒 نشون داده می‌شه.\n"
            "تیک‌ها برای همه فعاله، ولی بعضی گزینه‌های جزئی فقط با برنزی به بالا قابل تغییره.\n\n"
            "استریک روزانه و تعداد واژه‌های آماده‌ی مرور رو هم همین‌جا می‌بینی.\n\n"
            "روش: دکمه‌ی «👤 پروفایل و تنظیمات» رو بزن."
        ),
    },
    {
        "id": "study",
        "label": "📚 شروع مطالعه",
        "title": "شروع مطالعه",
        "body": (
            "هر روز به اندازه‌ی سهمیه‌ی پلنت کارت می‌گیری:\n"
            "▫️ ✨ واژه‌های جدید\n"
            "▫️ 🔁 واژه‌هایی که موعد مرورشون رسیده\n\n"
            "هر کارت رو اول «نمایش پاسخ» می‌زنی، بعد ۴ تا گزینه داری:\n"
            "▫️ برای مرور: از «یادم نیامد» تا «خیلی راحت بود»\n"
            "▫️ برای واژه‌ی جدید: از «کاملاً ناآشنا» تا «کاملاً بلدم»\n\n"
            "آخر سر هم گزارش همون جلسه رو می‌بینی.\n\n"
            "روش: دکمه‌ی «📚 شروع مطالعه» رو از منوی پایین بزن."
        ),
    },
    {
        "id": "ask",
        "label": "❓ پرسش واژه/عبارت",
        "title": "پرسش واژه/عبارت",
        "body": (
            "یه واژه یا عبارت کوتاه برام بفرست، کارت کاملش رو می‌سازم:\n"
            "▫️ معنی\n"
            "▫️ مثال + ترجمه‌ی مثال‌ها\n"
            "▫️ تلفظ\n\n"
            "با «ذخیره برای مطالعه» می‌ذاریش تو جعبه‌ی مرورت.\n"
            "پرسش سقف روزانه داره. اگه قبلاً پرسیده باشیش، می‌پرسم کارت جدید با سهمیه بسازم یا همون قبلی رو رایگان نشونت بدم.\n\n"
            "روش: دکمه‌ی «❓ پرسش واژه/عبارت» رو بزن و واژه‌ات رو بنویس."
        ),
    },
    {
        "id": "review",
        "label": "🔁 مرور واژه‌های ذخیره‌شده",
        "title": "مرور واژه‌های ذخیره‌شده",
        "body": (
            "واژه‌هایی که به مرور اضافه کردی اینجا جمع می‌شن. هر روز واژه‌هایی "
            "که موعد مرورشون رسیده برات میاد و با ۴ دکمه ارزیابی‌شون کن تا طبق "
            "الگوریتم فاصله‌دار زمانِ مرور بعدی تنظیم بشه.\n\n"
            "روش: از داخل «شروع مطالعه» وارد مرور می‌شی."
        ),
        "hidden": True,  # deactivated from the help panel for now
    },
    {
        "id": "tts",
        "label": "🔊 تلفظ (TTS)",
        "title": "تلفظ (TTS)",
        "body": (
            "روی هر کارت دکمه‌ی 🔊 رو بزن تا تلفظ همون واژه یا مثال رو به صورت ویس "
            f"برات بفرستم. این قابلیت {feature_audience('pronounce')} فعاله."
        ),
    },
    {
        "id": "reports",
        "label": "📋 گزارش‌ها (/reports)",
        "title": "گزارش‌ها",
        "body": (
            "بعد از هر «📚 شروع مطالعه» گزارش همون جلسه ذخیره می‌شه:\n"
            "▫️ خلاصه برای همه\n"
            "▫️ جزئیات صفحه‌به‌صفحه فقط برای برنزی به بالا\n\n"
            "آرشیو ۳ روز اخیر رو با /reports می‌بینی.\n\n"
            "روش: دستور /reports رو بزن تا فهرست گزارش‌هات بیاد، بعد با «جزئیات» و «بازگشت به فهرست» جابه‌جا شو."
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
    return [
        s
        for s in HELP_SECTIONS
        if (not s.get("owner_only") or is_owner(user_id)) and not s.get("hidden")
    ]


def _build_intro() -> str:
    """Render the help intro via the span tree (R3).

    The old ``@@BOT@@`` / ``@@START@@`` sentinels and the guillemet-based
    ``_apply_bold`` are gone: bold/code emphasis is expressed structurally, so
    escaping is scoped to leaf content and the resulting MarkdownV2 is always
    valid regardless of ``.`` ``!`` ``(`` ``)`` in the static text.
    """
    return _render_help_template(_HELP_INTRO)


def _render_help_template(template: str) -> str:
    """Tokenize a help template (with ``@@BOT@@`` / ``@@START@@`` sentinels and
    guillemet pairs « ») into spans and render them to MarkdownV2.

    Static text is emitted as ``plain()`` (escaped); ``@@BOT@@`` becomes a bold
    span of the bot name, ``@@START@@`` a ``code`` span, and a guillemet pair
    wraps its content in a ``bold`` span. Returns the final MarkdownV2 string.
    """
    from services.send_pretty import Message, bold, code, plain

    spans = _help_spans(template)
    msg = Message()
    msg.add_line(*spans)
    return msg.render()


def _help_spans(template: str) -> list:
    """Convert a help template into a flat list of span leaves.

    Single-pass tokenizer: splits on ``@@BOT@@`` then ``@@START@@``, and converts
    guillemet pairs (« … ») into ``bold`` spans within each segment. Returns a
    flat list of spans ready for ``Message.add_line``.
    """
    from services.send_pretty import bold, code, plain

    tokens: list = []

    def push_bold(inner: str) -> None:
        tokens.append(bold(inner))

    def push_plain(text: str) -> None:
        tokens.append(plain(text))

    def push_start() -> None:
        tokens.append(code("/start"))

    # Split on the BOT sentinel.
    bot_parts = template.split("@@BOT@@")
    for i, part in enumerate(bot_parts):
        if i > 0:
            tokens.append(bold("هم‌زبان"))
        # Within the segment, split on the START sentinel.
        start_parts = part.split("@@START@@")
        for j, seg in enumerate(start_parts):
            if j > 0:
                push_start()
            _help_guillemets(seg, push_plain, push_bold)

    return tokens


def _help_guillemets(text: str, push_plain, push_bold) -> None:
    """Emit spans for one segment, converting guillemet pairs to bold."""
    if not text:
        return
    for k, chunk in enumerate(text.split("\u00ab")):
        if k == 0:
            if chunk:
                push_plain(chunk)
            continue
        if "\u00bb" in chunk:
            inner, rest = chunk.split("\u00bb", 1)
            push_bold(inner)
            if rest:
                push_plain(rest)
        else:
            push_plain("\u00ab" + chunk)


def _build_section_detail(section_id: str) -> str | None:
    """Render a help section as a bold title + tokenized body (R3)."""
    for section in HELP_SECTIONS:
        if section["id"] == section_id:
            body = _render_help_template(section["body"])
            return f"*{escape_mdv2(section['title'])}*\n\n{body}"
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


async def _route_help(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    """Registry adapter for ``help:*`` (REF1-T4, R1 coarse).

    Rebuilds the full ``help:...`` data expected by ``handle_help_callback``
    (same adapter shape as ``admin._route_llm``).
    """
    await handle_help_callback(update, context, f"help:{action}")


register("help", _route_help)
