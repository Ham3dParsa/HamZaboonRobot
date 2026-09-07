import datetime
import html
import json
import random
import re

try:
    import jdatetime as _jdatetime
    jdatetime = _jdatetime
except Exception:  # pragma: no cover — fallback when jdatetime not installed
    jdatetime = None  # type: ignore[assignment]

from config import APP_TZ, _app_today
from config.catalog import language_label
from services.utils.validation import _CUSTOM_WORD_MAX_WORDS

# SRS staged-reveal prompt engine (#338). Front-stage prompt types follow the
# locked spec §2B; all learner-facing copy is pinned here verbatim so tests
# and the UI can never drift.
SRS_PROMPT_TYPES = ("standard", "fill_blank", "meaning", "synonym", "direct_translate")

SRS_HIDDEN_HEADER = "? ? ?"
SRS_FRONT_SUB_INSTRUCTION = (
    "👇 دکمه‌ی «نمایش پاسخ» را بزن؛ سپس صادقانه با دکمه‌ها به یادآوری‌ات نمره بده."
)
SRS_POST_REVEAL = "🧠 با دکمه‌های توصیفی زیر یادآوری خود را ثبت کنید."
NEW_CARD_BADGE = "کارت جدید ✨"
SRS_INSTRUCT_STANDARD = (
    "🧠 از حافظه‌ات استفاده کن تا معنا، مترادف‌ها و متضادهای این واژه را یادآوری کنی."
)
SRS_INSTRUCT_FILL_BLANK = "🧠 واژه جا افتاده در این جمله را به یاد بیاور:"
SRS_HINT_SYNONYM = "💡 راهنما: مترادف {item}"
SRS_HINT_ANTONYM = "💡 راهنما: متضاد {item}"
SRS_HINT_MEANING = "💡 راهنما: به معنای «{meaning}»"


def format_review_badge(days: int | None, review_number: int | None = None) -> str:
    """Learner-facing review badge for the staged-reveal front/back stages (R5, T3).

    ``review_number`` is optional so old callers render exactly as before.
    When provided: 0 means no prior review → «اولین دیدار»; N≥1 appends
    «مرور Nام» (Persian digits) after the days part.
    """
    base = "" if days is None else f"⏰ آخرین مرور: {to_persian_digits(days)} روز پیش"
    if review_number is None:
        return base
    try:
        n = int(review_number)
    except (TypeError, ValueError):
        return base
    ordinal = "اولین دیدار" if n <= 0 else f"مرور {to_persian_digits(n)}ام"
    if base:
        return f"{base} · {ordinal}"
    return ordinal


