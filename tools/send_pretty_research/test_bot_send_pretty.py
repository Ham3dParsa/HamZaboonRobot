"""Demo / research script for ``services/send_pretty.py``.

Drop your bot token in ``BOT_TOKEN`` below, run the script, then open a chat
with the bot on Telegram.  Send ``/start`` to see the demo menu and tap each
button to receive a message built with a different combination of spans,
backends, and delivery verbs.

Nothing is persisted, no DB is touched — this is a pure outbound-formatting
showcase.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ──────────────────────────────────────────────────────────────────────────────
# 🔑  Paste your real bot token here (for research / fun only)
# ──────────────────────────────────────────────────────────────────────────────
BOT_TOKEN = "7564274686:AAGhm_c_5nbDtue1Z0kATaoPpLhOejglq4E"

# Target chat for the `sendall` mode. Set to your user id (or a group id).
CHAT_ID = 0

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("send_pretty_demo")

# ──────────────────────────────────────────────────────────────────────────────
# Research-sandbox import: load the local fixed copy of send_pretty from this
# same directory (tools/send_pretty_research), not the worktree module.  This
# lets us experiment with send_pretty changes without touching the worktree.
# ──────────────────────────────────────────────────────────────────────────────
import os as _os  # noqa: E402
import sys as _sys  # noqa: E402
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from send_pretty import (  # noqa: E402  (after logging setup)
    Backend,
    Bold,
    Code,
    Italic,
    Link,
    Message,
    Newline,
    Plain,
    Quote,
    RawFormat,
    Spoiler,
    bold,
    code,
    italic,
    line,
    link,
    nl,
    plain,
    quote,
    send,
    spoiler,
)

# ──────────────────────────────────────────────────────────────────────────────
# Inline keyboard — one button per demo section
# ──────────────────────────────────────────────────────────────────────────────
DEMO_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("📝  Basic Spans", callback_data="demo:basic")],
        [InlineKeyboardButton("🧩  Deep Nesting", callback_data="demo:nested")],
        [InlineKeyboardButton("👁️  Spoiler", callback_data="demo:spoiler")],
        [InlineKeyboardButton("🔗  Link", callback_data="demo:link")],
        [InlineKeyboardButton("💬  Quote + Newline", callback_data="demo:quote")],
        [InlineKeyboardButton("⚠️  Special-chars escaping", callback_data="demo:escape")],
        [InlineKeyboardButton("🇮🇷  Persian + English mixed", callback_data="demo:persian")],
        [InlineKeyboardButton("🌐  HTML backend", callback_data="demo:html")],
        [InlineKeyboardButton("📄  PLAIN backend", callback_data="demo:plain")],
        [InlineKeyboardButton("🔩  Raw pre-formatted", callback_data="demo:raw")],
        [InlineKeyboardButton("🔘  Keyboard attached", callback_data="demo:keyboard")],
        [InlineKeyboardButton("❌  Error demos", callback_data="demo:errors")],
        [InlineKeyboardButton("🚀  Send all (no callback)", callback_data="demo:all")],
    ]
)

BACK_BUTTON = InlineKeyboardMarkup(
    [[InlineKeyboardButton("«  Back to menu", callback_data="demo:menu")]]
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


async def _reply(update: Update, content, *, raw: RawFormat | None = None, **kw):
    """Thin wrapper around ``send_pretty.send`` bound to the current chat."""
    await send(
        update.effective_chat.id,
        content,
        bot=update.get_bot(),
        raw=raw,
        **kw,
    )


def _section_header(text: str) -> Message:
    m = Message()
    m.add_line(bold(plain(text)))
    return m


# ──────────────────────────────────────────────────────────────────────────────
# Demo builders — each returns a ``Message`` (or raw string + RawFormat)
# ──────────────────────────────────────────────────────────────────────────────


def demo_basic() -> Message:
    m = _section_header("1 · Basic Spans  (one span per line)")
    m.add_line(plain("Plain text — no formatting."))
    m.add_line(bold("Bold text"))
    m.add_line(italic("Italic text"))
    m.add_line(code("print('hello')"))
    m.add_line(bold(plain("Bold + "), italic(plain("BoldItalic"))))
    m.add_line(nl())
    m.add_line(plain("Each span auto-escapes its own content."))
    return m


def demo_nested() -> Message:
    m = _section_header(
        "2 · Deep Nesting  (HTML backend — only one that nests spoilers)"
    )
    m.add_line(
        quote(
            bold(plain("Rule: ")),
            plain("Any container can hold any other container."),
        )
    )
    m.add_line(
        quote(
            link(
                "https://github.com/Ham3dParsa/HamZaboonRobot",
                bold(
                    italic(plain("⭐  Star the repo")),
                ),
            )
        )
    )
    m.add_line(
        spoiler(
            quote(
                bold(plain("Secret quote: ")),
                italic(plain("the answer is 42")),
                nl(),
                code("echo $SECRET"),
            )
        )
    )
    m.add_line(
        bold(
            plain("A "),
            spoiler(
                link(
                    "https://example.com",
                    code("hidden link"),
                )
            ),
            plain(" wrapped in bold."),
        )
    )
    m.add_line(nl())
    m.add_line(plain("Max demonstrated depth: Bold → Spoiler → Link → Code (4 levels)"))
    return m


def demo_spoiler() -> Message:
    m = _section_header("3 · Spoiler  (tap to reveal)")
    m.add_line(plain("The answer is "))
    m.add_line(spoiler(plain("42")))
    m.add_line(plain(" — spoiler hides the value until the user taps it."))
    m.add_line(nl())
    m.add_line(
        bold(
            plain("A "),
            spoiler(plain("secret")),
            plain(" inside bold text."),
        )
    )
    m.add_line(nl())
    m.add_line(plain("Spoiler can wrap any nested content."))
    return m


def demo_link() -> Message:
    m = _section_header("4 · Link  (clickable URL)")
    m.add_line(
        link(
            "https://t.me/HamZaboonRobot",
            plain("👉  Open HamZaboon on Telegram"),
        )
    )
    m.add_line(
        bold(
            link(
                "https://github.com/Ham3dParsa/HamZaboonRobot",
                plain("⭐  Star the repo"),
            )
        )
    )
    m.add_line(
        link(
            "https://python.org",
            code("python.org"),
        )
    )
    m.add_line(nl())
    m.add_line(plain("URLs are escaped automatically; no entity injection possible."))
    return m


def demo_quote() -> Message:
    m = _section_header('5 · Quote + Newline  ("> " prefix / <blockquote>)')
    m.add_line(
        quote(
            bold(plain("Persian proverb: ")),
            plain("کتاب دوست، دوست نیکوست."),
        )
    )
    m.add_line(
        quote(
            plain("A wise person once said:\n"),
            italic(plain("Learn every day,")),
            nl(),
            italic(plain("grow every day.")),
        )
    )
    m.add_line(
        quote(
            bold(code("git commit -m 'ship it'")),
        )
    )
    m.add_line(nl())
    m.add_line(plain("Quotes can contain newlines, bold, italic, and code spans."))
    return m


def demo_escape() -> Message:
    m = _section_header('6 · Special-chars escaping  (MarkdownV2)')
    m.add_line(
        plain(
            "These chars would break MDV2 if sent raw: "
            "* _ ` [ ] ( ) ~ > # + - = | { } . !"
        )
    )
    m.add_line(
        bold(
            plain("But send_pretty escapes every leaf automatically:\n"),
            plain("*_`[]()...*_`[]()..."),
        )
    )
    m.add_line(nl())
    m.add_line(plain("Bold line with * asterisks: "), bold(plain("2 * 3 = 6")))
    m.add_line(plain("Code with backticks: "), code("`backtick` inside code span"))
    m.add_line(plain("URL with brackets: "), link("https://x.com/(handle)", plain("profile")))
    return m


def demo_persian() -> Message:
    m = _section_header("7 · Persian + English mixed  (RTL + LTR)")
    m.add_line(plain("سلام!  Welcome to HamZaboon  👋"))
    m.add_line(bold(plain("واژهٔ today:  «spoon»")))
    m.add_line(
        quote(
            plain("نکته‌ی گرامری:\n"),
            italic(
                plain(
                    "Past continuous: من کتاب می‌خواندم = I was reading a book."
                )
            ),
        )
    )
    m.add_line(
        bold(
            plain("مترادف‌ها: "),
            italic(plain("happy → joyful, cheerful, delighted")),
        )
    )
    m.add_line(
        link(
            "https://fa.wikipedia.org/wiki/%D9%88%DB%8C%DA%A9%DB%8C",
            plain("📖  ویکی‌پدیای فارسی"),
        )
    )
    return m


def demo_html() -> Message:
    """HTML backend — rendered with <b>, <i>, <code>, <blockquote>, etc."""
    m = Message()
    m.add_line(bold(plain("HTML backend — rendered as HTML entities")))
    m.add_line(plain("Dynamic values like <user> are html_escaped automatically."))
    m.add_line(
        quote(
            bold(plain("Quoted ")),
            italic(plain("in HTML <blockquote> tags.")),
        )
    )
    m.add_line(
        link(
            "https://example.com",
            code("clickable code link"),
        )
    )
    text = m.render(Backend.HTML)
    return text, RawFormat.HTML


def demo_plain() -> Message:
    """PLAIN backend — all markup stripped, only text survives."""
    m = Message()
    m.add_line(bold(plain("PLAIN backend — no markup at all")))
    m.add_line(italic(plain("Italic becomes plain text")))
    m.add_line(code("print('code span loses backticks')"))
    m.add_line(
        quote(
            bold(plain("Quoted text — only content survives.")),
        )
    )
    text = m.render(Backend.PLAIN)
    return text, RawFormat.PLAIN


def demo_raw() -> tuple[str, RawFormat]:
    """Pre-formatted string passed via raw= — caller owns escaping.

    With raw= the module does NOT escape; the caller must produce valid
    MarkdownV2.  The hyphen in 'User-provided' and the trailing period are
    reserved chars, so they are escaped as \\- and \\. here.
    """
    raw_mdv2 = (
        r"*User\-provided MDV2*" + "\n"
        r"Already formatted, no span tree — caller must escape themselves\."
    )
    return raw_mdv2, RawFormat.MDV2


def demo_keyboard() -> Message:
    m = _section_header("🔘  This message has an inline keyboard attached")
    m.add_line(plain("The buttons below were set with msg.set_keyboard():"))
    m.add_line(nl())
    m.add_line(bold(plain("send_pretty automatically picks up msg.keyboard")))
    m.add_line(plain("No need to pass keyboard= separately."))
    m.set_keyboard(
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("👍  Like", callback_data="demo:like"),
                    InlineKeyboardButton("👎  Dislike", callback_data="demo:dislike"),
                ],
                [
                    InlineKeyboardButton("«  Menu", callback_data="demo:menu"),
                ],
            ]
        )
    )
    return m


# ──────────────────────────────────────────────────────────────────────────────
# Vocab flash-card variations  (/cards)
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_CARD = {
    "word": "controversial",
    "ipa": "/ˌkɑːntrəˈvɜːrʃl/",
    "fa_meaning": "بحث‌انگیز، جنجالی، پرمناقشه",
    "fa_explanation": (
        "صفت؛ به موضوعات، تصمیمات یا افرادی اطلاق می‌شود که باعث بروز اختلافات "
        "شدید، مباحثات پرشور و نظرات کاملاً متضاد در افکار عمومی یا میان متخصصان می‌شوند."
    ),
    "synonyms": ["contentious", "polemical", "disputable"],
    "antonyms": ["uncontroversial", "uncontested", "indisputable"],
    "examples": [
        "The government's decision to implement the new tax policy proved "
        "highly controversial among small business owners.",
        "He remains a controversial figure in modern literature due to his "
        "provocative themes and unconventional lifestyle.",
    ],
    "example_translations": [
        "تصمیم دولت برای اجرای سیاست جدید مالیاتی در میان صاحبان کسب‌وکارهای "
        "کوچک بسیار بحث‌انگیز از آب درآمد.",
        "او به دلیل درون‌مایه‌های تحریک‌آمیز و سبک زندگی غیرمرسومش، همچنان "
        "شخصیتی جنجالی در ادبیات معاصر باقی مانده است.",
    ],
    "grammar_tip": (
        "معمولاً با تشدیدکننده‌هایی مانند highly، deeply یا fiercely ترکیب "
        "می‌شود (مانند highly controversial). برای اشاره به موضوع از حروف اضافه "
        "over یا surrounding و برای گروه از among استفاده می‌شود."
    ),
}


def _card_syn_ant(card: dict) -> list:
    """Build the 🟢/🔴 synonym–antonym line tuples for a card."""
    antonyms = card.get("antonyms") or []
    return [
        (bold(plain("🟢 مترادف: ")), plain("، ".join(card.get("synonyms") or []) or "—")),
        (bold(plain("🔴 متضاد: ")), plain("، ".join(antonyms) or "—")),
    ]


def card_v0(card: dict) -> Message:
    """V0 · Recommended — word|ipa inline, quoted examples, spoiler translations,
    footer 'add to review' keyboard."""
    m = Message()
    m.add_line(bold(plain(card["word"])), plain(" | "), code(card["ipa"]))
    m.add_line(nl())
    m.add_line(bold(plain("✤ ")), bold(card["fa_meaning"]))
    m.add_line(plain(card["fa_explanation"]))
    m.add_line(nl())
    for head, body in _card_syn_ant(card):
        m.add_line(head, body)
    m.add_line(nl())
    m.add_line(bold(plain("📝 نمونه‌ها:")))
    for en, fa in zip(card["examples"], card["example_translations"]):
        m.add_line(
            quote(
                plain("✦ "), plain(en),
                nl(),
                spoiler(italic(plain(fa))),
            )
        )
    m.add_line(nl())
    m.add_line(bold(plain("💡 نکته‌ی گرامری:")), nl(), plain(card["grammar_tip"]))
    m.add_line(nl())
    m.set_keyboard(
        InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➕ افزودن به جعبه مرور", callback_data="card:add")],
                [InlineKeyboardButton("«  ارسال کارت برای دوستان", callback_data="card:share")],
                [InlineKeyboardButton("«  بازگشت به منو", callback_data="demo:menu")]
            ]
        )
    )
    return m


def card_v1(card: dict) -> Message:
    """V1 · Classic — faithful to the original two examples (no spoiler/quote)."""
    m = Message()
    m.add_line(bold(plain(card["word"])))
    m.add_line(code(card["ipa"]))
    m.add_line(nl())
    m.add_line(bold(plain("✤ ")), plain(card["fa_meaning"]))
    m.add_line(plain(card["fa_explanation"]))
    m.add_line(nl())
    for head, body in _card_syn_ant(card):
        m.add_line(head, body)
    m.add_line(nl())
    m.add_line(bold(plain("📝 مثال‌ها + ترجمه:")))
    for en, fa in zip(card["examples"], card["example_translations"]):
        m.add_line(plain("✦ "), plain(en))
        m.add_line(plain(fa))
    m.add_line(nl())
    m.add_line(bold(plain("✍️ نکته‌ی گرامری:")), nl(), plain(card["grammar_tip"]))
    return m


def card_v2(card: dict) -> Message:
    """V2 · Spoiler translations — user idea #1: examples in a quote, each
    Farsi translation behind a spoiler (tap to reveal)."""
    m = Message()
    m.add_line(bold(plain(card["word"])), plain(" | "), code(card["ipa"]))
    m.add_line(nl())
    m.add_line(bold(plain("✤ ")), plain(card["fa_meaning"]))
    m.add_line(plain(card["fa_explanation"]))
    m.add_line(nl())
    for head, body in _card_syn_ant(card):
        m.add_line(head, body)
    m.add_line(nl())
    m.add_line(bold(plain("📝 مثال‌ها + ترجمه (ترجمه‌ها پنهان‌اند — بزنید تا نمایان شوند):")))
    for en, fa in zip(card["examples"], card["example_translations"]):
        m.add_line(
            quote(
                plain("✦ "), plain(en),
                nl(),
                spoiler(plain(fa)),
            )
        )
    m.add_line(nl())
    m.add_line(bold(plain("✍️ نکته‌ی گرامری:")), nl(), plain(card["grammar_tip"]))
    return m


def card_v3(card: dict) -> Message:
    """V3 · Word+IPA emphasis — user idea #2: bold(word) | code(ipa) on one line
    with a divider, clean minimal body (no quote/spoiler)."""
    m = Message()
    m.add_line(bold(plain(card["word"])), plain("   |   "), code(card["ipa"]))
    m.add_line(plain("─" * 28))
    m.add_line(bold(plain("✤ ")), plain(card["fa_meaning"]))
    m.add_line(plain(card["fa_explanation"]))
    m.add_line(nl())
    for head, body in _card_syn_ant(card):
        m.add_line(head, body)
    m.add_line(nl())
    m.add_line(bold(plain("📝 مثال‌ها + ترجمه:")))
    for en, fa in zip(card["examples"], card["example_translations"]):
        m.add_line(plain("✦ "), plain(en))
        m.add_line(plain(fa))
    m.add_line(nl())
    m.add_line(bold(plain("✍️ نکته‌ی گرامری:")), nl(), plain(card["grammar_tip"]))
    return m


def card_v4(card: dict) -> Message:
    """V4 · Study mode — meaning AND translations hidden behind spoilers for
    recall practice; examples stay visible so the learner can guess."""
    m = Message()
    m.add_line(bold(plain(card["word"])), plain(" | "), code(card["ipa"]))
    m.add_line(nl())
    m.add_line(spoiler(plain(card["fa_meaning"])), plain("   ← معنی را حدس بزنید"))
    m.add_line(plain(card["fa_explanation"]))
    m.add_line(nl())
    for head, body in _card_syn_ant(card):
        m.add_line(head, body)
    m.add_line(nl())
    m.add_line(bold(plain("📝 مثال‌ها (ترجمه پنهان — حدس بزنید):")))
    for en, fa in zip(card["examples"], card["example_translations"]):
        m.add_line(
            quote(
                plain("✦ "), plain(en),
                nl(),
                spoiler(plain(fa)),
            )
        )
    m.add_line(nl())
    m.add_line(bold(plain("✍️ نکته‌ی گرامری:")), nl(), spoiler(plain(card["grammar_tip"])))
    return m


CARD_BUILDERS = [
    ("V0 · Recommended", card_v0),
    ("V1 · Classic", card_v1),
    ("V2 · Spoiler translations", card_v2),
    ("V3 · Word+IPA emphasis", card_v3),
    ("V4 · Study mode", card_v4),
]


async def send_cards_mode(bot) -> None:
    """Send all 5 flash-card layout variations for the sample card, one by one."""
    if CHAT_ID == 0:
        log.error("CHAT_ID is not set — edit the constant at the top of the script")
        return

    card = SAMPLE_CARD
    log.info("🃏  cards — sending %d variations for '%s'", len(CARD_BUILDERS), card["word"])
    sent = 0
    failed = 0
    for label, builder in CARD_BUILDERS:
        try:
            msg = builder(card)
            await send(CHAT_ID, msg, bot=bot)
            log.info("✅  [%s] sent", label)
            sent += 1
        except Exception as exc:
            log.error("❌  [%s] failed: %s", label, exc)
            failed += 1

    summary = f"🃏  cards complete — {sent} sent, {failed} failed"
    log.info(summary)
    print("\n" + summary)


async def cmd_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🃏  Sending flash-card layout variations…")
    chat_id = update.effective_chat.id
    global CHAT_ID
    original = CHAT_ID
    CHAT_ID = chat_id
    try:
        await send_cards_mode(update.get_bot())
    finally:
        CHAT_ID = original


# ──────────────────────────────────────────────────────────────────────────────
# /start and callback handlers
# ──────────────────────────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🛠  <b>send_pretty demo bot</b>\n"
        "Tap a button below to see a different formatting demo.\n"
        "Every message is built with the span-tree API and auto-escaped.",
        reply_markup=DEMO_KEYBOARD,
        parse_mode=ParseMode.HTML,
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data == "card:add":
        await query.edit_message_text(
            "✅  (demo) این واژه به مرور افزوده شد — نمایش آزمایشی.",
            reply_markup=BACK_BUTTON,
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "card:share":
        await query.answer("کارت آماده‌ی ارسال به دوستان است.", show_alert=True)
        return

    if data == "demo:menu" or not data.startswith("demo:"):
        await query.edit_message_text(
            "🛠  <b>send_pretty demo bot</b>\n"
            "Pick a section below:",
            reply_markup=DEMO_KEYBOARD,
            parse_mode=ParseMode.HTML,
        )
        return

    section = data.split(":", 1)[1]

    try:
        await _dispatch_demo(update, section)
    except Exception:
        log.exception("demo %r failed", section)
        await query.edit_message_text(
            f"❌  Demo <code>{section}</code> raised an error — check the console.",
            reply_markup=BACK_BUTTON,
            parse_mode=ParseMode.HTML,
        )


async def _dispatch_demo(update: Update, section: str) -> None:
    query = update.callback_query

    if section == "basic":
        await query.edit_message_text("⏳  Sending basic spans…")
        await _reply(update, demo_basic())

    elif section == "nested":
        await query.edit_message_text("⏳  Sending deep nesting (HTML backend)…")
        text = demo_nested().render(Backend.HTML)
        await _reply(update, text, raw=RawFormat.HTML)

    elif section == "spoiler":
        await query.edit_message_text("⏳  Sending spoiler demo…")
        await _reply(update, demo_spoiler())

    elif section == "link":
        await query.edit_message_text("⏳  Sending link demo…")
        await _reply(update, demo_link())

    elif section == "quote":
        await query.edit_message_text("⏳  Sending quote demo…")
        await _reply(update, demo_quote())

    elif section == "escape":
        await query.edit_message_text("⏳  Sending escape demo…")
        await _reply(update, demo_escape())

    elif section == "persian":
        await query.edit_message_text("⏳  Sending Persian demo…")
        await _reply(update, demo_persian())

    elif section == "html":
        await query.edit_message_text("⏳  Sending HTML-backend message…")
        text, fmt = demo_html()
        await _reply(update, text, raw=fmt)

    elif section == "plain":
        await query.edit_message_text("⏳  Sending PLAIN-backend message…")
        text, fmt = demo_plain()
        await _reply(update, text, raw=fmt)

    elif section == "raw":
        await query.edit_message_text("⏳  Sending raw pre-formatted string…")
        text, fmt = demo_raw()
        await _reply(update, text, raw=fmt)

    elif section == "keyboard":
        await query.edit_message_text("⏳  Sending message with keyboard…")
        await _reply(update, demo_keyboard())

    elif section == "errors":
        await _run_error_demos(update)
        return  # _run_error_demos already answers

    elif section == "all":
        await query.edit_message_text("🚀  Sending ALL demos in sequence…")
        await _run_all_demos(update)
        return  # _run_all_demos handles its own confirmation

    else:
        await query.edit_message_text(
            f"Unknown section: <code>{section}</code>",
            reply_markup=BACK_BUTTON,
            parse_mode=ParseMode.HTML,
        )
        return

    # Confirm with a back button after each successful demo
    try:
        await query.edit_message_text(
            "✅  Demo sent!  Pick another:",
            reply_markup=BACK_BUTTON,
            parse_mode=ParseMode.HTML,
        )
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            pass  # user tapped the same button twice — harmless
        else:
            raise


# ──────────────────────────────────────────────────────────────────────────────
# Composite flows
# ──────────────────────────────────────────────────────────────────────────────


async def _run_error_demos(update: Update) -> None:
    query = update.callback_query

    log.warning("=== Error demo 1: raw= with Message (expect TypeError) ===")
    try:
        await send(
            update.effective_chat.id,
            Message().add_line(plain("should fail")),
            bot=update.get_bot(),
            raw=RawFormat.MDV2,
        )
    except TypeError as exc:
        log.info("✓  Caught expected TypeError: %s", exc)

    log.warning("=== Error demo 2: Backend.RICH (expect NotImplementedError) ===")
    try:
        Message().render(Backend.RICH)
    except NotImplementedError as exc:
        log.info("✓  Caught expected NotImplementedError: %s", exc)

    await query.edit_message_text(
        "✅  Error demos ran — check your console/log for the caught exceptions.\n"
        "Both errors are intentional and fail loudly, as designed.",
        reply_markup=BACK_BUTTON,
        parse_mode=ParseMode.HTML,
    )


async def _run_all_demos(update: Update) -> None:
    sections = [
        ("basic", demo_basic()),
        ("nested", demo_nested()),
        ("spoiler", demo_spoiler()),
        ("link", demo_link()),
        ("quote", demo_quote()),
        ("escape", demo_escape()),
        ("persian", demo_persian()),
    ]
    for name, msg in sections:
        log.info("Sending section: %s", name)
        await _reply(update, msg)

    # HTML + PLAIN
    text, fmt = demo_html()
    await _reply(update, text, raw=fmt)
    text, fmt = demo_plain()
    await _reply(update, text, raw=fmt)

    # Raw
    text, fmt = demo_raw()
    await _reply(update, text, raw=fmt)

    # Keyboard
    await _reply(update, demo_keyboard())

    await _reply(
        update,
        _section_header("🎉  All demos sent!"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# sendall mode — fire every demo to one chat, one by one, with error handling
# ──────────────────────────────────────────────────────────────────────────────


async def _send_one_demo(bot, chat_id: int, label: str, content, raw=None) -> bool:
    """Send a single demo with isolated error handling; never abort the batch."""
    try:
        await send(chat_id, content, bot=bot, raw=raw)
        log.info("✅  [%s] sent", label)
        return True
    except Exception as exc:
        log.error("❌  [%s] failed: %s", label, exc)
        return False


async def send_all_mode(bot) -> None:
    """Send all demos sequentially to ``CHAT_ID`` with per-demo logging."""
    if CHAT_ID == 0:
        log.error("CHAT_ID is not set — edit the constant at the top of the script")
        return

    # (label, content, raw_fmt) — nested demo is pre-rendered via HTML backend.
    specs = [
        ("1 · Basic spans", demo_basic(), None),
        ("2 · Deep nesting (HTML)", demo_nested().render(Backend.HTML), RawFormat.HTML),
        ("3 · Spoiler", demo_spoiler(), None),
        ("4 · Link", demo_link(), None),
        ("5 · Quote + Newline", demo_quote(), None),
        ("6 · Special-chars escaping", demo_escape(), None),
        ("7 · Persian + English", demo_persian(), None),
        ("8 · HTML backend", *demo_html()),
        ("9 · PLAIN backend", *demo_plain()),
        ("10 · Raw pre-formatted", *demo_raw()),
        ("11 · Keyboard attached", demo_keyboard(), None),
    ]

    log.info("🚀  sendall — sending %d demos to chat %s", len(specs), CHAT_ID)
    sent = 0
    failed = 0
    for label, content, raw in specs:
        ok = await _send_one_demo(bot, CHAT_ID, label, content, raw)
        sent += int(ok)
        failed += int(not ok)

    summary = f"🏁  sendall complete — {sent} sent, {failed} failed"
    log.info(summary)
    print("\n" + summary)


async def cmd_sendall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🚀  Sending all demos to this chat…")
    chat_id = update.effective_chat.id
    global CHAT_ID
    original = CHAT_ID
    CHAT_ID = chat_id
    try:
        await send_all_mode(update.get_bot())
    finally:
        CHAT_ID = original


# ──────────────────────────────────────────────────────────────────────────────
# Render-only mode  (no Telegram bot needed)
# ──────────────────────────────────────────────────────────────────────────────


def _print_render_previews() -> None:
    """Print every demo section's rendered output to the console — no bot needed."""
    SEP = "─" * 60

    demos = [
        ("Basic spans", demo_basic()),
        ("Deep nesting", demo_nested()),
        ("Spoiler", demo_spoiler()),
        ("Link", demo_link()),
        ("Quote + Newline", demo_quote()),
        ("Special-chars escaping", demo_escape()),
        ("Persian + English", demo_persian()),
    ]

    for name, msg in demos:
        print(f"\n{SEP}")
        print(f"  {name}  (Backend.MDV2)")
        print(SEP)
        print(msg.render(Backend.MDV2))

    html_text, _ = demo_html()
    print(f"\n{SEP}")
    print("  HTML backend")
    print(SEP)
    print(html_text)

    plain_text, _ = demo_plain()
    print(f"\n{SEP}")
    print("  PLAIN backend")
    print(SEP)
    print(plain_text)

    raw_text, _ = demo_raw()
    print(f"\n{SEP}")
    print("  Raw pre-formatted (MDV2, caller-escaped)")
    print(SEP)
    print(raw_text)

    print(f"\n{SEP}")
    print("  Keyboard demo (Message object — no bot needed for render)")
    print(SEP)
    kb_demo = demo_keyboard()
    print(kb_demo.render(Backend.MDV2))
    print(f"\n  ↳ keyboard attached: {kb_demo.keyboard!r}")


