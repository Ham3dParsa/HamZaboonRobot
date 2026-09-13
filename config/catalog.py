"""Catalog facade (REF2-T6).

Thin re-export shim over the split leaves — ``catalog_languages.py``
(languages/goals/levels + namespaces + label helpers), ``catalog_toggles.py``,
``catalog_card_types.py``, ``catalog_settings_keys.py`` (SETTINGS_KEYS +
resolver), and ``catalog_validation.py`` (validators, moved last). Every
existing ``from config.catalog import ...`` caller works unchanged; the
canonical definitions live in the leaves (old defs removed same PR).

Deliberately NOT re-exported: none — the facade mirrors the full pre-split
surface so zero callers need retargeting in this PR.
"""

from config.catalog_card_types import (
    CARD_MODE_GATES,
    CARD_MODES,
    CARD_TYPES,
    DEFAULT_CARD_MODE,
    DEFAULT_CARD_MODE_GATE,
    SETTINGS_CARD_TYPES,
)
from config.catalog_languages import (
    CATALOG_NAMESPACES,
    DEFAULT_LEVEL,
    GOALS,
    LANGUAGES,
    LEVELS,
    GoalOption,
    LanguageOption,
    LevelOption,
    catalog_namespace,
    example_language_label,
    goal_hint,
    goal_label,
    language_guidance,
    language_label,
    level_cefr,
    level_label,
    level_prompt_guidance,
)
from config.catalog_settings_keys import (
    DEFAULT_MAINTENANCE_MESSAGE,
    SETTINGS_KEYS,
    settings_key,
    validate_settings_keys,
)
from config.catalog_toggles import (
    DISPLAY_TOGGLE_DEFAULTS,
    DISPLAY_TOGGLE_FIELDS,
    HIGH_VALUE_TOGGLES,
    LOW_VALUE_TOGGLES,
)
from config.catalog_validation import validate_catalog

__all__ = [
    "CARD_MODE_GATES",
    "CARD_MODES",
    "CARD_TYPES",
    "CATALOG_NAMESPACES",
    "DEFAULT_CARD_MODE",
    "DEFAULT_CARD_MODE_GATE",
    "DEFAULT_LEVEL",
    "DEFAULT_MAINTENANCE_MESSAGE",
    "DISPLAY_TOGGLE_DEFAULTS",
    "DISPLAY_TOGGLE_FIELDS",
    "GOALS",
    "HIGH_VALUE_TOGGLES",
    "LANGUAGES",
    "LEVELS",
    "LOW_VALUE_TOGGLES",
    "SETTINGS_CARD_TYPES",
    "SETTINGS_KEYS",
    "GoalOption",
    "LanguageOption",
    "LevelOption",
    "catalog_namespace",
    "example_language_label",
    "goal_hint",
    "goal_label",
    "language_guidance",
    "language_label",
    "level_cefr",
    "level_label",
    "level_prompt_guidance",
    "settings_key",
    "validate_catalog",
    "validate_settings_keys",
]