def days_since_review(last_review_at: str | None, now=None) -> int | None:
    """Whole days elapsed since the last review timestamp (R5 review badge).

    ``last_review_at`` is a UTC ISO-8601 string from ``saved_words``. A missing
    or unparseable timestamp returns None (callers then omit the badge). ``now``
    is injectable for tests; the live clock is used otherwise.
    """
    if not last_review_at:
        return None
    try:
        last = datetime.datetime.fromisoformat(last_review_at)
    except (TypeError, ValueError):
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return max(0, int((now - last).total_seconds() // 86400))


def format_next_review_text(interval_seconds: int | None) -> str:
    """Persian relative next-review toast for successful grades (Rule 9).

    ``interval_seconds`` is the exact scheduled interval. Display rounds:
       < 24h    -> «حدود N ساعت دیگر»
       = 1 day  -> «فردا»
       > 1 day  -> «N روز دیگر»
    A missing or zero interval falls back to a neutral scheduling line.
    The full toast carries the learner-facing copy verbatim for testability.
    """
    if not interval_seconds:
        return "ثبت شد؛ مرور بعدی زمان‌بندی شد."
    if interval_seconds < 86400:
        hours = max(1, round(interval_seconds / 3600))
        return f"ثبت شد؛ مرور بعدی: حدود {to_persian_digits(hours)} ساعت دیگر."
    days = round(interval_seconds / 86400)
    if days <= 1:
        return "ثبت شد؛ مرور بعدی: فردا."
    return f"ثبت شد؛ مرور بعدی: {to_persian_digits(days)} روز دیگر."


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


def _to_jalali_str(iso_str: str) -> str:
    """Convert an ISO datetime/date string to Jalali ``YYYY/MM/DD HH:MM`` with Persian digits.

    Parses ``iso_str`` via ``datetime.fromisoformat`` (handles ``Z`` suffix),
    converts through ``jdatetime.datetime.fromgregorian`` when available, and
    falls back to Gregorian formatting when ``jdatetime`` is absent or parsing
    fails. All digits are Persian via :func:`to_persian_digits`.
    Returns ``""`` for empty input and Persian-digit fallback for unparseable input.
    """
    if not iso_str:
        return ""
    # Normalise trailing Z to +00:00 for fromisoformat
    raw = iso_str.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        # Try date-only
        try:
            d = datetime.date.fromisoformat(raw)
            dt = datetime.datetime.combine(d, datetime.time.min)
        except (TypeError, ValueError):
            return to_persian_digits(iso_str)
    # jdatetime path — requires Gregorian datetime; strip tzinfo for conversion
    if jdatetime is not None:
        try:
            greg = dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
            jd = jdatetime.datetime.fromgregorian(datetime=greg)
            formatted = f"{jd.year}/{jd.month:02d}/{jd.day:02d} {jd.hour:02d}:{jd.minute:02d}"
            return to_persian_digits(formatted)
        except Exception:
            pass
    # Fallback: Gregorian formatted the same way
    try:
        formatted = dt.strftime("%Y/%m/%d %H:%M")
        return to_persian_digits(formatted)
    except Exception:
        return to_persian_digits(iso_str)


# Public alias (Q2 spec says _to_jalali_str, but expose friendly name too).
to_jalali_str = _to_jalali_str


def escape_mdv2_code(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"([`\\])", r"\\\1", text)


def html_escape(text: object | None) -> str:
    """Escape a dynamic value for interpolation into a ParseMode.HTML message.

    Centralized choke point for HTML-mode admin/non-learner renderings. Escapes
    the reserved HTML characters (``& < > " '``) so a value containing them
    (e.g. a base_url query string) cannot break Telegram's entity parsing.
    """
    if text is None:
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
    badge: str = "",
) -> str:
    if presentation not in {"brief", "detailed"}:
        raise ValueError("presentation must be 'brief' or 'detailed'")

    word = escape_mdv2(data.get("word", ""))
    fa_meaning = escape_mdv2(data.get("fa_meaning", ""))
    fa_expl = escape_mdv2(data.get("fa_explanation", ""))

    lines = [f"*{word}*"]

    if phonetic_lines:
        lines.extend(phonetic_lines)

    if badge:
        lines.append(f"\n{escape_mdv2(badge)}")

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


def _example_has_word(example: str, word: str) -> bool:
    """True when the example contains the exact word (word-boundary, R3)."""
    if not example or not word:
        return False
    return re.search(
        rf"(?<!\w){re.escape(word)}(?!\w)", example, re.IGNORECASE
    ) is not None


def _blank_word(text: str, word: str, count: int = 0) -> str:
    """Replace exact occurrences of the answer word with the hidden token.

    ``count`` mirrors ``re.sub``: 0 replaces all (used by front-stage hints so
    the answer never leaks), 1 replaces the first occurrence (used to blank the
    fill_blank example, R3). Word-boundary + case-insensitive, same as the
    eligibility matcher ``_example_has_word``.
    """
    if not text or not word:
        return text
    return re.sub(
        rf"(?<!\w){re.escape(word)}(?!\w)",
        "? ? ?",
        text,
        count=count,
        flags=re.IGNORECASE,
    )


def _hint_line(item: str, is_synonym: bool) -> str:
    """Single 💡 hint line for a drawn synonym or antonym item."""
    if is_synonym:
        return SRS_HINT_SYNONYM.format(item=item)
    return SRS_HINT_ANTONYM.format(item=item)


def _fill_blank_hints(
    card_data: dict, toggles: dict[str, bool], rng=None
) -> list[str]:
    """Build >=2 sense-consistent hint lines for the fill_blank prompt (issue #408).

    Adaptive composition from the *visible* synonym/antonym set:
      - 3 hints when one visible category has >=2 items and the other has >=1:
        2 from the dominant category (whichever has more; synonyms on tie) + 1
        from the other.
      - else 2 hints drawn from the combined visible syn+ant pool.
      - else a single meaning fallback (keeps the direct-render path safe for
        cards below the eligibility gate).
    """
    rng = rng or random
    visible_syn = [
        (item, True) for item in (card_data.get("synonyms") or []) if toggles.get("synonyms")
    ]
    visible_ant = [
        (item, False) for item in (card_data.get("antonyms") or []) if toggles.get("antonyms")
    ]

    three_hint = (len(visible_syn) >= 2 and len(visible_ant) >= 1) or (
        len(visible_ant) >= 2 and len(visible_syn) >= 1
    )
    if three_hint:
        if len(visible_ant) > len(visible_syn):
            dominant, other = visible_ant, visible_syn
        else:
            dominant, other = visible_syn, visible_ant  # synonyms on tie
        drawn = rng.sample(dominant, 2) + [rng.choice(other)]
        return [_hint_line(item, is_synonym) for item, is_synonym in drawn]

    combined = visible_syn + visible_ant
    if len(combined) >= 2:
        drawn = rng.sample(combined, 2)
        return [_hint_line(item, is_synonym) for item, is_synonym in drawn]

    if card_data.get("fa_meaning"):
        return [SRS_HINT_MEANING.format(meaning=card_data["fa_meaning"])]
    return []


def _join_guillemets(items: list[str]) -> str:
    return "«" + "» و «".join(str(item) for item in items) + "»"


def _synonym_instruct(syn_items: list[str], ant_items: list[str]) -> str:
    """Prompt sentence built from the drawn set (R2: only-synonyms /
    only-antonyms / both sentence styles; singular/plural aware per r5)."""
    syn_word = "مترادف" if len(syn_items) == 1 else "مترادف‌های"
    ant_word = "متضاد" if len(ant_items) == 1 else "متضادهای"
    if syn_items and ant_items:
        return (
            f"🧠 چه واژه‌ای {syn_word} {_join_guillemets(syn_items)} "
            f"و {ant_word} {_join_guillemets(ant_items)} دارد؟"
        )
    if syn_items:
        return f"🧠 چه واژه‌ای {syn_word} {_join_guillemets(syn_items)} دارد؟"
    return f"🧠 چه واژه‌ای {ant_word} {_join_guillemets(ant_items)} دارد؟"


def _draw_synonym_items(
    card_data: dict, toggles: dict[str, bool], rng
) -> tuple[list[str], list[str]]:
    """Draw 2-3 items from the combined *visible* set and split by category."""
    synonyms = card_data.get("synonyms") or []
    antonyms = card_data.get("antonyms") or []
    visible_syn = list(synonyms) if toggles.get("synonyms") else []
    visible_ant = list(antonyms) if toggles.get("antonyms") else []
    combined = visible_syn + visible_ant
    if not combined:
        return [], []
    draw_count = min(len(combined), rng.randint(2, 3))
    drawn = rng.sample(combined, draw_count)
    return (
        [item for item in drawn if item in visible_syn],
        [item for item in drawn if item in visible_ant],
    )


def eligible_srs_prompt_types(
    card_data: dict, toggles: dict[str, bool]
) -> list[str]:
    """Return the prompt types eligible for a card under the given toggles (R11).

    Follows the spec §2B ordering. ``standard`` only needs the word, so a bare
    card always keeps the pool non-empty; ``meaning``/``direct_translate`` need
    only ``fa_meaning``. ``fill_blank`` requires an example containing the exact
    word (R3); ``synonym`` requires a non-empty combined *visible* set (R2).
    """
    eligible: list[str] = []
    if card_data.get("word"):
        eligible.append("standard")
    visible_syn = list(card_data.get("synonyms") or []) if toggles.get("synonyms") else []
    visible_ant = list(card_data.get("antonyms") or []) if toggles.get("antonyms") else []
    if toggles.get("examples") and any(
        _example_has_word(example, card_data.get("word"))
        for example in (card_data.get("examples") or [])
    ) and len(visible_syn) + len(visible_ant) >= 2:
        eligible.append("fill_blank")
    if card_data.get("fa_meaning"):
        eligible.append("meaning")
        eligible.append("direct_translate")
    if visible_syn or visible_ant:
        eligible.append("synonym")
    return eligible


def select_srs_prompt_type(
    card_data: dict, toggles: dict[str, bool], rng=None
) -> str:
    """Pick one eligible prompt type via the injectable RNG (system in prod)."""
    eligible = eligible_srs_prompt_types(card_data, toggles)
    if not eligible:
        return "standard"
    return eligible[(rng or random).randrange(len(eligible))]


def format_srs_front_stage(
    card_data: dict,
    prompt_type: str,
    *,
    toggles: dict[str, bool],
    phonetic_lines: list[str] | None = None,
    badge: str = "",
    footer: str = "",
    lang: str = "",
    rng=None,
) -> str:
    """Render the hidden front stage for one prompt type (R4 sub-instruction +
    footer on every stage; badges per R5)."""
    rng = rng or random
    lines: list[str] = []
    if prompt_type == "standard":
        word = escape_mdv2(card_data.get("word", ""))
        lines.append(f"*{word}*")
        if phonetic_lines:
            lines.extend(phonetic_lines)
    elif prompt_type in ("fill_blank", "meaning", "synonym", "direct_translate"):
        lines.append(SRS_HIDDEN_HEADER)
    else:
        raise ValueError(f"Unknown SRS prompt type: {prompt_type}")

    if badge:
        lines.append(f"\n{escape_mdv2(badge)}")

    if prompt_type == "standard":
        lines.append(f"\n{escape_mdv2(SRS_INSTRUCT_STANDARD)}")
    elif prompt_type == "fill_blank":
        lines.append(f"\n{escape_mdv2(SRS_INSTRUCT_FILL_BLANK)}")
        matching = [
            example
            for example in (card_data.get("examples") or [])
            if _example_has_word(example, card_data.get("word"))
        ]
        chosen = matching[rng.randrange(len(matching))]
        lines.append(
            f"\n✦ {escape_mdv2(_blank_word(chosen, card_data.get('word'), count=1))}"
        )
        hints = _fill_blank_hints(card_data, toggles, rng)
        for hint in hints:
            blanked = _blank_word(hint, card_data.get("word", ""))
            if blanked and blanked.strip():
                lines.append(f"\n{escape_mdv2(blanked)}")
    elif prompt_type == "meaning":
        meaning = card_data.get("fa_meaning", "")
        lines.append(f"\n{escape_mdv2(f'🧠 چه واژه‌ای به معنای «{meaning}» است؟')}")
        if toggles.get("explanation") and card_data.get("fa_explanation"):
            hint = _blank_word(
                str(card_data.get("fa_explanation")), card_data.get("word", "")
            )
            if hint and hint.strip():
                lines.append(f"\n{escape_mdv2('راهنما: ' + hint)}")
    elif prompt_type == "synonym":
        syn_items, ant_items = _draw_synonym_items(card_data, toggles, rng)
        lines.append(f"\n{escape_mdv2(_synonym_instruct(syn_items, ant_items))}")
    elif prompt_type == "direct_translate":
        lang_label = language_label(lang)
        meaning = card_data.get("fa_meaning", "")
        lines.append(
            f"\n{escape_mdv2(f'🧠 معادل {lang_label} «{meaning}» را به یاد بیاور.')}"
        )

    lines.append(f"\n{escape_mdv2(SRS_FRONT_SUB_INSTRUCTION)}")
    if footer:
        lines.append(f"\n{escape_mdv2(footer)}")
    return "\n".join(lines)


def format_srs_back_stage(
    card_data: dict,
    *,
    toggles: dict[str, bool],
    phonetic_lines: list[str] | None = None,
    footer: str = "",
    badge: str = "",
) -> str:
    """Render the revealed back stage: full card gated by the display-toggles
    (§8 always full detail; each section respects its toggle). The review badge
    lives on the pre-reveal front stage only (owner bug report 2026-08-15);
    ``badge`` is optional for the first-exposure immediate mode (owner lock)."""
    word = escape_mdv2(card_data.get("word", ""))
    fa_meaning = escape_mdv2(card_data.get("fa_meaning", ""))
    fa_expl = escape_mdv2(card_data.get("fa_explanation", ""))

    lines = [f"*{word}*"]
    if phonetic_lines:
        lines.extend(phonetic_lines)

    if badge:
        lines.append(f"\n{escape_mdv2(badge)}")

    lines.append(f"\n✤ *{fa_meaning}*")
    if fa_expl and toggles.get("explanation"):
        lines.append(f"\n{fa_expl}")

    if toggles.get("synonyms"):
        syn = (
            "، ".join(
                escape_mdv2(item) for item in (card_data.get("synonyms") or [])
            )
            or "—"
        )
        lines.append(f"\n🟢 *مترادف:* {syn}")
    if toggles.get("antonyms"):
        ant = (
            "، ".join(
                escape_mdv2(item) for item in (card_data.get("antonyms") or [])
            )
            or "—"
        )
        lines.append(f"🔴 *متضاد:* {ant}")

    if toggles.get("examples"):
        examples = (card_data.get("examples") or [])[:2]
        translations = (card_data.get("example_translations") or [])[:2]
        translations_visible = toggles.get("example_translations")
        label = escape_mdv2(
            "مثال‌ها + ترجمه" if translations_visible else "مثال‌ها"
        )
        lines.append(f"\n📝 *{label}:*")
        for index, example in enumerate(examples):
            lines.append(f"✦ {escape_mdv2(example)}")
            if translations_visible and index < len(translations):
                lines.append(f"||{escape_mdv2(translations[index])}||")

    if toggles.get("grammar_tip") and card_data.get("grammar_tip"):
        lines.append(
            f"\n✍️ *نکته‌ی گرامری:*\n{escape_mdv2(card_data.get('grammar_tip'))}"
        )

    lines.append(f"\n{escape_mdv2(SRS_POST_REVEAL)}")
    if footer:
        lines.append(f"\n{escape_mdv2(footer)}")
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


def phonetic_lines(value: str | dict | None) -> list[str]:
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


def format_grammar_tip(data: dict, usage_text: str):
    """Build the learner-facing grammar-tip message as a ``send_pretty.Message``.

    The single MDV2 render choke for the grammar-tip path (R6/F6): the AI-returned
    field dict and the usage line arrive here raw, are placed into
    ``Plain``/``Bold``/``Code`` spans, and are escaped exactly once by the
    ``send_pretty`` renderer at delivery time. Handlers never call
    ``escape_mdv2`` directly for this message, so a missed field cannot produce
    a ``BadRequest`` ``can't parse entities`` failure.
    """
    from services.send_pretty import Message, bold, code, plain

    # Normalise missing/null AI fields to the empty string so they render as
    # an empty span, exactly like the escaped path they replaced (escape_mdv2
    # returns "" for falsy input). Without this, send_pretty's ``_span`` would
    # str()-ify ``None`` and render the literal ``None`` to the learner.
    msg = Message()
    msg.add_line("✍️ ", bold(data.get("title") or ""))
    msg.add_line(plain(""))
    msg.add_line(plain(data.get("explanation") or ""))
    msg.add_line(plain(""))
    msg.add_line(code(data.get("example") or ""))
    msg.add_line(plain(""))
    msg.add_line(plain(usage_text))
    return msg


# Single source of truth for the ask-word entry / re-prompt copy (issue #357).
# The per-word cap is interpolated from the validator so the learner-facing
# copy cannot drift from services/utils/validation._CUSTOM_WORD_MAX_WORDS.
ASK_WORD_PROMPT = (
    "✨ دوست داری چه واژه یا عبارتی رو یاد بگیری تا برات کارتشو بسازم؟\n"
    f"(برای مثال: یک کلمه‌ی جدید، اصطلاح یا فعل — حداکثر {_CUSTOM_WORD_MAX_WORDS} کلمه)"
)


# ---------------------------------------------------------------------------
# Session Summary Report rendering (R2–R9)
# ---------------------------------------------------------------------------

# Jalali month names (jdatetime month number 1..12 → Persian).
_JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)

