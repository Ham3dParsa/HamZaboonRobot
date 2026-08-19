import datetime
import html
import json
import random
import re

import jdatetime

from config import _app_today, daily_word_query_limit_for_plan
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


def format_review_badge(days: int) -> str:
    """Learner-facing review badge for the staged-reveal front/back stages (R5)."""
    return f"⏰ آخرین مرور: {to_persian_digits(days)} روز پیش"


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


def _fill_blank_hint(card_data: dict, toggles: dict[str, bool]) -> str:
    """Local-DB hint for the fill_blank prompt, synonym → antonym → meaning."""
    if toggles.get("synonyms") and card_data.get("synonyms"):
        return SRS_HINT_SYNONYM.format(item=card_data["synonyms"][0])
    if toggles.get("antonyms") and card_data.get("antonyms"):
        return SRS_HINT_ANTONYM.format(item=card_data["antonyms"][0])
    if card_data.get("fa_meaning"):
        return SRS_HINT_MEANING.format(meaning=card_data["fa_meaning"])
    return ""


def _join_guillemets(items: list[str]) -> str:
    return "«" + "» و «".join(str(item) for item in items) + "»"


def _synonym_instruct(syn_items: list[str], ant_items: list[str]) -> str:
    """Prompt sentence built from the drawn set (R2: only-synonyms /
    only-antonyms / both sentence styles)."""
    if syn_items and ant_items:
        return (
            f"🧠 چه واژه‌ای مترادف‌های {_join_guillemets(syn_items)} "
            f"و متضادهای {_join_guillemets(ant_items)} دارد؟"
        )
    if syn_items:
        return f"🧠 چه واژه‌ای مترادف‌های {_join_guillemets(syn_items)} دارد؟"
    return f"🧠 چه واژه‌ای متضادهای {_join_guillemets(ant_items)} دارد؟"


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
    if toggles.get("examples") and any(
        _example_has_word(example, card_data.get("word"))
        for example in (card_data.get("examples") or [])
    ):
        eligible.append("fill_blank")
    if card_data.get("fa_meaning"):
        eligible.append("meaning")
        eligible.append("direct_translate")
    visible_syn = toggles.get("synonyms") and bool(card_data.get("synonyms"))
    visible_ant = toggles.get("antonyms") and bool(card_data.get("antonyms"))
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
        hint = _blank_word(_fill_blank_hint(card_data, toggles), card_data.get("word", ""))
        if hint and hint.strip():
            lines.append(f"\n{escape_mdv2(hint)}")
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


# Single source of truth for the ask-word entry / re-prompt copy (issue #357).
# The per-word cap is interpolated from the validator so the learner-facing
# copy cannot drift from services/utils/validation._CUSTOM_WORD_MAX_WORDS.
ASK_WORD_PROMPT = (
    "✨ دوست داری چه واژه یا عبارتی رو یاد بگیری تا برات کارتشو بسازم؟\n"
    f"(برای مثال: یک کلمه‌ی جدید، اصطلاح یا فعل — حداکثر {_CUSTOM_WORD_MAX_WORDS} کلمه)"
)


def word_query_usage_text(row: dict) -> str:
    """Return the today's word-query usage summary line for a users row.

    Single source for the learner-facing usage line used by the word-query
    closing reply (bot.py). Mirrors the historical logic in handlers/user.py so
    all callers stay in sync.

    This is NOT a pure formatter: it reads the plan spec from the DB via
    ``daily_word_query_limit_for_plan`` to resolve the per-plan quota, so the
    caller must pass an already-fetched users row.
    """
    used = row["words_asked_today"] or 0
    if row["words_asked_date"] != _app_today():
        used = 0
    limit = daily_word_query_limit_for_plan(row["plan"] or "free")
    if limit < 0:
        return f"📊 استفاده امروز: {used} / نامحدود"
    remaining = max(limit - used, 0)
    return f"📊 استفاده امروز: {used}/{limit} · باقی‌مانده: {remaining}"


# ---------------------------------------------------------------------------
# Session Summary Report rendering (R2–R9)
# ---------------------------------------------------------------------------

_NEW_BADGE = "✨ جدید"
_REVIEW_BADGE = "🔁 مرور"

