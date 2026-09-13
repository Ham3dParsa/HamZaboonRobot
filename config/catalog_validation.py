"""Catalog-wide validation (REF2-T6 leaf, terminus).

Verbatim home of :func:`validate_catalog` split out of
``config/catalog.py`` — the last move of the ticket (validators last), folding
the language/goal/level, toggle, namespace, card-type, and settings-key
registries into a single validation chain. ``config/catalog.py`` keeps a
re-export shim so every existing ``from config.catalog import ...`` caller
works unchanged.

Leaf-import law: ``config`` only (sibling catalog leaves). This module sits
downstream of every other catalog leaf and must never be imported by one.
"""

from config.catalog_card_types import CARD_MODE_GATES, CARD_MODES, CARD_TYPES
from config.catalog_languages import (
    CATALOG_NAMESPACES,
    GOALS,
    LANGUAGES,
    LEVELS,
)
from config.catalog_settings_keys import validate_settings_keys
from config.catalog_toggles import (
    DISPLAY_TOGGLE_DEFAULTS,
    DISPLAY_TOGGLE_FIELDS,
    HIGH_VALUE_TOGGLES,
    LOW_VALUE_TOGGLES,
)


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
    # Card-type registry must be non-empty and modes/gates valid.
    if not CARD_TYPES or not all(isinstance(c, str) and c for c in CARD_TYPES):
        raise ValueError("CARD_TYPES must be non-empty strings")
    if set(CARD_MODES) != {"staged", "immediate"}:
        raise ValueError("CARD_MODES must be exactly staged/immediate")
    if set(CARD_MODE_GATES) != {"all", "premium"}:
        raise ValueError("CARD_MODE_GATES must be exactly all/premium")
    # Fold the settings-key registry into the same validation chain.
    validate_settings_keys()
