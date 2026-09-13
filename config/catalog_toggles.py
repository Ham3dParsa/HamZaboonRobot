"""Canonical display-toggle registry (REF2-T6 leaf).

Verbatim home of the display-toggle section split out of
``config/catalog.py`` (#338 R7/R9/R10/R11). ``config/catalog.py`` keeps a
re-export shim so every existing ``from config.catalog import ...`` caller
works unchanged.

Leaf-import law: stdlib only (no imports at all). The settings-keys leaf
consumes ``DISPLAY_TOGGLE_DEFAULTS`` for the ``display_toggle_defaults``
entry — never the reverse.
"""

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