# Persian weekday names Monday=0 -> دوشنبه ... Sunday=6 -> یکشنبه ; derived from Gregorian weekday.
_JALALI_WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")


def _weekday_name(dt: datetime.date) -> str:
    """Persian weekday for a Gregorian date."""
    return _JALALI_WEEKDAYS[dt.weekday()]


def _parse_iso_to_app_tz(iso_str: str) -> datetime.datetime | None:
    """Parse ISO string and convert to APP_TZ. Returns None on failure."""
    if not iso_str or not isinstance(iso_str, str):
        return None
    raw = iso_str.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    try:
        return dt.astimezone(APP_TZ)
    except Exception:
        return dt


def jalali_day_label(iso_str: str) -> str:
    """Convert UTC ISO datetime to Tehran Jalali day label.

    Returns "{weekday} {day} {month} {year}" with Persian digits, e.g.
    "جمعه ۹ خرداد ۱۴۰۴". Falls back to Gregorian "YYYY/MM/DD weekday" style
    when jdatetime unavailable. Returns "—" for empty/invalid input.
    """
    if not iso_str or not isinstance(iso_str, str):
        return "—"
    dt_app = _parse_iso_to_app_tz(iso_str)
    if dt_app is None:
        return "—"
    greg_date = dt_app.date()
    weekday = _weekday_name(greg_date)
    if jdatetime is not None:
        try:
            jd = jdatetime.date.fromgregorian(date=greg_date)
            return to_persian_digits(f"{weekday} {jd.day} {_JALALI_MONTHS[jd.month - 1]} {jd.year}")
        except Exception:
            pass
    # Fallback: Gregorian numeric with Persian digits + weekday (no Jalali month when jdatetime absent)
    return to_persian_digits(f"{weekday} {greg_date.day}/{greg_date.month}/{greg_date.year}")


