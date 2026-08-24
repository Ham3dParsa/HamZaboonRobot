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
    CustomEmoji,
    Details,
    Heading,
    Table,
    List,
    ListItem,
    TaskListItem,
    Math,
    Raw,
    Underline,
    Strikethrough,
    Marked,
    TgSpoiler,
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
    underline,
    strike,
    mark,
    tg_spoiler,
    emoji,
    heading,
    table,
    rich_list,
    details,
    math,
    raw_rich,
    telegram_rich,
)

# ──────────────────────────────────────────────────────────────────────────────
# 🔥 Rich Message research toggle
# When True, the demo actually calls sendRichMessage (Bot API 10.1). A 404
# capability latch inside telegram_rich disables Rich for this bot after the
# first unsupported probe, falling back to MarkdownV2/plain — so an old or
# local Bot API server is only hit once. Flip to False to force the MDV2
# fallback path and never call the raw endpoint.
# ──────────────────────────────────────────────────────────────────────────────
RICH_ON = True
telegram_rich.RICH_ENABLED = RICH_ON

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
        [InlineKeyboardButton("📋  REPORT session (Rich)", callback_data="demo:report")],
        [InlineKeyboardButton("📋  REPORT v2 (structured)", callback_data="demo:report_v2")],
        [InlineKeyboardButton("🔥  Rich Messages (one-by-one)", callback_data="demo:rich")],
        [InlineKeyboardButton("❌  Error demos", callback_data="demo:errors")],
        [InlineKeyboardButton("🚀  Send all (no callback)", callback_data="demo:all")],
    ]
)

BACK_BUTTON = InlineKeyboardMarkup(
    [[InlineKeyboardButton("«  Back to menu", callback_data="demo:menu")]]
)

RICH_MENU = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🔠  Heading", callback_data="demo:rich_heading")],
        [InlineKeyboardButton("📊  Table", callback_data="demo:rich_table")],
        [InlineKeyboardButton("📋  List (unordered/ordered)", callback_data="demo:rich_list")],
        [InlineKeyboardButton("✅  Task list", callback_data="demo:rich_task")],
        [InlineKeyboardButton("📂  Details (spoiler/disclosure)", callback_data="demo:rich_details")],
        [InlineKeyboardButton("∑  Math", callback_data="demo:rich_math")],
        [InlineKeyboardButton("😀  Custom emoji", callback_data="demo:rich_emoji")],
        [InlineKeyboardButton("😀  Custom emoji in BUTTONS", callback_data="demo:rich_emoji_btn")],
        [InlineKeyboardButton("🃏  Flash card (Rich + template)", callback_data="demo:rich_card")],
        [InlineKeyboardButton("🃏🃏  Flash card VARIATIONS", callback_data="demo:rich_cards")],
        [InlineKeyboardButton("🗂  SESSION cards", callback_data="demo:sessions")],
        [InlineKeyboardButton("▶  Run ALL rich demos", callback_data="demo:rich_all")],
        [InlineKeyboardButton("«  Back to main menu", callback_data="demo:rich_main")],
    ]
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
# 🔥 Rich Message demos — one element per message, so we can see exactly what
# renders against the live Bot API 10.1 server and what falls back.  Every demo
# is sent with backend=Backend.RICH; telegram_rich routes to sendRichMessage
# (or falls back to MDV2/plain on 404 / BadRequest).
# ──────────────────────────────────────────────────────────────────────────────


def _rich_header(text: str) -> Message:
    m = Message()
    m.add_line(bold(plain(text)))
    m.add_line(plain(f"backend=Backend.RICH  ·  RICH_ENABLED={RICH_ON}"))
    m.add_line(nl())
    return m


def demo_rich_heading() -> Message:
    m = _rich_header("🔠  Rich · Heading")
    m.add_line(heading(1, plain("Heading 1 — title")))
    m.add_line(heading(2, plain("Heading 2 — کتاب"), italic(plain("  (ketâb)"))))
    m.add_line(heading(3, plain("Heading 3 — smaller")))
    m.add_line(nl())
    m.add_line(plain("Headings render as larger/bolder text in a Rich Message."))
    return m


def demo_rich_table() -> Message:
    m = _rich_header("📊  Rich · Table")
    m.add_line(
        table(
            (plain("English"), plain("Persian")),
            (plain("book"), plain("کتاب")),
            (plain("controversial"), plain("بحث‌انگیز")),
            (plain("house"), plain("خانه")),
        )
    )
    m.add_line(nl())
    m.add_line(plain("A GFM pipe table — aligned columns, header row."))
    return m


def demo_rich_list() -> Message:
    m = _rich_header("📋  Rich · List")
    m.add_line(plain("Unordered:"))
    m.add_line(
        rich_list(
            False,
            ListItem(plain("First item")),
            ListItem(plain("Second item — کتاب")),
        )
    )
    m.add_line(plain("Ordered:"))
    m.add_line(
        rich_list(
            True,
            ListItem(plain("Step one")),
            ListItem(plain("Step two")),
        )
    )
    return m


def demo_rich_task() -> Message:
    m = _rich_header("✅  Rich · Task list")
    m.add_line(
        rich_list(
            False,
            TaskListItem(True, plain("Mastered today")),
            TaskListItem(False, plain("Review tomorrow")),
            TaskListItem(True, plain("Saved to review box")),
        )
    )
    m.add_line(nl())
    m.add_line(plain("[x] = checked, [ ] = unchecked."))
    return m


def demo_rich_details() -> Message:
    m = _rich_header("📂  Rich · Details (spoiler/disclosure)")
    m.add_line(
        details(
            plain("💡 نکته‌ی گرامری:"),
            plain(
                "معمولاً با تشدیدکننده‌هایی مانند highly، deeply یا fiercely ترکیب "
                "می‌شود (مانند highly controversial)."
            ),
        )
    )
    m.add_line(nl())
    m.add_line(plain("Tap the summary to expand the hidden body."))
    return m


