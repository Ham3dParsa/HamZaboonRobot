"""Display-toggle consolidation (R3).

Single owner of display-toggle read/write and effective-resolution precedence.
This replaces the scattered helpers that previously lived in
``services/db/users.py`` (per-user overrides / forced overrides) and
``services/db/settings.py`` (admin-global defaults) with one deep module behind a
small interface: ``DisplayToggleService`` (plus module-level conveniences).

Precedence for a user's effective toggles (forced > user > global > catalog) is
resolved in exactly one place: ``DisplayToggleService.get_effective``.

Seam note (coordination with J0.2): this module consumes the existing
``get_setting`` / ``set_setting`` primitives and the catalog ``DISPLAY_TOGGLE_*``
constants. The settings key is imported from ``settings.py``
(``DISPLAY_TOGGLE_DEFAULTS_KEY``), which J0.2 wired to the canonical
``SETTINGS_KEYS`` registry — so there is exactly one definition of the key
string and J-A3 introduces **no** new settings-key constant.
"""

from __future__ import annotations

import json

from config.catalog import DISPLAY_TOGGLE_DEFAULTS, DISPLAY_TOGGLE_FIELDS
from services.db.schema import transaction
from services.db.settings import (
    DISPLAY_TOGGLE_DEFAULTS_KEY,
    get_setting,
    set_setting,
)


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _decode_toggles(raw: str | None) -> dict[str, bool]:
    """Decode a display-toggles JSON column, keeping only known fields."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        key: _as_bool(value)
        for key, value in data.items()
        if key in DISPLAY_TOGGLE_FIELDS
    }


def _get_user_row(user_id: int):
    """Fetch a users row via the public accessor (avoids a second SQL path).

    Lazy import of ``get_user`` dodges the ``users <-> display_toggles`` import
    cycle without duplicating the row read.
    """
    from services.db.users import get_user
    return get_user(user_id)


class DisplayToggleService:
    """Single owner of display-toggle state and precedence resolution (R3)."""

    def get_global_defaults(self) -> dict[str, bool]:
        """Admin-global display-toggle defaults (R10), always complete.

        Stored values are merged over the built-in catalog defaults so the result
        always carries every ``DISPLAY_TOGGLE_FIELD`` and unknown/stale keys are
        ignored.
        """
        effective = dict(DISPLAY_TOGGLE_DEFAULTS)
        raw = get_setting(DISPLAY_TOGGLE_DEFAULTS_KEY, "")
        if raw:
            try:
                stored = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                stored = None
            if isinstance(stored, dict):
                for key, value in stored.items():
                    if key in DISPLAY_TOGGLE_FIELDS:
                        effective[key] = bool(value)
        return effective

    def set_global_defaults(self, values: dict[str, bool]):
        """Merge per-field admin-global display-toggle defaults (R10).

        Only known ``DISPLAY_TOGGLE_FIELDS`` are accepted; anything else raises so
        a mistyped admin edit can never silently no-op.
        """
        unknown = set(values) - set(DISPLAY_TOGGLE_FIELDS)
        if unknown:
            raise ValueError(f"Unknown display-toggle field(s): {', '.join(sorted(unknown))}")
        merged = self.get_global_defaults()
        for key, value in values.items():
            merged[key] = bool(value)
        set_setting(DISPLAY_TOGGLE_DEFAULTS_KEY, json.dumps(merged))

    def get_effective(self, user_id: int, row=None) -> dict[str, bool]:
        """Resolve a user's effective display toggles (R10).

        Precedence: admin-forced per-user > per-user override > admin-global
        defaults > built-in catalog defaults. ``row`` is an optional pre-fetched
        users row (callers that already hold one pass it in to avoid an extra
        SELECT); it is re-fetched when omitted. A missing user still resolves to
        the defaults so the session engine can always render a prompt (R11).
        """
        effective = dict(self.get_global_defaults())
        if row is None:
            row = _get_user_row(user_id)
        if row:
            effective.update(_decode_toggles(row["display_toggles"]))
            effective.update(_decode_toggles(row["display_toggles_forced"]))
        return {
            field: effective.get(field, DISPLAY_TOGGLE_DEFAULTS[field])
            for field in DISPLAY_TOGGLE_FIELDS
        }

    def set_user_toggle(self, user_id: int, field: str, enabled: bool):
        """Set a user's own display-toggle override (wins over admin defaults)."""
        if field not in DISPLAY_TOGGLE_FIELDS:
            raise ValueError(f"Unknown display-toggle field: {field}")
        with transaction() as conn:
            row = conn.execute(
                "SELECT display_toggles FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
            current = _decode_toggles(row["display_toggles"]) if row else {}
            current[field] = _as_bool(enabled)
            conn.execute(
                "UPDATE users SET display_toggles=? WHERE user_id=?",
                (json.dumps(current), user_id),
            )

    def set_forced(self, user_id: int, field: str, enabled: bool):
        """Set an admin-forced per-user display toggle (wins over user override)."""
        if field not in DISPLAY_TOGGLE_FIELDS:
            raise ValueError(f"Unknown display-toggle field: {field}")
        with transaction() as conn:
            row = conn.execute(
                "SELECT display_toggles_forced FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
            current = _decode_toggles(row["display_toggles_forced"]) if row else {}
            current[field] = _as_bool(enabled)
            conn.execute(
                "UPDATE users SET display_toggles_forced=? WHERE user_id=?",
                (json.dumps(current), user_id),
            )


# Module-level convenience wrappers around the single service instance.
_SERVICE = DisplayToggleService()


def get_global_defaults() -> dict[str, bool]:
    return _SERVICE.get_global_defaults()


def set_global_defaults(values: dict[str, bool]):
    return _SERVICE.set_global_defaults(values)


def get_effective(user_id: int, row=None) -> dict[str, bool]:
    return _SERVICE.get_effective(user_id, row)


def set_user_toggle(user_id: int, field: str, enabled: bool):
    return _SERVICE.set_user_toggle(user_id, field, enabled)


def set_forced(user_id: int, field: str, enabled: bool):
    return _SERVICE.set_forced(user_id, field, enabled)