def jalali_time_label(iso_str: str) -> str:
    """Convert UTC ISO datetime to Tehran HH:MM with Persian digits.

    Returns "—" for empty/invalid input.
    """
    if not iso_str or not isinstance(iso_str, str):
        return "—"
    dt_app = _parse_iso_to_app_tz(iso_str)
    if dt_app is None:
        return "—"
    return to_persian_digits(f"{dt_app.hour:02d}:{dt_app.minute:02d}")


def reports_jalali_group_key(iso_str: str) -> str:
    """Gregorian YYYY-MM-DD in APP_TZ for /reports grouping (R6, single source)."""
    dt_app = _parse_iso_to_app_tz(iso_str)
    if dt_app is None:
        s = (iso_str or "").strip()
        return s[:10] if len(s) >= 10 else ""
    return dt_app.date().isoformat()


# Public alias — config/handlers must import this, not the private _parse helper.
parse_iso_to_app_tz = _parse_iso_to_app_tz

# Single source for reports day-key validation + sort (Kilo §3)
_ISO_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_iso_day_key(s: str) -> bool:
    """True if s is YYYY-MM-DD (reports day key)."""
    return bool(_ISO_DAY_RE.match(s or ""))


def reports_day_sort_key(k: str) -> tuple[int, str]:
    """Sort key for reports day keys: ISO days first (DESC), fallback last."""
    return (1, k) if _ISO_DAY_RE.match(k or "") else (0, k)