# Jalali month names (jdatetime month number 1..12 → Persian).
_JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)

# Tier → header line (R5/R7). Values are static, so no escaping needed.
_TIER_LABEL = {
    "excellent": "⚡️ پیشرفت کلی این نشست: عالی",
    "acceptable": "⚡️ پیشرفت کلی این نشست: قابل قبول",
    "needs_improvement": "⚡️ پیشرفت کلی این نشست: نیاز به بهبود",
}


def _utc_today() -> datetime.date:
    """Today's date in UTC — matches how stored ``next_review_at``/prior dates
    are derived (sliced from UTC timestamps) so relative-date math is stable."""
    return datetime.datetime.now(datetime.timezone.utc).date()


def _jalali_day_month(iso_date: str) -> str:
    """Convert an ISO ``YYYY-MM-DD`` to ``{day} {jalali month name}`` with
    Persian digits (e.g. ``۲۹ مرداد``)."""
    d = datetime.date.fromisoformat(iso_date)
    j = jdatetime.date.fromgregorian(date=d)
    return to_persian_digits(f"{j.day} {_JALALI_MONTHS[j.month - 1]}")


def _relative_next_review(iso_date: str, today: datetime.date) -> str:
    """Relative-first date for the ``بعدی`` field (R3).

    today→امروز, +1→فردا, +2→پس‌فردا, +3..6→«{n} روز دیگه», ≥7 (or past)→Jalali
    absolute date. Returns "" for an unparseable date.
    """
    try:
        d = datetime.date.fromisoformat(iso_date)
    except (TypeError, ValueError):
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


def _difficulty_label(difficulty: float | None) -> str | None:
    """Plain learner-facing difficulty label (R2) — no raw number."""
    if difficulty is None:
        return None
    if difficulty >= 6:
        return "🔴 سخت"
    if difficulty >= 3:
        return "🟡 متوسط"
    return "🟢 راحت"


def _session_badge(activity_type: str) -> str:
    """Badge for a report row: ✨ new, 🔁 review (and any other activity)."""
    return _NEW_BADGE if activity_type == "first_exposure" else _REVIEW_BADGE


def _admin_extra(r) -> str:
    """Admin-only diagnostic block (R9), grouped and marked ``(فقط ادمین)``.

    Raw numeric difficulty/stability plus Δ and interval — the only place raw
    numbers appear. Returns "" (no block) when nothing is available.
    """
    bits: list[str] = []
    if r.difficulty is not None:
        bits.append(f"سختی {_fmt_stability(r.difficulty)}")
    if r.stability_after is not None:
        bits.append(f"پایداری {_fmt_stability(r.stability_after)}")
    if r.stability_before is not None and r.stability_after is not None:
        bits.append(f"Δ{_fmt_stability(r.stability_after - r.stability_before)}")
    if r.interval_days is not None:
        bits.append(f"فاصله {_fmt_stability(r.interval_days)} روز")
    if not bits:
        return ""
    return f"(فقط ادمین: {', '.join(bits)})"


def _fmt_stability(value: float | None) -> str:
    """Round a stability value to one decimal as Persian digits, or '—'."""
    if value is None:
        return "—"
    return to_persian_digits(f"{value:.1f}")


