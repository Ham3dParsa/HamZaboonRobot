"""Canonical learner-facing language, goal, and level metadata."""

from dataclasses import dataclass

from config import (
    DEFAULT_AI_MODEL,
    USD_TO_TOMAN_RATE,
    LLM_INPUT_COST_USD_PER_MILLION,
    LLM_OUTPUT_COST_USD_PER_MILLION,
)


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
)

HIGH_VALUE_TOGGLES = frozenset(
    {"explanation", "synonyms", "antonyms", "examples"}
)

LOW_VALUE_TOGGLES = frozenset(
    {"grammar_tip", "example_translations"}
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



# Canonical settings-key registry (SEAMS.md "settings keys" shared resource).
# Mirrors CATALOG_NAMESPACES: every stable db.get_setting/set_setting key has a
# single canonical entry here so the settings surface is enumerated and validated.
# Dynamic per-card-type keys use a "{card_type}" placeholder (resolved at call
# time by settings_key()). Ephemeral/test/delivery sentinels are intentionally
# excluded so they never trip validation.

# Card types whose per-type admin-global modes/gates are registered as dynamic
# settings keys. Mirrors services/db/users.py CARD_TYPES; kept local to this
# module to avoid a circular import (users.py imports from config.catalog).
SETTINGS_CARD_TYPES = ("first_exposure", "review")

SETTINGS_KEYS = {
    "log_level":                        {"key": "log_level", "type": "str", "default": "", "scope": "global"},
    "user_activity_log":                {"key": "user_activity_log", "type": "bool", "default": False, "scope": "global"},
    "usd_to_toman_rate":                {"key": "usd_to_toman_rate", "type": "float", "default": USD_TO_TOMAN_RATE, "scope": "global"},
    "ai_primary_preset":               {"key": "ai_primary_preset", "type": "str", "default": "", "scope": "global"},
    "ai_fallback_preset":              {"key": "ai_fallback_preset", "type": "str", "default": "", "scope": "global"},
    "ai_consecutive_failures":         {"key": "ai_consecutive_failures", "type": "int", "default": 0, "scope": "global"},
    "ai_fallback_active":              {"key": "ai_fallback_active", "type": "bool", "default": False, "scope": "global"},
    "ai_fallback_since":               {"key": "ai_fallback_since", "type": "str", "default": "", "scope": "global"},
    "llm_input_cost_usd_per_million":  {"key": "llm_input_cost_usd_per_million", "type": "float", "default": LLM_INPUT_COST_USD_PER_MILLION, "scope": "global"},
    "llm_output_cost_usd_per_million": {"key": "llm_output_cost_usd_per_million", "type": "float", "default": LLM_OUTPUT_COST_USD_PER_MILLION, "scope": "global"},
    "ai_model":                        {"key": "ai_model", "type": "str", "default": DEFAULT_AI_MODEL, "scope": "global"},
    "display_toggle_defaults":         {"key": "display_toggle_defaults", "type": "json", "default": DISPLAY_TOGGLE_DEFAULTS, "scope": "global"},
    # Dynamic per-card-type admin-global modes + gates (key = f"{card_type}_mode" / f"{card_type}_mode_gate").
    # Defaults mirror services/db/users.py DEFAULT_CARD_MODE / DEFAULT_CARD_MODE_GATE.
    "{card_type}_mode":                {"key": "{card_type}_mode", "type": "str", "default": "staged", "scope": "global", "pattern": True},
    "{card_type}_mode_gate":           {"key": "{card_type}_mode_gate", "type": "str", "default": "premium", "scope": "global", "pattern": True},
}

def settings_key(name: str) -> dict:
    """Return the metadata dict for a canonical settings key.

    Resolves both stable keys and the dynamic `{card_type}_mode` /
    `{card_type}_mode_gate` patterns (e.g. `"first_exposure_mode"`). Raises
    `KeyError` for unknown keys so callers fail fast rather than silently
    reading an empty or wrong key.
    """
    if name in SETTINGS_KEYS:
        # Return a copy (never the registry entry) so callers cannot mutate the
        # canonical SETTINGS_KEYS entry, and copy nested mutable defaults so the
        # shared DISPLAY_TOGGLE_DEFAULTS dict can never be corrupted. Pattern keys
        # below already return a copy via dict(meta), keeping the contract symmetric.
        meta = dict(SETTINGS_KEYS[name])
        if isinstance(meta.get("default"), dict):
            meta["default"] = dict(meta["default"])
        return meta
    for tmpl, meta in SETTINGS_KEYS.items():
        if not meta.get("pattern"):
            continue
        prefix, suffix = tmpl.split("{card_type}", 1)
        if name.startswith(prefix) and name.endswith(suffix) and len(name) > len(prefix) + len(suffix):
            card_type = name[len(prefix):len(name) - len(suffix)] if suffix else name[len(prefix):]
            if card_type not in SETTINGS_CARD_TYPES:
                continue
            resolved = dict(meta)
            resolved["key"] = name
            resolved["card_type"] = card_type
            return resolved
    raise KeyError(f"unknown settings key: {name!r}")


def validate_settings_keys() -> None:
    """Validate the SETTINGS_KEYS registry structure (soft — no IO, no hard-fail).

    Raises on malformed entries (missing ``key`` or invalid ``type``); does NOT
    raise for unknown runtime keys (ephemeral/test keys are intentionally
    outside the registry). Callers that need strict lookup use settings_key(),
    which raises KeyError on unknown keys.
    """
    valid_types = {"str", "bool", "int", "float", "json"}
    for key, meta in SETTINGS_KEYS.items():
        if "key" not in meta or not meta["key"]:
            raise ValueError(f"settings key entry {key!r} missing 'key'")
        if meta["type"] not in valid_types:
            raise ValueError(f"settings key {key!r} has invalid type {meta['type']!r}")
        if meta.get("pattern"):
            tmpl = meta["key"]
            if "{card_type}" not in tmpl:
                raise ValueError(f"pattern settings key {key!r} must contain '{{card_type}}'")
            _p, _s = tmpl.split("{card_type}", 1)
            if not _s:
                raise ValueError(f"pattern settings key {key!r} must have a non-empty suffix")


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
        if code != option.code or not option.name_fa or not option.example_name or not option.voice:
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
    # Fold the settings-key registry into the same validation chain.
    validate_settings_keys()