def demo_rich_math() -> Message:
    m = _rich_header("∑  Rich · Math")
    m.add_line(plain("Inline: "), math("E = mc^2"))
    m.add_line(nl())
    m.add_line(plain("Block:"))
    m.add_line(math("\\int_0^1 x^2\\,dx = \\frac{1}{3}", block=True))
    return m


def demo_rich_emoji() -> Message:
    m = _rich_header("😀  Rich · Custom emoji (message body)")
    m.add_line(plain("Custom emoji span: "), emoji("book"))
    m.add_line(nl())
    m.add_line(
        plain(
            "Fallback 📖 shows if the registry has no real id or the bot "
            "lacks Premium (message-body custom emoji needs Premium)."
        )
    )
    return m


def demo_rich_emoji_buttons() -> Message:
    """Custom emoji in INLINE BUTTONS reportedly does NOT need Premium (unlike
    message-body custom emoji).  Experimental: the button text uses the same
    tg://emoji markdown.  Watch whether the emoji actually renders on the
    button — if it shows as raw text, the client didn't accept it."""
    cid, fb = "5350716797622442220", "▶"
    m = _rich_header("😀  Rich · Custom emoji in BUTTONS")
    m.add_line(plain("These buttons try to render a custom emoji in their text."))
    m.add_line(plain("Buttons reportedly don't need Premium — only message-body does."))
    m.add_line(nl())
    m.add_line(plain("Tap a button:"))
    m.set_keyboard(
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=f"![{fb}](tg://emoji?id={cid}) Start",
                        callback_data="demo:like",
                    ),
                    InlineKeyboardButton(
                        text=f"![{fb}](tg://emoji?id={cid}) Back",
                        callback_data="demo:rich_menu",
                    ),
                ],
                [InlineKeyboardButton(text="«  Menu", callback_data="demo:rich_main")],
            ]
        )
    )
    return m


def card_h(card: dict) -> Message:
    """H · Exact feedback — table card with PLAIN translations (in-table spoilers
    render empty on Telegram, so no spoilers there), collapsible examples table,
    word as level-2 heading, meaning as level-3 heading, grammar as a plain-summary
    Details (no bold → no literal asterisks)."""
    rows = _rich_head(card) + _card_syn_ant(card)
    rows.append(_examples_section(card, highlight=True))
    rows.append(_grammar_row(card))
    return _message_from(*rows)


# ──────────────────────────────────────────────────────────────────────────────
# Rich flash-card VARIATIONS  (/cardsrich)
# ──────────────────────────────────────────────────────────────────────────────

def _rich_head(card) -> list:
    """Word as a level-2 heading, ipa normal-size under it, meaning as a level-3
    heading, explanation as a paragraph."""
    return [
        (heading(2, plain(card["word"])),),
        (code(card["ipa"]),),
        (heading(3, plain("✤ "), plain(card["fa_meaning"])),),
        (plain(card["fa_explanation"]),),
    ]


_LRE = "\u202A"  # Unicode LEFT-TO-RIGHT embedding (invisible, forces LTR on a cell)
_RLE = "\u202B"  # Unicode RIGHT-TO-LEFT embedding (invisible, forces RTL on a cell)
_PDF = "\u202C"  # Unicode POP DIRECTIONAL FORMATTING (ends an embedding)


def _split_on_word(sentence: str, word: str) -> tuple[str, str, str]:
    """Split ``sentence`` into (before, word, after) around the first
    case-insensitive occurrence of ``word``.  Returns empty word parts when absent."""
    if not word:
        return sentence, "", ""
    idx = sentence.lower().find(word.lower())
    if idx < 0:
        return sentence, "", ""
    return sentence[:idx], sentence[idx:idx + len(word)], sentence[idx + len(word):]


def _highlight_ltr_cell(sentence: str, word: str) -> tuple:
    """Cell spans: an English sentence forced LTR (invisible BiDi) with the target
    word bolded.  Bold renders fine inside a Markdown table cell (mira-confirmed);
    a literal '|' must never sit inside the bold, or the table breaks."""
    before, hit, after = _split_on_word(sentence, word)
    parts = [plain(_LRE + before)]
    if hit:
        parts.append(bold(plain(hit)))
    parts.append(plain(after + _PDF))
    return tuple(parts)


def _highlight_fa_cell(text: str, meaning: str) -> tuple:
    """A Persian translation cell forced RTL with the first meaning word that
    actually appears in the text bolded (so the Persian meaning is highlighted
    too, not just the English keyword)."""
    candidates = [meaning] + [w.strip() for w in meaning.split("،") if w.strip()]
    target = next((c for c in candidates if c in text), "")
    before, hit, after = _split_on_word(text, target)
    parts = [plain(_RLE + before)]
    if hit:
        parts.append(bold(plain(hit)))
    parts.append(plain(after + _PDF))
    return tuple(parts)


def _examples_table(card, *, highlight: bool = False) -> Table:
    """Two-column table — sample sentence | translation.  With ``highlight=True``
    the flashcard word is bolded inside each English sentence AND the Persian
    meaning word inside each translation; both columns get invisible BiDi
    direction control.  Otherwise identical to the pre-findings look (so S·3
    stays byte-identical)."""
    header = (plain("جمله نمونه"), plain("ترجمه"))
    if highlight:
        rows = tuple(
            (
                _highlight_ltr_cell(en, card["word"]),
                _highlight_fa_cell(fa, card["fa_meaning"]),
            )
            for en, fa in zip(card["examples"], card["example_translations"])
        )
    else:
        rows = tuple(
            (plain(en), plain(fa))
            for en, fa in zip(card["examples"], card["example_translations"])
        )
    return Table(header=header, rows=rows)