# Tier → header line (R5/R7). Values are static, so no escaping needed.
_TIER_LABEL = {
    "excellent": "⚡️ پیشرفت کلی این نشست: عالی",
    "acceptable": "⚡️ پیشرفت کلی این نشست: قابل قبول",
    "needs_improvement": "⚡️ پیشرفت کلی این نشست: نیاز به بهبود",
}


def _app_date() -> datetime.date:
    """Today's date in the application timezone (``APP_TIMEZONE``).

    Stored ``next_review_at``/prior dates are derived from app-time timestamps
    (``words.py`` ``astimezone(APP_TZ)``), so the relative-date baseline must be
    the app day too — otherwise labels flip at local midnight. Falls back to the
    config ``_app_today()`` source of truth.
    """
    return datetime.date.fromisoformat(_app_today())


def _jalali_day_month(iso_date: str) -> str:
    """Convert an ISO ``YYYY-MM-DD`` to ``{day} {jalali month name}`` with
    Persian digits (e.g. ``۲۹ مرداد``). Falls back to Gregorian day/month when
    jdatetime is unavailable."""
    d = datetime.date.fromisoformat(iso_date)
    if jdatetime is not None:
        try:
            j = jdatetime.date.fromgregorian(date=d)
            return to_persian_digits(f"{j.day} {_JALALI_MONTHS[j.month - 1]}")
        except Exception:
            pass
    # Fallback: Gregorian month name via Jalali array (approximate) or numeric
    return to_persian_digits(f"{d.day} {_JALALI_MONTHS[d.month - 1]}")


