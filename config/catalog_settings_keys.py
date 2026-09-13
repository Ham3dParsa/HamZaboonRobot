"""Canonical settings-key registry (REF2-T6 leaf).

Verbatim home of the settings-key section split out of
``config/catalog.py`` (SEAMS.md "settings keys" shared resource): the
``DEFAULT_MAINTENANCE_MESSAGE`` canonical default, ``SETTINGS_KEYS``,
:func:`settings_key`, and :func:`validate_settings_keys`.
``config/catalog.py`` keeps a re-export shim so every existing
``from config.catalog import ...`` caller works unchanged.

Leaf-import law: ``config`` only (env cost bindings from ``config``,
``DISPLAY_TOGGLE_DEFAULTS`` from the toggles leaf, ``SETTINGS_CARD_TYPES``
from the card-types leaf). Split order is load-bearing: this leaf is defined
after toggles/card-types so the ``display_toggle_defaults`` default and the
``{card_type}`` pattern gates never dangle.
"""

from config import (
    USD_TO_TOMAN_RATE,
    LLM_INPUT_COST_USD_PER_MILLION,
    LLM_OUTPUT_COST_USD_PER_MILLION,
)
from config.catalog_card_types import SETTINGS_CARD_TYPES
from config.catalog_toggles import DISPLAY_TOGGLE_DEFAULTS

# Canonical default learner-facing maintenance message (single source of truth
# for the maintenance_message settings key; consumers read it via settings_key).
DEFAULT_MAINTENANCE_MESSAGE = "ربات در حال تعمیر است؛ لطفاً بعداً مراجعه کنید."


# Canonical settings-key registry (SEAMS.md "settings keys" shared resource).
# Mirrors CATALOG_NAMESPACES: every stable db.get_setting/set_setting key has a
# single canonical entry here so the settings surface is enumerated and validated.
# Dynamic per-card-type keys use a "{card_type}" placeholder (resolved at call
# time by settings_key()). Ephemeral/test/delivery sentinels are intentionally
# excluded so they never trip validation.
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
    "ai_model":                        {"key": "ai_model", "type": "str", "default": "", "scope": "global"},
    "display_toggle_defaults":         {"key": "display_toggle_defaults", "type": "json", "default": DISPLAY_TOGGLE_DEFAULTS, "scope": "global"},
    "maintenance_mode":                {"key": "maintenance_mode", "type": "bool", "default": False, "scope": "global"},
    "maintenance_message":             {"key": "maintenance_message", "type": "str", "default": DEFAULT_MAINTENANCE_MESSAGE, "scope": "global"},
    # Dynamic per-card-type admin-global modes + gates (key = f"{card_type}_mode" / f"{card_type}_mode_gate").
    # Defaults mirror services/db/users.py DEFAULT_CARD_MODE / DEFAULT_CARD_MODE_GATE.
    "tts_cache_chat_id":               {"key": "tts_cache_chat_id", "type": "str", "default": "", "scope": "global"},
    "{card_type}_mode":                {"key": "{card_type}_mode", "type": "str", "default": "staged", "scope": "global", "pattern": True},
    "{card_type}_mode_gate":           {"key": "{card_type}_mode_gate", "type": "str", "default": "premium", "scope": "global", "pattern": True},
    "archive_chat_id":                {"key": "archive_chat_id", "type": "str", "default": "", "scope": "global"},
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