def _examples_lines_spoiler(card) -> list:
    """✦ English line + Persian translation behind a spoiler (on its own line).
    Used by study mode, where translations must be hidden (a table cannot hide
    its cells, and spoilers don't render inside table cells)."""
    rows = [(bold(plain("📝 مثال‌ها (ترجمه‌ها پنهان‌اند — بزنید تا ببینید):")),)]
    for en, fa in zip(card["examples"], card["example_translations"]):
        rows.append((plain("✦ "),) + _highlight_ltr_cell(en, card["word"]))
        rows.append((spoiler(plain(fa)),))
    return rows


def _examples_section(card, *, highlight: bool = False) -> tuple:
    """The examples + translations TABLE, always visible.

    A markdown TABLE cannot live inside ``<details>``: Telegram Rich renders
    ``<details>`` content as plain text (not re-parsed), so a collapsible table
    shows raw ``|`` pipes when expanded. Grammar/explanation Details are fine
    because they are plain text; the table must stay outside any Details.
    """
    return (_examples_table(card, highlight=highlight),)


def _explanation_details(card, *, open: bool = False) -> tuple:
    """The Persian explanation wrapped in a collapsible Details."""
    return (details(plain("📖 توضیح فارسی:"), plain(card["fa_explanation"]), open=open),)


def _grammar_row(card) -> tuple:
    # Summary and body must be PLAIN — Telegram Rich does not parse bold or
    # spoiler inside <details>, so markers would show literally.
    return (details(plain("💡 نکته‌ی گرامری:"), plain(card["grammar_tip"])),)


def _message_from(*rows) -> Message:
    m = Message()
    for row in rows:
        m.add_line(*row)
    return m


def _labelled_card(label: str, m: Message) -> Message:
    out = Message()
    out.add_line(italic(plain(label)))
    out._lines.extend(m._lines)
    return out


def card_h_compact(card) -> Message:
    """H·1 Compact — explanation folded into a collapsible Details (leaner card
    that still offers the Persian explanation on tap)."""
    rows = [
        (heading(2, plain(card["word"])),),
        (code(card["ipa"]),),
        (heading(3, plain("✤ "), plain(card["fa_meaning"])),),
    ] + _card_syn_ant(card)
    rows.append(_explanation_details(card))
    rows.append(_examples_section(card, highlight=True))
    rows.append(_grammar_row(card))
    return _message_from(*rows)


def card_h_study(card) -> Message:
    """H·2 Study — meaning hidden behind a spoiler line; examples as ✦ lines with
    spoiler translations (a table can't hide its cells).  Grammar stays plain."""
    rows = [
        (heading(2, plain(card["word"])),),
        (code(card["ipa"]),),
        (spoiler(plain(card["fa_meaning"])), plain("  ← معنی را حدس بزنید")),
        (plain(card["fa_explanation"]),),
    ] + _card_syn_ant(card)
    rows += _examples_lines_spoiler(card)
    rows.append(_grammar_row(card))
    return _message_from(*rows)


def card_h_plain_grammar(card) -> Message:
    """H·3 Plain grammar — like H but the grammar tip is a normal line (not a
    collapsible Details), in case you want it always visible."""
    rows = _rich_head(card) + _card_syn_ant(card)
    rows.append(_examples_section(card, highlight=True))
    rows.append((bold(plain("💡 نکته‌ی گرامری:")),))
    rows.append((plain(card["grammar_tip"]),))
    return _message_from(*rows)


def rich_card_variations(card) -> list:
    """The H-family Rich card structures to compare."""
    return [
        ("H · Exact feedback (collapsible table, plain translations)", _labelled_card("H · Exact feedback", card_h(card))),
        ("H·1 · Compact (explanation collapsible)", _labelled_card("H·1 · Compact", card_h_compact(card))),
        ("H·2 · Study (hidden answers)", _labelled_card("H·2 · Study", card_h_study(card))),
        ("H·3 · Plain grammar (no details)", _labelled_card("H·3 · Plain grammar", card_h_plain_grammar(card))),
    ]


async def send_rich_cards_mode(bot, chat_id: int) -> None:
    """Send all Rich flash-card structure variations, one by one."""
    sent = 0
    failed = 0
    for label, msg in rich_card_variations(SAMPLE_CARD):
        try:
            await send(chat_id, msg, bot=bot, backend=Backend.RICH)
            log.info("✅  [%s] sent", label)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            log.error("❌  [%s] failed: %s", label, exc)
            failed += 1
    log.info("🃏  rich cards — %d sent, %d failed", sent, failed)
    print(f"\n🃏  rich cards complete — {sent} sent, {failed} failed")


