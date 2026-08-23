"""Callback-data encoding scheme for admin AI preset callbacks.

Keeps callback_data payloads under Telegram's 64-byte limit by replacing long
variable identifiers (preset names, Persian group labels) with short deterministic
hashes, and field names with short static aliases.

The static prefix (e.g. ``admin:ai_preset:edit_field:``) is preserved so the
wiring guard (``tests/test_wiring.py``) stays green — only the variable payload
segments change.
"""

import hashlib

from services.db.preset_registry import get_group_labels
from services.db import get_presets

# ---- Field-name aliases — single source: services/ai/preset_fields.PRESET_FIELDS ----
# Derives the short callback alias directly from the canonical preset registry so
# the two maps can never drift (R3). The preset seam owns the alias; codec is a
# thin translation layer delegating to services/field_registry.alias_map.
from services.ai.preset_fields import PRESET_FIELDS as _PRESET_FIELDS  # noqa: E402
from services.field_registry import alias_map as _alias_map  # noqa: E402

_FIELD_ALIAS: dict[str, str] = _alias_map(_PRESET_FIELDS)

_FIELD_ALIAS_REV: dict[str, str] = {v: k for k, v in _FIELD_ALIAS.items()}


def alias_field(field_name: str) -> str:
    return _FIELD_ALIAS.get(field_name, field_name)


def resolve_field_alias(alias: str) -> str:
    return _FIELD_ALIAS_REV.get(alias, alias)


# ---- Deterministic hash (sha256[:12], same style as admin_ai._key_hash) ----
def _cb_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


# ---- Preset name encoding ----
def preset_token(name: str) -> str:
    return _cb_hash(name)


def resolve_preset_token(token: str) -> str | None:
    for p in get_presets():
        if _cb_hash(p["name"]) == token:
            return p["name"]
    return None


# ---- Group label encoding ----
def label_token(label: str) -> str:
    return _cb_hash(label)


def resolve_label_token(token: str) -> str | None:
    for g in get_group_labels():
        if _cb_hash(g["label"]) == token:
            return g["label"]
    return None