def format_session_summary(report, *, is_admin: bool = False, rng=None):
    """Build the learner (or admin) session summary as a ``Message`` (R7).

    ``report`` is a :class:`services.session.summary.SessionReport`. The tier /
    motivational block (R5/R6) sits above the stats; count lines are shown only
    when nonzero; the rate + average-stability line is single. ``rng`` seeds the
    motivational-variant selection so tests are deterministic. Dynamic values go
    into ``Plain`` spans and are escaped exactly once by the renderer.
    """
    from services.send_pretty import Message, plain
    from services.session.summary import classify_tier, pick_motivation

    msg = Message()
    msg.add_line(plain("📊 گزارش نشست مطالعه"))
    msg.add_line(plain(""))

    motivation = pick_motivation(report, rng=rng)
    if motivation is not None:
        tier = classify_tier(report.recall_rate)
        msg.add_line(plain(_TIER_LABEL[tier]))
        msg.add_line(plain(motivation))
        msg.add_line(plain(""))

    if report.learned_count:
        msg.add_line(
            plain(f"✨ {to_persian_digits(report.learned_count)} واژه تازه یاد گرفتی")
        )
    if report.reviewed_count:
        msg.add_line(
            plain(f"🔁 {to_persian_digits(report.reviewed_count)} واژه مرور کردی")
        )

    stats_parts: list[str] = []
    if report.recall_rate is not None:
        pct = to_persian_digits(round(report.recall_rate * 100))
        stats_parts.append(f"🎯 نرخ یادآوری: {pct}٪")
    if report.avg_stability_after is not None:
        days = to_persian_digits(max(1, round(report.avg_stability_after)))
        stats_parts.append(f"میانگین پایداری: ~{days} روز")
    if stats_parts:
        msg.add_line(plain(" · ".join(stats_parts)))

    if is_admin and report.avg_stability_delta is not None:
        msg.add_line(
            plain(f"میانگین تغییر پایداری: {_fmt_stability(report.avg_stability_delta)}")
        )
    return msg


def format_session_detail_page(
    records,
    page_index: int,
    total_pages: int,
    *,
    is_admin: bool = False,
    today: datetime.date | None = None,
):
    """Build one page of the paged word list as a ``Message`` (R2/R9).

    Learner rows: line 1 ``{word} {badge}``; line 2 ``{difficulty label} ·
    📅 {relative date} · امتیاز {n}``; review cards get a third line
    ``آخرین مرور: {jalali} · امتیاز {n}``. Admins additionally see a trailing
    ``(فقط ادمین: …)`` diagnostic block (raw numbers, Δ, فاصله). ``today`` is
    injectable for deterministic relative-date tests.
    """
    from services.send_pretty import Message, plain

    today = today or _utc_today()
    msg = Message()
    msg.add_line(
        plain(
            f"📋 واژه‌ها — صفحه {to_persian_digits(page_index + 1)} از "
            f"{to_persian_digits(total_pages)}"
        )
    )
    for r in records:
        badge = _session_badge(r.activity_type)
        msg.add_line(plain(f"{r.word}  {badge}"))

        parts: list[str] = []
        diff_label = _difficulty_label(r.difficulty)
        if diff_label:
            parts.append(diff_label)
        if r.next_review_date:
            parts.append(f"📅 {_relative_next_review(r.next_review_date, today)}")
        if r.grade is not None:
            parts.append(f"امتیاز {to_persian_digits(r.grade)}")
        if parts:
            msg.add_line(plain(" · ".join(parts)))

        admin_extra = _admin_extra(r) if is_admin else ""
        if r.activity_type == "srs_review":
            review_parts: list[str] = []
            if r.prior_review_date:
                review_parts.append(
                    f"آخرین مرور: {_jalali_day_month(r.prior_review_date)}"
                )
            if r.grade is not None:
                review_parts.append(f"امتیاز {to_persian_digits(r.grade)}")
            line3 = " · ".join(review_parts)
            if admin_extra:
                line3 = f"{line3}  {admin_extra}" if line3 else admin_extra
            if line3:
                msg.add_line(plain(line3))
        elif admin_extra:
            msg.add_line(plain(admin_extra))
    return msg


def format_summary_legend():
    """Build the symbol-legend message opened by the legend button (R8).

    Covers ✨🔁 (activity), 🔴🟡🟢 (difficulty labels), and 📅 (next review).
    Stability-color rows (⚪🔵🟣) were retired with the raw-number removal (R2),
    so they are intentionally absent here. All text is static Persian.
    """
    from services.send_pretty import Message, plain

    msg = Message()
    msg.add_line(plain("📖 راهنمای نمادها"))
    msg.add_line(plain(""))
    msg.add_line(plain("✨ جدید  ·  🔁 مرور"))
    msg.add_line(plain(""))
    msg.add_line(plain("سختی:"))
    msg.add_line(plain("🔴 بالا (۶ و بیشتر)"))
    msg.add_line(plain("🟡 متوسط (۳ تا ۵٫۹)"))
    msg.add_line(plain("🟢 راحت (کمتر از ۳)"))
    msg.add_line(plain(""))
    msg.add_line(plain("📅 مرور بعدی"))
    return msg
