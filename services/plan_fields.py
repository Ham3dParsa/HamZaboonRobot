"""Canonical plan-field schema for the admin plan-manager wizard (G3 F8/R8).

Single owner of the 5 admin-editable plan fields' metadata — name, type, DB
write default, Persian label, hint, and group. ``handlers/admin_plans.py``
derives its wizard (step order, labels, hints, group headers, validation, and
the ``upsert_plan`` save mapping) from here instead of hardcoding literals, so
the plan-edit surface cannot diverge from the ``plans`` table or from the
wizard's behavior. Mirrors ``services/ai/preset_fields.py`` for the AI-preset
surface.

Identity/status fields that are not wizard-editable (``name``, ``sort_order``,
``is_active``, card modes) stay owned by ``services/db/plans.py`` /
``config/plan_identity.py``; only the editable fields live here.

This module is deliberately narrow and deep: a small interface
(``plan_field`` / ``field_order`` / ``field_label`` / ``field_hint`` /
``group_header`` / ``write_default`` / ``validate_value``) hiding the full
schema table and validation logic. It performs no I/O — no DB, no handlers.
"""

from collections.abc import Mapping

#: field name -> metadata.
#: ``write_default`` mirrors the ``plans`` column DEFAULT (display_name has no
#: DEFAULT clause so it is ""). ``label``/``hint`` are the Persian wizard copy;
#: ``group`` selects the display/quotas group header in PLAN_GROUPS.
PLAN_FIELDS: dict[str, dict] = {
    "display_name": {
        "type": "str",
        "write_default": "",
        "label": "نام نمایشی",
        "hint": "",
        "group": "display",
    },
    "price": {
        "type": "int",
        "write_default": 0,
        "label": "قیمت (تومان)",
        "hint": "",
        "group": "display",
    },
    "query_quota": {
        "type": "int",
        "write_default": 0,
        "label": "سهمیه سؤال روزانه (جستجوی دستی واژه)",
        "hint": "سقف جستجوی دستی واژه در روز (سؤال‌کردن از ربات برای یک واژهٔ جدید)؛ جدا از کارت‌های روزانه و محتوای هوشمند است.",
        "group": "quotas",
    },
    "max_sessions": {
        "type": "int",
        "write_default": 1,
        "label": "جلسات روزانه",
        "hint": "تعداد جلسه‌های مطالعه در هر روز.",
        "group": "quotas",
    },
    "cards_per_session": {
        "type": "int",
        "write_default": 1,
        "label": "کارت در هر جلسه",
        "hint": "تعداد کارت‌های هر جلسهٔ مطالعه.",
        "group": "quotas",
    },
}

#: group name -> (header, Persian one-line hint) shown at the wizard step.
PLAN_GROUPS: dict[str, dict] = {
    "display": {
        "header": "🎨 — گروه نمایش (Display):",
        "hint": "نام نمایشی و قیمت، فقط برای نمایش هستند و محدودیت‌ی به کاربر تحمیل نمی‌کنند.",
    },
    "quotas": {
        "header": "💰 — گروه سهمیه (Quotas):",
        "hint": "این سهمیه‌ها رفتار روزانهٔ مطالعه و سؤال‌کردن کاربر را محدود می‌کنند.",
    },
}

_VALID_TYPES = {"str", "int"}


def plan_field(name: str) -> dict:
    """Return a copy of the metadata for a canonical editable plan field.

    Raises ``KeyError`` for unknown field names so callers fail fast instead of
    silently reading an unregistered field.
    """
    if name not in PLAN_FIELDS:
        raise KeyError(f"unknown plan field: {name!r}")
    return dict(PLAN_FIELDS[name])


def field_order() -> list[str]:
    """Return the editable field names in wizard order."""
    return list(PLAN_FIELDS)


def field_label(name: str) -> str:
    """Return the Persian wizard label for a field."""
    return plan_field(name)["label"]


def field_hint(name: str) -> str:
    """Return the Persian extra hint for a field (may be empty)."""
    return plan_field(name).get("hint", "")


def group_header(name: str) -> tuple[str, str]:
    """Return ``(header, hint)`` for the group the field belongs to."""
    group = plan_field(name)["group"]
    meta = PLAN_GROUPS[group]
    return meta["header"], meta["hint"]


def write_default(name: str):
    """Return the canonical DB write default for a field (mirrors the column)."""
    return plan_field(name)["write_default"]


def validate_value(name: str, raw) -> object | None:
    """Parse and validate a wizard input for a field. Returns the value, or
    None on invalid/empty input.

    ``str`` fields: stripped non-empty text, else None. ``int`` fields: a
    non-negative integer, else None. Mirrors the pre-registry wizard validation
    exactly.
    """
    meta = plan_field(name)
    if meta["type"] == "str":
        v = raw.strip()
        return v if v else None
    try:
        v = int(raw)
    except (ValueError, TypeError):
        return None
    return v if v >= 0 else None


def validate_plan_fields() -> None:
    """Structural check of the PLAN_FIELDS registry (raises on malformed entries)."""
    for name, meta in PLAN_FIELDS.items():
        if meta.get("type") not in _VALID_TYPES:
            raise ValueError(f"plan field {name!r} has invalid type {meta.get('type')!r}")
        if "write_default" not in meta:
            raise ValueError(f"plan field {name!r} missing 'write_default'")
        if "label" not in meta or not meta.get("label"):
            raise ValueError(f"plan field {name!r} missing a Persian label")
        if meta.get("group") not in PLAN_GROUPS:
            raise ValueError(f"plan field {name!r} has unknown group {meta.get('group')!r}")


def build_upsert_kwargs(plan: Mapping, values: Mapping) -> dict:
    """Build the ``upsert_plan`` keyword dict from a plan row + wizard values.

    For each editable field, takes the wizard value if present, else the
    current DB value, coercing ``int`` fields to int and falling back to the
    registry write default when the stored value is absent. Identity/status
    fields (sort_order, is_active) are passed through unchanged.
    """
    kwargs: dict = {"name": plan.get("name")}
    for name in field_order():
        meta = plan_field(name)
        val = values.get(name, plan.get(name))
        if val is None:
            val = write_default(name)
        if meta["type"] == "int":
            val = int(val)
        kwargs[name] = val
    kwargs["sort_order"] = plan.get("sort_order", 0)
    kwargs["is_active"] = plan.get("is_active", 1)
    return kwargs


__all__ = [
    "PLAN_FIELDS",
    "PLAN_GROUPS",
    "build_upsert_kwargs",
    "field_hint",
    "field_label",
    "field_order",
    "group_header",
    "plan_field",
    "validate_plan_fields",
    "validate_value",
    "write_default",
]