def _relative_next_review(iso_date: str, today: datetime.date) -> str:
    """Relative-first date for the ``بعدی`` field (R3).

    today→امروز, +1→فردا, +2→پس‌فردا, +3..6→«{n} روز دیگه», ≥7 (or past)→Jalali
    absolute date. Returns "" for an unparseable date.
    """
    try:
        d = datetime.date.fromisoformat(iso_date)
    except (TypeError, ValueError, AttributeError):
        return ""
    delta = (d - today).days
    if delta < 0:
        return _jalali_day_month(iso_date)
    if delta == 0:
        return "امروز"
    if delta == 1:
        return "فردا"
    if delta == 2:
        return "پس‌فردا"
    if delta <= 6:
        return f"{to_persian_digits(delta)} روز دیگه"
    return _jalali_day_month(iso_date)


# Single source for the session memory-stage buckets (locked r7, T3).
# Buckets derive from FSRS stability_after (S) + difficulty (D) on each
# WordReviewRecord — never from grade/activity (grade is only a proxy).
_STAGE_ICON = {
    "learning": "🌱",
    "familiar": "👀",
    "learned": "📚",
    "stable": "🧠",
}


def _stage_for_record(stability_after, difficulty) -> str:
    """Memory-stage key for one review record (locked r7, single source).

    Base bucket from S: S<2.5 → learning; S<7 → familiar; S<21 →
    learned; S>=21 → stable; missing/None S → learning. D gates then
    apply: D>=6.5 forces learning; 6.0<=D<6.5 caps learned/stable at
    familiar; a stable base requires D<4, else D<6 → learned, else
    familiar. Returns one of ``learning``/``familiar``/``learned``/
    ``stable``.
    """
    try:
        d = None if difficulty is None else float(difficulty)
    except (TypeError, ValueError):
        d = None
    if d is not None and d >= 6.5:
        return "learning"
    try:
        s = None if stability_after is None else float(stability_after)
    except (TypeError, ValueError):
        s = None
    if s is None or s < 2.5:
        base = "learning"
    elif s < 7:
        base = "familiar"
    elif s < 21:
        base = "learned"
    else:
        base = "stable"
    if d is None:
        return base
    if 6.0 <= d < 6.5 and base in ("learned", "stable"):
        return "familiar"
    if base == "stable":
        if d < 4:
            return "stable"
        if d < 6:
            return "learned"
        return "familiar"
    return base


