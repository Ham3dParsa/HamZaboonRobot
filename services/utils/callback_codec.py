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

# ---- Field-name aliases (closed set from admin_ai.WIZARD_FIELDS) ----
_FIELD_ALIAS: dict[str, str] = {
    "name": "n",
    "api_key": "k",
    "base_url": "u",
    "model": "m",
    "max_concurrency": "mc",
    "max_rpm": "mr",
    "max_tpm": "mt",
    "daily_batch_size": "bs",
    "max_daily_req": "md",
    "timeout_seconds": "to",
    "temperature": "t",
    "max_output_tokens": "mo",
    "priority": "p",
    "is_emergency": "ie",
    "in_fallback_chain": "fc",
    "input_cost_per_million": "ic",
    "output_cost_per_million": "oc",
    "group_label": "gl",
}

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