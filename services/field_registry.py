"""Generic field-registry helper — deep module for two registries → one.

Provides a tiny reusable base for `services/ai/preset_fields.py` and
`services/plan_fields.py` so validation and alias handling live in one place.
Interface is deliberately small: a registry dict plus `validate` and `alias_map`.
Callers keep their own small interface (preset_field/plan_field) but share the
implementation behind it (depth = leverage).
"""

from collections.abc import Mapping


_VALID_TYPES = {"str", "int", "float"}


def validate_registry(fields: dict[str, dict], *, require_write_default: bool = True) -> None:
    for name, meta in fields.items():
        if meta.get("type") not in _VALID_TYPES:
            raise ValueError(f"field {name!r} has invalid type {meta.get('type')!r}")
        if require_write_default and "write_default" not in meta:
            raise ValueError(f"field {name!r} missing 'write_default'")


def validate_instance(fields: dict[str, dict], instance: Mapping) -> None:
    for name, value in instance.items():
        meta = fields.get(name)
        if meta is None or value is None:
            continue
        expected = meta["type"]
        if expected == "str":
            ok = isinstance(value, str)
        elif expected == "int":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif expected == "float":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = True
        if not ok:
            raise ValueError(f"field {name!r} must be {expected}, got {type(value).__name__}")


def alias_map(fields: dict[str, dict]) -> dict[str, str]:
    return {name: meta["alias"] for name, meta in fields.items() if "alias" in meta}