async def cmd_cardsrich(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🃏  Sending Rich flash-card VARIATIONS…")
    await send_rich_cards_mode(update.get_bot(), update.effective_chat.id)


# ──────────────────────────────────────────────────────────────────────────────
# Rich SESSION demos  (/sessions)
# Mirrors the session-engine revealed card: full word card, a recall prompt, the
# 4 FSRS grade buttons, and a progress footer (نشست ۴ | کارت ۸ از ۸).  Demos
# vary WHERE the progress bar goes and HOW MUCH of the card is collapsed.
# ──────────────────────────────────────────────────────────────────────────────

SRS_POST_REVEAL_LINE = "🧠 با دکمه‌های توصیفی زیر یادآوری خود را ثبت کنید."

SESSION_GRADE_LABELS = {
    1: "یادم نیامد ⭕",
    2: "به سختی یادم اومد 🟡",
    3: "خوب بود 🟢",
    4: "خیلی آسون 🟣",
}


def _progress_stepper(card_idx: int, total: int) -> str:
    """Stepper-dots progress: one ● per card up to the current one, ○ after.
    Locked by owner (گامنما).  E.g. card 5 of 8 -> '● ● ● ● ● ○ ○ ○'."""
    card_idx = max(0, min(card_idx, total))
    return " ".join(["●"] * card_idx + ["○"] * (total - card_idx))


def _grade_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(SESSION_GRADE_LABELS[1], callback_data="demo:sess_grade:1"),
            InlineKeyboardButton(SESSION_GRADE_LABELS[2], callback_data="demo:sess_grade:2"),
        ],
        [
            InlineKeyboardButton(SESSION_GRADE_LABELS[3], callback_data="demo:sess_grade:3"),
            InlineKeyboardButton(SESSION_GRADE_LABELS[4], callback_data="demo:sess_grade:4"),
        ],
        [InlineKeyboardButton("🔊 تلفظ", callback_data="demo:sess_pronounce")],
    ]
    return InlineKeyboardMarkup(rows)


def _fa_digits(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _session_footer(session_no: int, card_idx: int, total: int) -> str:
    return (
        f"نشست {_fa_digits(session_no)} | "
        f"کارت {_fa_digits(card_idx)} از {_fa_digits(total)}"
    )


def _session_examples_lines(card) -> list:
    """✦ English line + Persian translation under it, BOTH with the keyword/meaning
    word bolded (double-highlight) and invisible BiDi per line."""
    rows = [(bold(plain("📝 مثال‌ها + ترجمه:")),)]
    for en, fa in zip(card["examples"], card["example_translations"]):
        rows.append((plain("✦ "),) + _highlight_ltr_cell(en, card["word"]))
        rows.append(_highlight_fa_cell(fa, card["fa_meaning"]))
    return rows


def _collapsible_html_table(card) -> str:
    """Raw Rich markup: an HTML ``<table>`` inside ``<details open>`` with BOTH the
    English keyword and the Persian meaning word bolded, plus invisible BiDi per
    cell.  EXPERIMENTAL — the only way to nest a table in ``<details>`` (Markdown
    tables don't render there); borders render faintly, bold-in-cells is the open
    question we're testing."""
    def _first_hit(text, candidates):
        for c in candidates:
            b, h, a = _split_on_word(text, c)
            if h:
                return b, h, a
        return text, "", ""

    def _b(target, meaning):
        candidates = [meaning] + [w.strip() for w in meaning.split("،") if w.strip()]
        b, h, a = _first_hit(target, candidates)
        return b + (f"<b>{h}</b>" if h else "") + a

    body = "".join(
        f"<tr><td>{_LRE}{_b(en, card['word'])}{_PDF}</td>"
        f"<td>{_RLE}{_b(fa, card['fa_meaning'])}{_PDF}</td></tr>"
        for en, fa in zip(card["examples"], card["example_translations"])
    )
    return (
        "<details open><summary>📝 مثال‌ها و ترجمه</summary>"
        "<table><tr><th>جمله نمونه</th><th>ترجمه</th></tr>" + body + "</table></details>"
    )


def session_card_mockup(card) -> Message:
    """S·1 · NEW experiment — reduced footer (stepper + نشست ۴, no card counter),
    per-cell BiDi, double-highlight (English keyword AND Persian meaning), the
    Persian explanation open by default, and a collapsible (HTML) examples table."""
    rows = [
        (plain(_progress_stepper(5, 8) + "  نشست ۴"),),
        (heading(2, plain(card["word"])),),
        (code(card["ipa"]),),
        (heading(3, plain("✤ "), plain(card["fa_meaning"])),),
        _explanation_details(card, open=True),
    ] + _card_syn_ant(card)
    rows.append((raw_rich(_collapsible_html_table(card)),))
    rows.append(_grammar_row(card))
    rows.append((plain(SRS_POST_REVEAL_LINE),))
    m = _message_from(*rows)
    m.set_keyboard(_grade_keyboard())
    return m


def session_card_footer_bar(card) -> Message:
    """S·2 — progress bar in the footer, under the session text."""
    rows = [
        (heading(2, plain(card["word"])),),
        (code(card["ipa"]),),
        (heading(3, plain("✤ "), plain(card["fa_meaning"])),),
        (plain(card["fa_explanation"]),),
    ] + _card_syn_ant(card)
    rows += _session_examples_lines(card)
    rows += [
        (bold(plain("✍️ نکته‌ی گرامری:")),),
        (plain(card["grammar_tip"]),),
        (plain(SRS_POST_REVEAL_LINE),),
        (plain("نشست ۴" + "  " + _progress_stepper(5, 8)),),
    ]
    m = _message_from(*rows)
    m.set_keyboard(_grade_keyboard())
    return m


def session_card_top_bar(card) -> Message:
    """S·3 — progress bar at the TOP; explanation, examples and grammar are
    collapsed into collapsible Details to hide mid-session clutter."""
    rows = [
        (plain(_progress_stepper(5, 8) + "  " + _session_footer(4, 5, 8)),),
        (heading(2, plain(card["word"])),),
        (code(card["ipa"]),),
        (heading(3, plain("✤ "), plain(card["fa_meaning"])),),
        _explanation_details(card),
    ] + _card_syn_ant(card)
    rows.append(_examples_section(card))
    rows.append(_grammar_row(card))
    rows.append((plain(SRS_POST_REVEAL_LINE),))
    m = _message_from(*rows)
    m.set_keyboard(_grade_keyboard())
    return m


def session_card_max_collapse(card) -> Message:
    """S·4 — leanest mid-session card: progress bar on top, ONLY word + meaning
    visible; explanation, examples, grammar each behind a collapsed Details."""
    rows = [
        (plain(_progress_stepper(5, 8) + "  نشست ۴"),),
        (heading(2, plain(card["word"])),),
        (code(card["ipa"]),),
        (heading(3, plain("✤ "), plain(card["fa_meaning"])),),
        _explanation_details(card),
        _examples_section(card, highlight=True),
        _grammar_row(card),
        (plain(SRS_POST_REVEAL_LINE),),
    ]
    m = _message_from(*rows)
    m.set_keyboard(_grade_keyboard())
    return m


def session_card_variations(card) -> list:
    return [
        ("S·1 · NEW experiment (bidi + collapsible table + double-highlight)", session_card_mockup(card)),
        ("S·2 · Progress bar in footer", session_card_footer_bar(card)),
        ("S·3 · Progress bar on top + collapsible", session_card_top_bar(card)),
        ("S·4 · Max collapse (leanest)", session_card_max_collapse(card)),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# 📋 SESSION REPORT demos — summary / detail / legend (Rich)
# Final proposal from grill: grouped by status, no "—", Rich Message
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_REPORT = {
    "summary": {"learned": 2, "reviewed": 6, "recall": 72, "xp": 16, "heat": 2, "heat_label": "دوآتیشه"},
    "words": [
        ("Anticipate", "learning", "آسان", None, "۵ روز دیگر"),
        ("crater", "learning", "سخت", "۴ روز", "فردا"),
        ("facade", "familiar", "سخت", "۲ روز ", "۳ روز دیگر"),
        ("affection", "familiar", "آسان", "۳ روز ", "۴ روز دیگر"),
        ("mitigate", "familiar", "سخت", "۵ روز ", "پس‌فردا"),
        ("serene", "familiar", "آسان", None, "۶ روز دیگر"),
        ("available", "learned", "آسان", None, "۱۲ روز دیگر"),
        ("eloquent", "learned", "آسان", None, "۸ روز دیگر"),
    ],
    "counts": {"learning": 2, "familiar": 4, "learned": 2, "stable": 0},
}

_STATUS_META = {
    "learning": ("🌱", "در حال آموختن"),
    "familiar": ("👀", "آشنا (نیازمند تثبیت)"),
    "learned": ("📚", "آموخته شده"),
    "stable": ("🧠", "پایدار"),
}


def demo_report_summary() -> Message:
    s = SAMPLE_REPORT["summary"]
    m = Message()
    m.add_line(heading(3, plain("📊 گزارش نشست مطالعه")))
    m.add_line(plain(f"✨ {s['learned']} واژه تازه"), plain(f"  ·  🔁 {s['reviewed']} واژه مرور"))
    m.add_line(plain(f"🎯 یادآوری: {s['recall']}٪  ·  (+{s['xp']} XP)  ·  🔥 {s['heat_label']}"))
    m.add_line(nl())
    m.add_line(plain(f"📈 پیشرفت: 🌱{SAMPLE_REPORT['counts']['learning']} · 👀{SAMPLE_REPORT['counts']['familiar']} · 📚{SAMPLE_REPORT['counts']['learned']} · 🧠{SAMPLE_REPORT['counts']['stable']}"))
    m.set_keyboard(InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 جزئیات واژه‌ها", callback_data="demo:report_detail")],
        [InlineKeyboardButton("📖 راهنما", callback_data="demo:report_legend")],
    ]))
    return m


