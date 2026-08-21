"""Canonical AI-preset field schema: types, defaults, and semantics (J-B2).

Single owner of AI-preset field metadata, kept in the ``services/ai`` domain.
Persistence (``preset_registry.set_preset``) and the AI-call/display consumers
(``ai.py``, ``handlers/admin_ai.py``) read field semantics from here instead of
hardcoding default literals, so the preset surface cannot diverge.

Field names and write defaults mirror the ``ai_presets`` table (the canonical
column set lives in ``services/db/schema._AI_PRESETS_COLUMNS``); a dedicated
test (``tests/test_preset_fields.py``) asserts that alignment so a schema change
without a registry change fails loudly instead of silently drifting.

This module is deliberately narrow and deep: a small interface
(``preset_field`` / ``write_default`` / ``resolve`` / ``validate``) hiding the
full schema table and resolution/validation logic. It performs no I/O — no DB,
no AI calls — so it cannot become a god module.
"""

from collections.abc import Mapping

from config import (
    AI_MAX_OUTPUT_TOKENS,
    AI_TEMPERATURE,
    AI_TIMEOUT_SECONDS,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
)

#: field name -> metadata.
#: ``write_default`` mirrors the ai_presets column DEFAULT (the value written to
#: the DB when none is supplied). ``config_default``, when present, is the
#: runtime read-side fallback for env-configurable fields; it overrides
#: ``write_default`` on the read side only so env overrides keep working.
#: ``secret`` and ``cost`` are semantic flags used by callers (encryption,
#: pricing) rather than by the DB.
PRESET_FIELDS: dict[str, dict] = {
    "name": {"type": "str", "write_default": ""},
    "base_url": {
        "type": "str",
        "write_default": "",
        "config_default": DEFAULT_AI_BASE_URL,
    },
    "model": {
        "type": "str",
        "write_default": "",
        "config_default": DEFAULT_AI_MODEL,
    },
    "api_key": {"type": "str", "write_default": "", "secret": True},
    "daily_batch_size": {"type": "int", "write_default": 6},
    "max_concurrency": {"type": "int", "write_default": 2},
    "max_rpm": {"type": "int", "write_default": 30},
    "max_tpm": {"type": "int", "write_default": 0},
    "max_daily_req": {"type": "int", "write_default": 0},
    "timeout_seconds": {
        "type": "float",
        "write_default": 30.0,
        "config_default": AI_TIMEOUT_SECONDS,
    },
    "temperature": {
        "type": "float",
        "write_default": 0.6,
        "config_default": AI_TEMPERATURE,
    },
    "max_output_tokens": {
        "type": "int",
        "write_default": 4096,
        "config_default": AI_MAX_OUTPUT_TOKENS,
    },
    "is_emergency": {"type": "int", "write_default": 0},
    "priority": {"type": "int", "write_default": 0},
    "enabled": {"type": "int", "write_default": 1},
    "input_cost_per_million": {"type": "float", "write_default": None, "cost": True},
    "output_cost_per_million": {"type": "float", "write_default": None, "cost": True},
    "in_fallback_chain": {"type": "int", "write_default": 1},
    "group_label": {"type": "str", "write_default": ""},
    "reasoning_effort": {"type": "str", "write_default": "none"},
}

_VALID_TYPES = {"str", "int", "float"}


def preset_field(name: str) -> dict:
    """Return a copy of the metadata for a canonical preset field.

    Raises ``KeyError`` for unknown field names so callers fail fast instead of
    silently reading an unregistered field.
    """
    if name not in PRESET_FIELDS:
        raise KeyError(f"unknown preset field: {name!r}")
    return dict(PRESET_FIELDS[name])


def write_default(name: str):
    """Return the canonical DB write default for a field (mirrors the column)."""
    return preset_field(name)["write_default"]


def _stored_or_default(preset: Mapping, name: str, default):
    """Return ``preset[name]`` if present and not None/``""``, else ``default``.

    ``None`` and ``""`` count as absent so a NULL/empty column falls back, while
    a stored falsy-but-valid value (``0``, ``0.0``) is preserved.
    """
    if name in preset and preset[name] not in (None, ""):
        return preset[name]
    return default


def resolve(preset: Mapping, name: str):
    """Return a field's value from the preset, or its canonical default.

    This is a **read-side** helper: the returned value is used for display or an
    AI call, never persisted back. For env-configurable fields (``config_default``
    present), an absent/empty preset value falls back to the config constant so
    environment overrides keep working. Other fields fall back to ``write_default``.

    ``config_default`` is therefore intentionally inert for real presets: the
    write path (``set_preset`` and the admin edit-save flows) persists concrete
    non-empty ``write_default`` values, so env is applied dynamically at call
    time rather than frozen at write time. Write paths must use ``write_value``
    (preserve stored value, fall back to the DB default) and must NOT call
    ``resolve``, which would snapshot the env constant.
    """
    meta = preset_field(name)
    cfg = meta.get("config_default")
    fallback = cfg if cfg is not None else meta["write_default"]
    return _stored_or_default(preset, name, fallback)


def write_value(preset: Mapping, name: str):
    """Return a field's value for persistence, or its canonical DB write default.

    Write-side sibling of :func:`resolve`: preserves a stored value (including
    falsy-but-valid ``0``/``0.0``) and treats ``None``/``""`` as absent, falling
    back to the plain ``write_default`` — never the env ``config_default``.
    """
    return _stored_or_default(preset, name, write_default(name))


def validate(preset: Mapping) -> None:
    """Raise ``ValueError`` if any present field in the preset has the wrong type.

    Unknown fields are ignored (forward-compat). ``None`` values are allowed
    (nullable columns). Callers that need strict membership use ``preset_field``.
    """
    for name, value in preset.items():
        meta = PRESET_FIELDS.get(name)
        if meta is None or value is None:
            continue
        expected = meta["type"]
        if expected == "str":
            ok = isinstance(value, str)
        elif expected == "int":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif expected == "float":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:  # defensive; structural check in validate_preset_fields
            ok = True
        if not ok:
            raise ValueError(
                f"preset field {name!r} must be {expected}, got {type(value).__name__}"
            )


def validate_preset_fields() -> None:
    """Structural check of the PRESET_FIELDS registry (raises on malformed entries).

    Raises ``ValueError`` on an invalid ``type`` or a missing ``write_default``.
    Does not raise for unknown runtime keys (they are not part of the schema).
    """
    for name, meta in PRESET_FIELDS.items():
        if meta.get("type") not in _VALID_TYPES:
            raise ValueError(f"preset field {name!r} has invalid type {meta.get('type')!r}")
        if "write_default" not in meta:
            raise ValueError(f"preset field {name!r} missing 'write_default'")