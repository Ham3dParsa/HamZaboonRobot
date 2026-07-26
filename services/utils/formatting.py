import json
import re

from services import db

SRS_HIDDEN_INSTRUCTION = (
    "⏰ مرور فاصله‌دار: معنی و مثال‌ها را از حفظ یادآوری کن — "
    "هر بار که از حافظه استفاده می‌کنی، واژه در ذهنت عمیق‌تر می‌شود. "
    "اگر به‌یادت آمد «✅ یادم بود» را بزن؛ اگر نه، «👁 افشای کارت» را بزن و بعد ارزیابی کن."
)

SRS_REVEAL_QUESTION = "🧠 آیا واقعاً درست به یادش آوردی، یا می‌خواهی باز هم یادآوری شود?"


def escape_mdv2(text: str) -> str:
    """Escape کامل‌تر برای MarkdownV2"""
    if not text:
        return ""
    special = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([' + re.escape(special) + r'])', r'\\\1', text)


def escape_mdv2_code(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"([`\\])", r"\\\1", text)


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


def _phonetic_lines(value: str | dict) -> list[str]:
    settings = db.get_phonetic_display_settings()

    if isinstance(value, dict):
        sections = value
    else:
        raw = (value or "").strip()
        if not raw:
            return []

        if raw.startswith("{") and raw.endswith("}"):
            try:
                sections = json.loads(raw.replace("'", '"'))
            except (json.JSONDecodeError, Exception):
                lines = raw.splitlines()
                if len(lines) >= 3:
                    sections = {"ipa": lines[0].strip(), "persian": lines[2].strip()}
                elif len(lines) == 2:
                    sections = {"ipa": lines[0].strip(), "persian": lines[1].strip()}
                else:
                    sections = {"ipa": raw, "persian": ""}
        else:
            lines = raw.splitlines()
            if len(lines) >= 3:
                sections = {"ipa": lines[0].strip(), "persian": lines[2].strip()}
            elif len(lines) == 2:
                sections = {"ipa": lines[0].strip(), "persian": lines[1].strip()}
            else:
                sections = {"ipa": raw, "persian": ""}

    rendered = []
    for key in ('ipa', 'persian'):
        val = sections.get(key)
        if settings.get(key) and val:
            rendered.append(f"`{escape_mdv2_code(str(val))}`")

    return rendered