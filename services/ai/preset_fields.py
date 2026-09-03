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
)

#: field name -> metadata.
#: ``write_default`` mirrors the ai_presets column DEFAULT (the value written to
#: the DB when none is supplied). ``config_default``, when present, is the
#: runtime read-side fallback for env-configurable fields; it overrides
#: ``write_default`` on the read side only so env overrides keep working.
#: ``secret`` and ``cost`` are semantic flags used by callers (encryption,
#: pricing) rather than by the DB.
PRESET_FIELDS: dict[str, dict] = {
    "name": {"type": "str", "write_default": "", "alias": "n"},
    "base_url": {
        "type": "str",
        "write_default": "",
        "alias": "u",
    },
    "model": {
        "type": "str",
        "write_default": "",
        "alias": "m",
    },
    "api_key": {"type": "str", "write_default": "", "secret": True, "alias": "k"},
    "daily_batch_size": {"type": "int", "write_default": 6, "alias": "bs"},
    "max_concurrency": {"type": "int", "write_default": 2, "alias": "mc"},
    "max_rpm": {"type": "int", "write_default": 30, "alias": "mr"},
    "max_tpm": {"type": "int", "write_default": 0, "alias": "mt"},
    "max_daily_req": {"type": "int", "write_default": 0, "alias": "md"},
    "timeout_seconds": {
        "type": "float",
        "write_default": 30.0,
        "config_default": AI_TIMEOUT_SECONDS,
        "alias": "to",
    },
    "temperature": {
        "type": "float",
        "write_default": 0.6,
        "config_default": AI_TEMPERATURE,
        "alias": "t",
    },
    "max_output_tokens": {
        "type": "int",
        "write_default": 4096,
        "config_default": AI_MAX_OUTPUT_TOKENS,
        "alias": "mo",
    },
    "is_emergency": {"type": "int", "write_default": 0, "alias": "ie"},
    "priority": {"type": "int", "write_default": 0, "alias": "p"},
    "enabled": {"type": "int", "write_default": 1, "alias": "en"},
    "input_cost_per_million": {"type": "float", "write_default": None, "cost": True, "alias": "ic"},
    "output_cost_per_million": {"type": "float", "write_default": None, "cost": True, "alias": "oc"},
    "in_fallback_chain": {"type": "int", "write_default": 1, "alias": "fc"},
    "group_label": {"type": "str", "write_default": "", "alias": "gl"},
    "reasoning_effort": {"type": "str", "write_default": "none", "alias": "re"},
}

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
    """Raise ``ValueError`` if any present field in the preset has the wrong type."""
    from services.field_registry import validate_instance

    validate_instance(PRESET_FIELDS, preset)


def validate_preset_fields() -> None:
    """Structural check of the PRESET_FIELDS registry (raises on malformed entries)."""
    from services.field_registry import validate_registry

    validate_registry(PRESET_FIELDS)