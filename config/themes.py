"""Canonical theme catalog (issue #467).

Pure, stdlib-only leaf module with **no application imports**. It is the single
source of truth for learner-facing theme labels (streak/shield/heat/status and
profile/event lines). Stage semantics are domain-owned and live elsewhere; this
module holds NO stage labels.

Unknown theme ids fail closed to ``DEFAULT_THEME_ID`` on reads (see
``get_theme``); writes validate fail-fast elsewhere (``ValueError``).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TypedDict


class _ThemeSpec(TypedDict):
    """Precise shape of a single theme entry."""

    label: str
    streak: str
    shield: str
    best_streak: str
    xp: str
    heat: dict[int, str]
    shield_event: str
    status_title: str
    profile_today: str
    profile_total: str
    event_first: str
    event_milestone_1: str
    event_milestone_2: str
    has_animation: bool


DEFAULT_THEME_ID = "fire_temple"

_THEMES: dict[str, _ThemeSpec] = {
    "fire_temple": {
        "label": "آتشکده هم‌زبان",
        "streak": "پیوستگی",
        "shield": "فرشته نجات",
        "best_streak": "بلندترین پیوستگی",
        "xp": "امتیاز",
        "heat": {1: "یک‌آتیشه 🔥", 2: "دوآتیشه 🔥🔥", 3: "سه‌آتیشه 🔥🔥🔥"},
        "shield_event": "فرشته نجات حواست را داشت",
        "status_title": "🏛️ آتشکده شما",
        "profile_today": "وضعیت امروز",
        "profile_total": "آمار کلی",
        "event_first": "یک‌آتیشه شدی",
        "event_milestone_1": "دوآتیشه شدی، ۴۰٪ نشست‌های امروز",
        "event_milestone_2": "سه‌آتیشه، روز کامل",
        "has_animation": True,
    },
    "star": {
        "label": "ستاره",
        "streak": "پیوستگی",
        "shield": "سپر 🛡️",
        "best_streak": "بلندترین پیوستگی",
        "xp": "امتیاز",
        "heat": {1: "تک‌ستاره ★", 2: "دوستاره ★★", 3: "سه‌ستاره ★★★"},
        "shield_event": "سپر حواست را داشت",
        "status_title": "⭐ نمای شما",
        "profile_today": "وضعیت امروز",
        "profile_total": "آمار کلی",
        "event_first": "تک‌ستاره شدی",
        "event_milestone_1": "دوستاره شدی، ۴۰٪ نشست‌های امروز",
        "event_milestone_2": "سه‌ستاره، روز کامل",
        "has_animation": False,
    },
}

# Frozen view: outer registry + each theme + each heat map are immutable, so no
# consumer can drift the catalog at runtime. No other module may hold a
# parallel theme dictionary.
THEMES = MappingProxyType(
    {
        theme_id: MappingProxyType(
            {**spec, "heat": MappingProxyType(dict(spec["heat"]))}
        )
        for theme_id, spec in _THEMES.items()
    }
)

# Learner strings must never contain these (Persian law): middle dot, em dash,
# or pipe. Lists use ، and clauses use ؛.
_FORBIDDEN_LEARNER_CHARS = frozenset({"·", "—", "|"})


def get_theme(theme_id: str | None) -> MappingProxyType:
    """Return the theme spec for ``theme_id``.

    Unknown (or non-string) ids fail closed to ``DEFAULT_THEME_ID``: callers
    always get a usable theme and never crash on a stale stored value.
    """
    if isinstance(theme_id, str) and theme_id in THEMES:
        return THEMES[theme_id]
    return THEMES[DEFAULT_THEME_ID]


def validate_themes() -> None:
    """Validate the frozen catalog; raise ``ValueError`` on any violation."""
    if set(THEMES) != {"fire_temple", "star"}:
        raise ValueError("THEMES must hold exactly fire_temple and star")
    if DEFAULT_THEME_ID not in THEMES:
        raise ValueError("DEFAULT_THEME_ID must exist in THEMES")
    reference_keys = set(THEMES[DEFAULT_THEME_ID].keys())
    for theme_id, spec in THEMES.items():
        if set(spec.keys()) != reference_keys:
            raise ValueError(f"theme {theme_id} key set differs from default")
        if "stage" in " ".join(str(k).lower() for k in spec.keys()):
            raise ValueError(f"theme {theme_id} must not hold stage labels")
        for key, value in spec.items():
            if key in ("heat", "has_animation"):
                continue
            if not isinstance(value, str) or not value:
                raise ValueError(f"theme {theme_id}.{key} must be a non-empty string")
            if _FORBIDDEN_LEARNER_CHARS & set(value):
                raise ValueError(f"theme {theme_id}.{key} breaks Persian law")
        heat = spec["heat"]
        if set(heat.keys()) != {1, 2, 3}:
            raise ValueError(f"theme {theme_id}.heat must map exactly 1/2/3")
        for level, label in heat.items():
            if (
                not isinstance(label, str)
                or not label
                or _FORBIDDEN_LEARNER_CHARS & set(label)
            ):
                raise ValueError(f"theme {theme_id}.heat[{level}] breaks Persian law")
        if not isinstance(spec["has_animation"], bool):
            raise ValueError(f"theme {theme_id}.has_animation must be bool")
    if THEMES["fire_temple"]["has_animation"] is not True:
        raise ValueError("fire_temple.has_animation must be True")
    if THEMES["star"]["has_animation"] is not False:
        raise ValueError("star.has_animation must be False")