def _stage_modifier(difficulty) -> str | None:
    """Display-only difficulty modifier — never changes the bucket.

    D<=2.5 → ``آسان``; D>=6 → ``سخت``; otherwise (or missing) None.
    """
    try:
        d = None if difficulty is None else float(difficulty)
    except (TypeError, ValueError):
        return None
    if d is None:
        return None
    if d <= 2.5:
        return "آسان"
    if d >= 6:
        return "سخت"
    return None


def _stage_counts(records) -> tuple[int, int, int, int]:
    """Count records into the (🌱 👀 📚 🧠) buckets via _stage_for_record.

    Takes the per-word records (``report.rows``); every record lands in
    exactly one bucket, so the four always sum to ``len(records)``.
    """
    learning = familiar = learned = stable = 0
    for r in records or ():
        stage = _stage_for_record(
            getattr(r, "stability_after", None),
            getattr(r, "difficulty", None),
        )
        if stage == "familiar":
            familiar += 1
        elif stage == "learned":
            learned += 1
        elif stage == "stable":
            stable += 1
        else:
            learning += 1
    return (learning, familiar, learned, stable)


def _heat_label(used: int, total: int) -> tuple[str, str]:
    """Fire icons + label for today's session heat (T3, no streak).

    Percent = used/total*100 (total<=0 → 0): 1–39% → 🔥 یک‌آتیشه,
    40–99% → 🔥🔥 دوآتیشه, 100% (used>=total, total>0) → 🔥🔥🔥 سه‌آتیشه,
    0 → 🔥 یک‌آتیشه (started). Returns (fires, label).
    """
    try:
        u, t = int(used), int(total)
    except (TypeError, ValueError):
        return "🔥", "یک‌آتیشه"
    if t > 0 and u >= t:
        return "🔥🔥🔥", "سه‌آتیشه"
    pct = round(u / t * 100) if t > 0 else 0
    if pct >= 40:
        return "🔥🔥", "دوآتیشه"
    return "🔥", "یک‌آتیشه"