def demo_report_detail() -> Message:
    m = Message()
    m.add_line(heading(3, plain("📋 واژه‌های این نشست")))
    # 4-col table but status shortened to icon + modifier only (legend explains)
    header = (plain("واژه"), plain("وضعیت"), plain("بعدی"), plain("قبلی"))
    rows = []
    order = ("learning", "familiar", "learned", "stable")
    grouped = {k: [w for w in SAMPLE_REPORT["words"] if w[1] == k] for k in order}
    for key in order:
        emoji, _ = _STATUS_META[key]
        items = grouped[key]
        if not items:
            rows.append((plain(""), plain(f"{emoji}"), plain("هنوز واژه‌ای نیست"), plain("")))
            continue
        for word, _, mod, prev, nxt in items:
            status = f"{emoji} ({mod})"
            nxt_short = nxt.replace(" دیگر", "") if nxt else ""
            prev_short = prev.replace(" دیگر", "") if prev else ""
            rows.append((plain(word), plain(status), plain(nxt_short), plain(prev_short)))
    m.add_line(table(header, *rows))
    m.add_line(nl())
    # progress as small table
    m.add_line(table(
        (plain("🌱"), plain("👀"), plain("📚"), plain("🧠")),
        (plain(str(SAMPLE_REPORT['counts']['learning'])), plain(str(SAMPLE_REPORT['counts']['familiar'])), plain(str(SAMPLE_REPORT['counts']['learned'])), plain(str(SAMPLE_REPORT['counts']['stable']))),
    ))
    m.set_keyboard(InlineKeyboardMarkup([
        [InlineKeyboardButton("« بازگشت به خلاصه", callback_data="demo:report_summary")],
        [InlineKeyboardButton("📖 راهنما", callback_data="demo:report_legend")],
    ]))
    return m


