import html
import json
import re

SRS_HIDDEN_INSTRUCTION = (
    "⏰ مرور فاصله‌دار: معنی و مثال‌ها را از حفظ یادآوری کن — "
    "هر بار که از حافظه استفاده می‌کنی، واژه در ذهنت عمیق‌تر می‌شود. "
    "بعد از یادآوری، با ۴ دکمه ارزیابی کن: "
    "یادم نیامد / سخت بود / خوب بود / خیلی راحت بود."
)

SRS_REVEAL_QUESTION = "🧠 آیا واقعاً درست به یادش آوردی، یا می‌خواهی باز هم یادآوری شود?"


def escape_mdv2(text: str) -> str:
    """Escape کامل‌تر برای MarkdownV2"""
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([' + re.escape(special) + r'])', r'\\\1', text)


_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_persian_digits(value) -> str:
    """Convert Latin digits to Persian digits for learner-facing text."""
    return str(value).translate(_PERSIAN_DIGITS)


def escape_mdv2_code(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"([`\\])", r"\\\1", text)


def html_escape(text: str) -> str:
    """Escape a dynamic value for interpolation into a ParseMode.HTML message.

    Centralized choke point for HTML-mode admin/non-learner renderings. Escapes
    the reserved HTML characters (``& < > " '``) so a value containing them
    (e.g. a base_url query string) cannot break Telegram's entity parsing.
    """
    if not text:
        return ""
    return html.escape(str(text), quote=True)


class CardPreparationError(RuntimeError):
    pass


def format_card(
    data: dict,
    footer: str = "",
    *,
    presentation: str = "detailed",
    translations_prepared: bool = False,
    phonetic_lines: list[str] | None = None,
) -> str:
    if presentation not in {"brief", "detailed"}:
        raise ValueError("presentation must be 'brief' or 'detailed'")

    word = escape_mdv2(data.get("word", ""))
    fa_meaning = escape_mdv2(data.get("fa_meaning", ""))
    fa_expl = escape_mdv2(data.get("fa_explanation", ""))

    lines = [f"*{word}*"]

    if phonetic_lines:
        lines.extend(phonetic_lines)

    lines.append(f"\n✤ *{fa_meaning}*")

    if fa_expl:
        lines.append(f"{fa_expl}")

    if presentation == "brief":
        if footer:
            lines.append(f"\n{escape_mdv2(footer)}")
        return "\n".join(lines)

    syn_list = [escape_mdv2(s) for s in (data.get("synonyms") or [])]
    ant_list = [escape_mdv2(s) for s in (data.get("antonyms") or [])]
    syn = "، ".join(syn_list) or "—"
    ant = "، ".join(ant_list) or "—"

    examples = (data.get("examples") or [])[:2]
    translations = (data.get("example_translations") or [])[:2]

    grammar_tip = escape_mdv2(data.get("grammar_tip", ""))

    lines.append(f"\n🟢 *مترادف:* {syn}")
    lines.append(f"🔴 *متضاد:* {ant}")

    if examples:
        example_label = escape_mdv2("مثال‌ها + ترجمه" if translations_prepared else "مثال‌ها")
        lines.append(f"\n📝 *{example_label}:*")
        for index, example in enumerate(examples):
            lines.append(f"✦ {escape_mdv2(example)}")
            if translations_prepared and index < len(translations):
                lines.append(f"||{escape_mdv2(translations[index])}||")

    if grammar_tip:
        lines.append(f"\n✍️ *نکته‌ی گرامری:*\n{grammar_tip}")

    if footer:
        lines.append(f"\n{escape_mdv2(footer)}")

    return "\n".join(lines)


def format_srs_prompt(data: dict, *, phonetic_lines: list[str] | None = None) -> str:
    """Render the first (hidden) SRS reminder screen.

    Shows only the prompt word and phonetic so the learner can self-test before
    revealing the meaning, examples, and grammar tip.
    """
    word = escape_mdv2(data.get("word", ""))
    lines = [f"*{word}*"]
    if phonetic_lines:
        lines.extend(phonetic_lines)
    lines.append(f"\n{escape_mdv2(SRS_HIDDEN_INSTRUCTION)}")
    return "\n".join(lines)


def _saved_word_card(row) -> dict:
    """Decode a saved_words row's card_data JSON into a card dict.

    Single shared implementation for the study/review flows. The stored
    card_data is a JSON string; a row without a valid card dict falls back
    to a minimal card so rendering never crashes.
    """
    if row["card_data"]:
        try:
            data = json.loads(row["card_data"])
        except (TypeError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            return data
    return {
        "word": row["word"],
        "phonetic": "",
        "fa_meaning": "این واژه قبلاً بدون کارت کامل ذخیره شده است.",
        "fa_explanation": "معنی و مثال کامل در داده‌های قدیمی موجود نیست؛ خودت معنی را یادآوری کن.",
        "synonyms": [],
        "antonyms": [],
        "examples": [],
        "example_translations": [],
        "grammar_tip": "",
    }


def _phonetic_lines(value: str | dict) -> list[str]:
    if isinstance(value, dict):
        ipa = value.get("ipa", "")
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            ipa = parsed.get("ipa", "") if isinstance(parsed, dict) else ""
        except (json.JSONDecodeError, TypeError):
            ipa = value.strip()
    else:
        return []

    if ipa:
        return [f"`{escape_mdv2_code(str(ipa))}`"]
    return []