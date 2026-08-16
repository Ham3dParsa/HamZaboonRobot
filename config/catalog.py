"""Canonical learner-facing language, goal, and level metadata."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageOption:
    code: str
    name_fa: str
    example_name: str
    guidance: str = ""


@dataclass(frozen=True)
class GoalOption:
    code: str
    name_fa: str
    prompt_hint: str


@dataclass(frozen=True)
class LevelOption:
    code: str
    name_fa: str
    cefr: str
    prompt_guidance: str


LANGUAGES = {
    "en": LanguageOption(
        "en",
        "انگلیسی",
        "انگلیسی",
        "برای انگلیسی، صرف فعل و کاربرد واج‌ها را متناسب با سطح کاربر رعایت کن.",
    ),
    "es": LanguageOption(
        "es",
        "اسپانیایی",
        "اسپانیایی",
        "برای اسپانیایی، جنسیت اسم‌ها، صرف فعل و کاربرد درست حروف تعریف را متناسب با سطح کاربر رعایت کن.",
    ),
    "ar": LanguageOption(
        "ar",
        "عربی",
        "عربی",
        "برای عربی، اعراب‌گذاری و ساختارهای صرفی را در حد نیاز و متناسب با سطح کاربر رعایت کن.",
    ),
    "fr": LanguageOption(
        "fr",
        "فرانسوی",
        "فرانسوی",
        "برای فرانسوی، جنسیت اسم‌ها، صرف فعل و حروف تعریف را متناسب با سطح کاربر رعایت کن.",
    ),
    "de": LanguageOption(
        "de",
        "آلمانی",
        "آلمانی",
        "برای آلمانی، جنسیت اسم‌ها (der/die/das)، حالت‌های دستوری "
        "(Nominativ/Akkusativ/Dativ/Genitiv)، صرف فعل، حروف بزرگ و جایگاه فعل "
        "را دقیق و متناسب با سطح کاربر رعایت کن.",
    ),
    "tr": LanguageOption(
        "tr",
        "ترکی استانبولی",
        "ترکی استانبولی",
        "برای ترکی استانبولی، هماهنگی واکه‌ها، پسوندها و تلفظ شفاف واژه را متناسب با سطح کاربر رعایت کن.",
    ),
    "he": LanguageOption(
        "he",
        "عبری",
        "عبری",
        "برای عبری، ساخت ریشه‌ای و آواهای متناسب با سطح کاربر را رعایت کن.",
    ),
}

GOALS = {
    "general": GoalOption(
        "general",
        "عمومی",
        "کلمه باید برای مکالمه و زندگی روزمره کاربردی باشد، نه آکادمیک صرف.",
    ),
    "konkur": GoalOption(
        "konkur",
        "کنکور",
        "کلمه باید نزدیک به دامنه‌ی واژگان کنکور زبان‌های خارجی در ایران باشد.",
    ),
    "toefl": GoalOption(
        "toefl",
        "تافل",
        "کلمه باید در سطح واژگان آزمون TOEFL باشد؛ نه خیلی ساده، نه به‌شدت نادر.",
    ),
}

LEVELS = {
    "beginner": LevelOption(
        "beginner",
        "مبتدی",
        "A1/A2",
        "از واژه‌ها و ساختارهای پایه و پرتکرار استفاده کن و توضیح را ساده نگه دار.",
    ),
    "intermediate": LevelOption(
        "intermediate",
        "متوسط",
        "B1/B2",
        "از واژه‌ها و ساختارهای متوسط و کاربردی استفاده کن و یک نکته‌ی ظریف آموزشی اضافه کن.",
    ),
    "advanced": LevelOption(
        "advanced",
        "پیشرفته",
        "C1/C2",
        "از واژه‌ها و ساختارهای پیشرفته اما معتبر استفاده کن و تفاوت کاربرد رسمی/غیررسمی را در صورت نیاز توضیح بده.",
    ),
}

DEFAULT_LEVEL = "beginner"

# Canonical display-toggle registry (#338 R7/R9/R10/R11). The learner can
# toggle each field on/off per-user; admin-global defaults and an admin
# per-user override layer on top. Prompt-pool eligibility reads these same
# fields (e.g. synonyms off removes the `synonym` prompt), so the registry
# must stay the single source of truth consumed by storage, menus, prompts,
# and validation.
DISPLAY_TOGGLE_FIELDS = (
    "explanation",
    "synonyms",
    "antonyms",
    "examples",
    "example_translations",
    "grammar_tip",
    "phonetic",
)

HIGH_VALUE_TOGGLES = frozenset(
    {"explanation", "synonyms", "antonyms", "examples"}
)

LOW_VALUE_TOGGLES = frozenset(
    {"phonetic", "grammar_tip", "example_translations"}
)

DISPLAY_TOGGLE_DEFAULTS = {field: True for field in DISPLAY_TOGGLE_FIELDS}

# Canonical identifier-namespace registry. Maps a stable namespace name to the
# dict whose keys are the stable learner-facing identifiers for that family.
# This is the single enumeration of catalog identifier namespaces so the
# `catalog-identifiers` seam can be claimed, enumerated, and validated
# precisely (SEAMS.md "Catalog identifiers").
CATALOG_NAMESPACES = {
    "languages": LANGUAGES,
    "goals": GOALS,
    "levels": LEVELS,
}


def catalog_namespace(name: str) -> dict:
    """Return the catalog identifier dict for a namespace name.

    Raises KeyError for unknown namespaces so callers fail fast rather than
    silently reading an empty or wrong namespace.
    """
    return CATALOG_NAMESPACES[name]


def language_label(code: str) -> str:
    option = LANGUAGES.get(code)
    return option.name_fa if option else code


def example_language_label(code: str) -> str:
    option = LANGUAGES.get(code)
    return option.example_name if option else code


def language_guidance(code: str) -> str:
    option = LANGUAGES.get(code)
    return option.guidance if option else ""


def goal_label(code: str) -> str:
    option = GOALS.get(code)
    return option.name_fa if option else "عمومی"


def goal_hint(code: str) -> str:
    option = GOALS.get(code)
    return option.prompt_hint if option else ""


def level_label(code: str) -> str:
    option = LEVELS.get(code) or LEVELS[DEFAULT_LEVEL]
    return f"{option.name_fa} ({option.cefr})"


def level_cefr(code: str) -> str:
    option = LEVELS.get(code)
    return option.cefr if option else ""


def level_prompt_guidance(code: str) -> str:
    option = LEVELS.get(code) or LEVELS[DEFAULT_LEVEL]
    return option.prompt_guidance


def validate_catalog() -> None:
    for code, option in LANGUAGES.items():
        if code != option.code or not option.name_fa or not option.example_name:
            raise ValueError(f"invalid language catalog entry: {code}")
    for code, option in GOALS.items():
        if code != option.code or not option.name_fa or not option.prompt_hint:
            raise ValueError(f"invalid goal catalog entry: {code}")
    for code, option in LEVELS.items():
        if (
            code != option.code
            or not option.name_fa
            or not option.cefr
            or not option.prompt_guidance
        ):
            raise ValueError(f"invalid level catalog entry: {code}")
    if (
        HIGH_VALUE_TOGGLES | LOW_VALUE_TOGGLES != set(DISPLAY_TOGGLE_FIELDS)
        or HIGH_VALUE_TOGGLES & LOW_VALUE_TOGGLES
    ):
        raise ValueError("display-toggle high/low partition must cover DISPLAY_TOGGLE_FIELDS")
    if set(DISPLAY_TOGGLE_DEFAULTS) != set(DISPLAY_TOGGLE_FIELDS):
        raise ValueError("DISPLAY_TOGGLE_DEFAULTS must cover every DISPLAY_TOGGLE_FIELD")
    expected_namespaces = {"languages", "goals", "levels"}
    if set(CATALOG_NAMESPACES) != expected_namespaces:
        raise ValueError(
            "CATALOG_NAMESPACES must expose exactly the canonical identifier namespaces"
        )
    for name in expected_namespaces:
        entries = CATALOG_NAMESPACES[name]
        if not entries or not all(
            code == option.code for code, option in entries.items()
        ):
            raise ValueError(f"catalog namespace {name!r} must be code-keyed and non-empty")