def demo_report_legend() -> Message:
    m = Message()
    m.add_line(heading(3, plain("📖 گام‌های تثبیت در حافظه")))
    m.add_line(nl())
    m.add_line(bold("🌱 پیش‌آموزش:"), plain(" کارت تازه، نیازمند مرورهای نزدیک"))
    m.add_line(bold("👀 آشنا:"), plain(" گام پیش از تثبیت"))
    m.add_line(bold("📚  آموخته شده:"), plain(" فاصله مرورها بیشتر میشود"))
    m.add_line(bold("🧠 پایداری:"), plain(" نشسته در حافظه بلندمدت، فاصله مرورها حداکثری میشود"))
    m.add_line(nl())
    m.add_line(bold("(آسان):"), plain(" زودتر می‌آموزید"))
    m.add_line(bold("(سخت):"), plain(" کندتر در حافظه می‌نشیند"))
    m.add_line(nl())
    m.add_line(plain("📅 مرور آینده · ⏰ مرور پیشین"))
    m.set_keyboard(InlineKeyboardMarkup([
        [InlineKeyboardButton("« بازگشت", callback_data="demo:report_detail")],
    ]))
    return m


# ——— v2 structured variants for comparison (small header + table + motivational) ———

def demo_report_summary_v2() -> Message:
    s = SAMPLE_REPORT["summary"]
    m = Message()
    m.add_line(heading(3, plain("📃 گزارش نشست")))
    m.add_line(quote(plain("آفرین! 👏\nاین نشست ترکیبی بود از مرور خوب و یادگیری واژگان نو.\nراستی، فقط یه نشست دیگه مونده که سه‌آتیشه بشیا! 🚀")))
    # structured 2-col table: stat | value
    m.add_line(table(
        (plain("یادآوری"), plain(f"{s['recall']}٪")),
        (plain("امتیاز"), plain(f"+{s['xp']} · {s['heat_label']} 🔥")),
        (plain("کارت"), plain(f"{s['learned']} تازه · {s['reviewed']} مرور")),
    ))
    m.add_line(nl())
    m.add_line(heading(3, plain("📊 وضعیت کارت‌های نشست")))
    m.add_line(table(
        (plain("🌱"), plain("👀"), plain("📚"), plain("🧠")),
        (plain(str(SAMPLE_REPORT['counts']['learning'])), plain(str(SAMPLE_REPORT['counts']['familiar'])), plain(str(SAMPLE_REPORT['counts']['learned'])), plain(str(SAMPLE_REPORT['counts']['stable']))),
    ))
    m.set_keyboard(InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 جزئیات (v2)", callback_data="demo:report_detail_v2")],
        [InlineKeyboardButton("📖 راهنما (v2)", callback_data="demo:report_legend_v2")],
    ]))
    return m


def demo_report_detail_v2() -> Message:
    m = Message()
    m.add_line(heading(3, plain("📋 واژه‌های این نشست")))
    # 3-col table: واژه | وضعیت | مرور — status shortened, بعدی without دیگر
    header = (plain("واژه"), plain("وضعیت"), plain("مرور"))
    rows = []
    order = ("learning", "familiar", "learned", "stable")
    grouped = {k: [w for w in SAMPLE_REPORT["words"] if w[1] == k] for k in order}
    for key in order:
        emoji, _ = _STATUS_META[key]
        items = grouped[key]
        if not items:
            rows.append((plain(""), plain(f"{emoji}"), plain("هنوز واژه‌ای نیست")))
            continue
        for word, _, mod, prev, nxt in items:
            status = f"{emoji} ({mod})"
            nxt_short = nxt.replace(" دیگر", "") if nxt else ""
            prev_short = prev.replace(" دیگر", "") if prev else ""
            مرور = f"📅 {nxt_short}" + (f" ⏰ {prev_short}" if prev else "")
            rows.append((plain(word), plain(status), plain(مرور)))
    m.add_line(table(header, *rows))
    m.set_keyboard(InlineKeyboardMarkup([
        [InlineKeyboardButton("« خلاصه (v2)", callback_data="demo:report_summary_v2")],
        [InlineKeyboardButton("📖 راهنما (v2)", callback_data="demo:report_legend_v2")],
    ]))
    return m


def demo_report_legend_v2() -> Message:
    m = Message()
    m.add_line(heading(3, plain("📖 گام‌های تثبیت در حافظه")))
    m.add_line(table(
        (plain("نماد"), plain("معنا")),
        (bold("🌱 پیش‌آموزش"), plain("کارت تازه، نیازمند مرورهای نزدیک")),
        (bold("👀 آشنا"), plain("گام پیش از تثبیت، فقط چند روز در حافظه")),
        (bold("📚 آموخته شده"), plain("فاصله مرورها بیشتر میشود، چندین روز در حافظه")),
        (bold("🧠 پایداری"), plain("نشسته در حافظه بلندمدت، فاصله مرورها حداکثری میشود")),
        (bold("(آسان)"), plain("زودتر می‌آموزید")),
        (bold("(سخت)"), plain("کندتر در حافظه می‌نشیند")),
        (bold("📅 بعدی"), plain("مرور آینده")),
        (bold("⏰ قبلی"), plain("مرور پیشین")),
    ))
    m.set_keyboard(InlineKeyboardMarkup([
        [InlineKeyboardButton("« جزئیات (v2)", callback_data="demo:report_detail_v2")],
    ]))
    return m


async def send_session_mode(bot, chat_id: int) -> None:
    sent = 0
    failed = 0
    for label, msg in session_card_variations(SAMPLE_CARD):
        try:
            await send(chat_id, msg, bot=bot, backend=Backend.RICH)
            log.info("✅  [%s] sent", label)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            log.error("❌  [%s] failed: %s", label, exc)
            failed += 1
    log.info("🗂  sessions — %d sent, %d failed", sent, failed)
    print(f"\n🗂  sessions complete — {sent} sent, {failed} failed")


async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🗂  Sending Rich SESSION-card variations…")
    await send_session_mode(update.get_bot(), update.effective_chat.id)


