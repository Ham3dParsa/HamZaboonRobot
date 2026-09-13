"""Canonical language/goal/level registries (REF2-T6 leaf).

Verbatim home of the language/goal/level section split out of
``config/catalog.py``: the ``LanguageOption``/``GoalOption``/``LevelOption``
dataclasses, ``LANGUAGES``/``GOALS``/``LEVELS`` (+ ``DEFAULT_LEVEL``), the
``CATALOG_NAMESPACES`` identifier-namespace registry with
:func:`catalog_namespace`, and the label/guidance accessors.
``config/catalog.py`` keeps a re-export shim so every existing
``from config.catalog import ...`` caller works unchanged.

Leaf-import law: stdlib only (``dataclasses``). This module must never import
sibling catalog leaves — the settings-keys leaf and the validation leaf
consume it, never the reverse (settings defaults at old ``:213`` and the
``{card_type}`` patterns at old ``:219-220`` resolve downward only).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageOption:
    code: str
    name_fa: str
    example_name: str
    guidance: str = ""
    voice: str = ""


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
        voice="en-US-JennyNeural",
    ),
    "es": LanguageOption(
        "es",
        "اسپانیایی",
        "اسپانیایی",
        "برای اسپانیایی، جنسیت اسم‌ها، صرف فعل و کاربرد درست حروف تعریف را متناسب با سطح کاربر رعایت کن.",
        voice="es-ES-ElviraNeural",
    ),
    "ar": LanguageOption(
        "ar",
        "عربی",
        "عربی",
        "برای عربی، اعراب‌گذاری و ساختارهای صرفی را در حد نیاز و متناسب با سطح کاربر رعایت کن.",
        voice="ar-SA-ZariyahNeural",
    ),
    "fr": LanguageOption(
        "fr",
        "فرانسوی",
        "فرانسوی",
        "برای فرانسوی، جنسیت اسم‌ها، صرف فعل و حروف تعریف را متناسب با سطح کاربر رعایت کن.",
        voice="fr-FR-DeniseNeural",
    ),
    "de": LanguageOption(
        "de",
        "آلمانی",
        "آلمانی",
        "برای آلمانی، جنسیت اسم‌ها (der/die/das)، حالت‌های دستوری "
        "(Nominativ/Akkusativ/Dativ/Genitiv)، صرف فعل، حروف بزرگ و جایگاه فعل "
        "را دقیق و متناسب با سطح کاربر رعایت کن.",
        voice="de-DE-KatjaNeural",
    ),
    "tr": LanguageOption(
        "tr",
        "ترکی استانبولی",
        "ترکی استانبولی",
        "برای ترکی استانبولی، هماهنگی واکه‌ها، پسوندها و تلفظ شفاف واژه را متناسب با سطح کاربر رعایت کن.",
        voice="tr-TR-EmelNeural",
    ),
    "he": LanguageOption(
        "he",
        "عبری",
        "عبری",
        "برای عبری، ساخت ریشه‌ای و آواهای متناسب با سطح کاربر را رعایت کن.",
        voice="he-IL-HilaNeural",
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