def format_session_summary(report, *, is_admin: bool = False, rng=None, heat_used=None, heat_total=None, m01_note: str | None = None):
    """Build the session summary as a Rich structured ``Message`` (T4).

    Layout mirrors the demo ``demo_report_summary_v2``: ``heading(3)`` title,
    ``quote`` motivational block (tier label + data-driven line), a 2-col
    stats table (یادآوری/امتیاز/کارت — heat lives in the امتیاز row), and a
    4-col 🌱👀📚🧠 counts mini-table. ``is_admin`` is kept for signature
    compat but renders identically for True/False (no admin diagnostics;
    dedicated telemetry is deferred). Dynamic values ride ``Plain`` spans and
    are escaped exactly once by the renderer. ``m01_note`` (issue #467) is an
    optional raw pre-rendered M01 same-day-dues line (``render_m01`` output,
    escaped once here via ``Plain``) appended as a quote; ``None``/empty
    leaves existing renders unchanged.
    """
    from services.send_pretty import Message, heading, plain, quote, table

    _ = is_admin  # signature compat only — output is identical for both.
    from services.session.summary import classify_tier, pick_motivation

    msg = Message()
    msg.add_line(heading(3, plain("📊 گزارش نشست مطالعه")))

    motivation = pick_motivation(report, rng=rng)
    if motivation is not None:
        tier = classify_tier(report.recall_rate)
        msg.add_line(quote(plain(f"{_TIER_LABEL[tier]}\n{motivation}")))

    # M01 short-interval same-day note (issue #467): appended by the
    # handler/summary-render site that already holds heat params; None keeps
    # existing callers byte-identical.
    if m01_note:
        msg.add_line(quote(plain(m01_note)))

    if report.recall_rate is not None:
        pct = to_persian_digits(round(report.recall_rate * 100))
        recall_val = f"🎯 {pct}٪"
        if report.avg_stability_after is not None:
            days = to_persian_digits(max(1, round(report.avg_stability_after)))
            recall_val += f" · ~{days} روز"
        stat_rows = [(plain("یادآوری"), plain(recall_val))]
        if heat_used is not None and heat_total is not None:
            fires, label = _heat_label(heat_used, heat_total)
            stat_rows.append((
                plain("امتیاز"),
                plain(
                    f"{fires} {label} · "
                    f"{to_persian_digits(heat_used)} از "
                    f"{to_persian_digits(heat_total)} نشست"
                ),
            ))
        stat_rows.append((
            plain("کارت"),
            plain(
                f"{to_persian_digits(report.learned_count)} تازه · "
                f"{to_persian_digits(report.reviewed_count)} مرور"
            ),
        ))
        msg.add_line(table(stat_rows[0], *stat_rows[1:]))
    else:
        msg.add_line(table(
            (
                plain("کارت"),
                plain(
                    f"{to_persian_digits(report.learned_count)} تازه · "
                    f"{to_persian_digits(report.reviewed_count)} مرور"
                ),
            ),
        ))

    learning, familiar, learned, stable = _stage_counts(report.rows)
    msg.add_line(table(
        (plain("🌱"), plain("👀"), plain("📚"), plain("🧠")),
        (
            plain(to_persian_digits(learning)),
            plain(to_persian_digits(familiar)),
            plain(to_persian_digits(learned)),
            plain(to_persian_digits(stable)),
        ),
    ))
    return msg


def format_session_detail_page(
    records,
    page_index: int,
    total_pages: int,
    *,
    is_admin: bool = False,
    today: datetime.date | None = None,
):
    """Build one page of the paged word list as a Rich ``Message`` (T4).

    3-col table (واژه|وضعیت|مرور) mirroring ``demo_report_detail_v2``:
    وضعیت is the S/D stage icon (``_stage_for_record``) plus the
    display-only modifier (``_stage_modifier``), e.g. ``🌱 (سخت)``;
    مرور is ``📅 {relative next}`` plus ``⏰ {prior}`` for reviewed
    cards. An empty page renders the ``هنوز واژه‌ای نیست``
    row. Pagination (``PAGE_SIZE``) is unchanged. ``is_admin`` is kept for
    signature compat but renders identically for True/False. ``today`` is
    injectable for deterministic relative-date tests.
    """
    from services.send_pretty import Message, heading, plain, table

    _ = is_admin  # signature compat only — output is identical for both.
    today = today or _app_date()
    msg = Message()
    msg.add_line(heading(
        3,
        plain(
            f"📋 واژه‌ها — صفحه {to_persian_digits(page_index + 1)} از "
            f"{to_persian_digits(total_pages)}"
        ),
    ))
    rows: list[tuple] = []
    if not records:
        rows.append((plain(""), plain(""), plain("هنوز واژه‌ای نیست")))
    for r in records:
        icon = _STAGE_ICON[_stage_for_record(r.stability_after, r.difficulty)]
        mod = _stage_modifier(r.difficulty)
        status = f"{icon} ({mod})" if mod else icon
        review_bits: list[str] = []
        if r.next_review_date:
            review_bits.append(f"📅 {_relative_next_review(r.next_review_date, today)}")
        if r.activity_type == "srs_review" and r.prior_review_date:
            review_bits.append(f"⏰ {_jalali_day_month(r.prior_review_date)}")
        مرور = " ".join(review_bits) if review_bits else "—"
        rows.append((plain(r.word), plain(status), plain(مرور)))
    msg.add_line(table(
        (plain("واژه"), plain("وضعیت"), plain("مرور")),
        *rows,
    ))
    return msg


def format_summary_legend():
    """Build the symbol-legend message as a Rich ``Message`` (T4).

    ``(نماد|معنا)`` table with the 8 showcase-gallery rows verbatim:
    🌱👀📚🧠 stages, (آسان)/(سخت) modifiers, 📅/⏰ reviews. All static.
    """
    from services.send_pretty import Message, bold, heading, plain, table

    msg = Message()
    msg.add_line(heading(3, plain("📖 گام‌های تثبیت در حافظه")))
    msg.add_line(table(
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
    return msg