# ──────────────────────────────────────────────────────────────────────────────
# Hypothesis probe: does Rich re-parse HTML-ish tags inside <details>?  (/richtest)
# ──────────────────────────────────────────────────────────────────────────────
# Hypothesis (owner + @mira): Rich Messages lean toward HTML. Markdown constructs
# (| table |, ||spoiler||) inside a nested <details> block are NOT re-parsed, so
# they render as raw text — but HTML tags (<table>, <tg-spoiler>, <pre>) should
# work. Each case is sent as RAW rich markup via send_rich_message (no span tree),
# so we test what the Rich dialect itself accepts.
def _hypothesis_cases() -> list[tuple[str, str]]:
    """(label, raw rich body) pairs to probe HTML-inside-details support."""
    return [
        (
            "1) HTML <table> inside <details open>",
            "<details open><summary>📂 جدول HTML</summary>"
            "<table><tr><th>کلمه</th><th>معنی</th></tr>"
            "<tr><td>lodge</td><td>اقامت</td></tr>"
            "<tr><td>adapt</td><td>سازگار</td></tr></table></details>",
        ),
        (
            "2) <tg-spoiler> inside HTML table cell (no details)",
            "<table><tr><th>کلمه</th><th>معنی (اسپویلر)</th></tr>"
            "<tr><td>lodge</td><td><tg-spoiler>اقامت</tg-spoiler></td></tr>"
            "<tr><td>adapt</td><td><tg-spoiler>سازگار</tg-spoiler></td></tr></table>",
        ),
        (
            "3) <tg-spoiler> inside <details>",
            "<details open><summary>💡 معنی</summary><tg-spoiler>اقامت در منزل</tg-spoiler></details>",
        ),
        (
            "4) <pre> ASCII table inside <details>",
            "<details open><summary>📊 جدول املا</summary><pre>│ کلمه   │ معنی\n"
            "│ ────── │ ──────\n│ lodge  │ اقامت\n│ adapt  │ سازگار\n</pre></details>",
        ),
        (
            "5) control: plain body inside <details>",
            "<details open><summary>📂 کنترل</summary>متن ساده بدون هیچ تگ تو در تو</details>",
        ),
    ]


async def send_hypothesis_test(bot, chat_id: int) -> None:
    sent = 0
    failed = 0
    for label, body in _hypothesis_cases():
        markup = f"<b>{label}</b>\n\n{body}"
        try:
            await telegram_rich.send_rich_message(
                bot, chat_id, markup, markup, is_rtl=True
            )
            log.info("✅  [%s]", label)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            log.error("❌  [%s] failed: %s", label, exc)
            failed += 1
    # Phase 03 — new inline spans via the span tree (Backend.RICH), including table-cell tg_spoiler
    span_cases: list[tuple[str, Message]] = []
    m = Message(); m.add_line(underline("متن زیرخط‌دار")); span_cases.append(("underline", m))
    m = Message(); m.add_line(strike("متن خط‌خورده")); span_cases.append(("strike", m))
    m = Message(); m.add_line(mark("متن هایلایت")); span_cases.append(("marked", m))
    m = Message(); m.add_line(tg_spoiler("راز")); span_cases.append(("tg_spoiler inline", m))
    m = Message(); m.add_line(Table(header=None, rows=((tg_spoiler("راز"), plain("ترجمه")),))); span_cases.append(("tg_spoiler in table cell", m))
    for label, msg in span_cases:
        try:
            await send(chat_id, msg, bot=bot, backend=Backend.RICH)
            log.info("✅  [span:%s] sent", label)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            log.error("❌  [span:%s] failed: %s", label, exc)
            failed += 1
    log.info("🧪  richtest — %d sent, %d failed", sent, failed)
    print(f"\n🧪  richtest complete — {sent} sent, {failed} failed")