# ──────────────────────────────────────────────────────────────────────────────
# Entry-point
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "preview":
        print("📄  Render-only mode — no Telegram bot started.\n")
        _print_render_previews()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "sendall":
        if CHAT_ID == 0:
            print(
                "❌  Edit CHAT_ID at the top of this script before running sendall mode.\n"
                "    Or send /sendall to the live bot and it uses the chat you're in."
            )
            return

        async def _run_sendall():
            print("🚀  Starting sendall mode…")
            app = ApplicationBuilder().token(BOT_TOKEN).build()
            async with app:
                await send_all_mode(app.bot)

        asyncio.run(_run_sendall())
        return

    if len(sys.argv) > 1 and sys.argv[1] == "cards":
        if CHAT_ID == 0:
            print(
                "❌  Edit CHAT_ID at the top of this script before running cards mode.\n"
                "    Or send /cards to the live bot and it uses the chat you're in."
            )
            return

        async def _run_cards():
            print("🃏  Starting cards mode…")
            app = ApplicationBuilder().token(BOT_TOKEN).build()
            async with app:
                await send_cards_mode(app.bot)

        asyncio.run(_run_cards())
        return

    if not BOT_TOKEN or BOT_TOKEN == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11":
        print(
            "❌  Edit BOT_TOKEN at the top of this script before running live mode.\n"
            "    Or run with:  python test_bot_send_pretty.py preview"
        )
        return

    print("🤖  Starting send_pretty demo bot…")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sendall", cmd_sendall))
    app.add_handler(CommandHandler("cards", cmd_cards))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^demo:"))

    print("✅  Bot is up — open a chat with it and send /start (or /sendall)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