async def cmd_richtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🧪  Sending Rich HTML-inside-<details> probes…")
    await send_hypothesis_test(update.get_bot(), update.effective_chat.id)


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

    if data in ("demo:rich", "demo:rich_menu"):
        await query.edit_message_text(
            "🔥  <b>Rich Message demos</b>\n"
            "Tap one element to send it via sendRichMessage and watch what "
            "renders (or falls back).",
            reply_markup=RICH_MENU,
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "demo:rich_main":
        await query.edit_message_text(
            "🛠  <b>send_pretty demo bot</b>\nPick a section below:",
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

    elif section == "report":
        await query.edit_message_text("⏳  Sending REPORT demos (summary → detail → legend)…")
        await _reply(update, demo_report_summary(), backend=Backend.RICH)
        await _reply(update, demo_report_detail(), backend=Backend.RICH)
        await _reply(update, demo_report_legend(), backend=Backend.RICH)
        await query.edit_message_text("✅  REPORT (summary + detail + legend) sent!  Pick another:", reply_markup=BACK_BUTTON, parse_mode=ParseMode.HTML)
        return

    elif section == "report_v2":
        await query.edit_message_text("⏳  Sending REPORT v2 (structured)…")
        await _reply(update, demo_report_summary_v2(), backend=Backend.RICH)
        await _reply(update, demo_report_detail_v2(), backend=Backend.RICH)
        await _reply(update, demo_report_legend_v2(), backend=Backend.RICH)
        await query.edit_message_text("✅  REPORT v2 (structured) sent!  Pick another:", reply_markup=BACK_BUTTON, parse_mode=ParseMode.HTML)
        return

    elif section == "report_summary":
        await _reply(update, demo_report_summary(), backend=Backend.RICH)
        return

    elif section == "report_detail":
        await _reply(update, demo_report_detail(), backend=Backend.RICH)
        return

    elif section == "report_legend":
        await _reply(update, demo_report_legend(), backend=Backend.RICH)
        return

    elif section == "report_summary_v2":
        await _reply(update, demo_report_summary_v2(), backend=Backend.RICH)
        return

    elif section == "report_detail_v2":
        await _reply(update, demo_report_detail_v2(), backend=Backend.RICH)
        return

    elif section == "report_legend_v2":
        await _reply(update, demo_report_legend_v2(), backend=Backend.RICH)
        return

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

    elif section == "rich_heading":
        await query.edit_message_text("⏳  Sending Rich heading…")
        await _reply(update, demo_rich_heading(), backend=Backend.RICH)
        await query.edit_message_text("✅  Rich heading sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "rich_table":
        await query.edit_message_text("⏳  Sending Rich table…")
        await _reply(update, demo_rich_table(), backend=Backend.RICH)
        await query.edit_message_text("✅  Rich table sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "rich_list":
        await query.edit_message_text("⏳  Sending Rich list…")
        await _reply(update, demo_rich_list(), backend=Backend.RICH)
        await query.edit_message_text("✅  Rich list sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "rich_task":
        await query.edit_message_text("⏳  Sending Rich task list…")
        await _reply(update, demo_rich_task(), backend=Backend.RICH)
        await query.edit_message_text("✅  Rich task list sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "rich_details":
        await query.edit_message_text("⏳  Sending Rich details…")
        await _reply(update, demo_rich_details(), backend=Backend.RICH)
        await query.edit_message_text("✅  Rich details sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "rich_math":
        await query.edit_message_text("⏳  Sending Rich math…")
        await _reply(update, demo_rich_math(), backend=Backend.RICH)
        await query.edit_message_text("✅  Rich math sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "rich_emoji":
        await query.edit_message_text("⏳  Sending Rich custom emoji…")
        await _reply(update, demo_rich_emoji(), backend=Backend.RICH)
        await query.edit_message_text("✅  Rich custom emoji sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "rich_emoji_btn":
        await query.edit_message_text("⏳  Sending Rich custom-emoji buttons…")
        await _reply(update, demo_rich_emoji_buttons(), backend=Backend.RICH)
        await query.edit_message_text("✅  Rich custom-emoji buttons sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "rich_card":
        await query.edit_message_text("⏳  Sending Rich flash card…")
        await _reply(update, card_h(SAMPLE_CARD), backend=Backend.RICH)
        await query.edit_message_text("✅  Rich flash card sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "rich_cards":
        await query.edit_message_text("🃏  Sending Rich flash-card VARIATIONS…")
        await send_rich_cards_mode(update.get_bot(), update.effective_chat.id)
        await query.edit_message_text("✅  Rich flash-card variations sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section == "sessions":
        await query.edit_message_text("🗂  Sending Rich SESSION-card variations…")
        await send_session_mode(update.get_bot(), update.effective_chat.id)
        await query.edit_message_text("✅  Session-card variations sent!  Pick another:", reply_markup=RICH_MENU, parse_mode=ParseMode.HTML)
        return

    elif section.startswith("sess_grade:"):
        grade = int(section.split(":", 1)[1])
        await query.answer(f"انتخاب شد: {SESSION_GRADE_LABELS.get(grade, '?')}")
        return

    elif section == "sess_pronounce":
        await query.answer("🔊 تلفظ (دمو)")
        return

    elif section == "rich_all":
        await query.edit_message_text("▶  Running ALL Rich demos…")
        await _run_rich_all(update)
        return

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

    log.warning("=== Error demo 2: Backend.RICH (now implemented — should render) ===")
    try:
        rendered = Message().add_line(heading(1, plain("x"))).render(Backend.RICH)
        log.info("✓  RICH now renders: %r", rendered)
    except Exception as exc:
        log.error("✗  RICH render unexpectedly raised: %s", exc)

    await query.edit_message_text(
        "✅  Error demos ran — check your console/log for the caught exceptions.\n"
        "Error 1 (raw= + Message) still fails loudly; RICH is now implemented "
        "(demo 2 should render, not raise).",
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


RICH_DEMOS = [
    ("Heading", demo_rich_heading),
    ("Table", demo_rich_table),
    ("List", demo_rich_list),
    ("Task list", demo_rich_task),
    ("Details", demo_rich_details),
    ("Math", demo_rich_math),
    ("Custom emoji", demo_rich_emoji),
    ("Custom emoji buttons", demo_rich_emoji_buttons),
    ("Flash card", lambda: card_h(SAMPLE_CARD)),
]


async def _run_rich_all(update: Update) -> None:
    """Send every Rich element one-by-one via Backend.RICH, logging per-demo
    success/failure so we can see exactly what renders vs falls back."""
    query = update.callback_query
    sent = 0
    failed = 0
    for label, builder in RICH_DEMOS:
        try:
            await _reply(update, builder(), backend=Backend.RICH)
            log.info("✅  [Rich %s] sent", label)
            sent += 1
        except Exception as exc:
            log.error("❌  [Rich %s] failed: %s", label, exc)
            failed += 1

    summary = (
        f"🏁  Rich demos complete — {sent} sent, {failed} failed.\n"
        "Look at the messages above: a real Rich Message renders natively; "
        "anything that fell back shows as plain/MDV2 text."
    )
    try:
        await query.edit_message_text(
            summary, reply_markup=RICH_MENU, parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


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
    print("  🔥 Rich Message renders (Backend.RICH — what sendRichMessage gets)")
    print(SEP)
    for name, builder in RICH_DEMOS:
        print(f"\n── {name} ──")
        print(builder().render(Backend.RICH))

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
    app.add_handler(CommandHandler("cardsrich", cmd_cardsrich))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("richtest", cmd_richtest))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^demo:"))

    print("✅  Bot is up — open a chat with it and send /start (or /sendall)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
