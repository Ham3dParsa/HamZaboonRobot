"""Canonical plan-identity registry (J-B6, R5/F5).

Pure, stdlib-only leaf module with **no application imports**. It is the single
source of truth for:

- the set of valid plan codes and their learner-facing labels / tier rank;
- which plans are premium (paid) tiers;
- feature gating via a ``feature -> minimum-rank`` map.

Every plan/feature decision in the app must derive from these helpers so that
adding a tier or a feature is a one-map change with automatic inheritance.
No other module may hold a parallel plan dictionary or a parallel feature gate.
"""

from __future__ import annotations

from typing import TypedDict


class _PlanSpec(TypedDict):
    """Precise shape of a single plan-identity entry."""

    label: str
    premium: bool
    rank: int


# Plan code -> metadata. ``rank`` orders tiers low->high (0 = free base);
# ``premium`` marks the paid tiers. Features inherit automatically from the
# ``_FEATURE_MIN_RANK`` map, so a new tier never silently misses a feature.
_PLANS: dict[str, _PlanSpec] = {
    "free":    {"label": "رایگان",  "premium": False, "rank": 0},
    "bronze":  {"label": "برنزی",   "premium": False, "rank": 1},
    "silver":  {"label": "نقره‌ای", "premium": True,  "rank": 2},
    "gold":    {"label": "طلایی",   "premium": True,  "rank": 3},
    "emerald": {"label": "زمردی",   "premium": True,  "rank": 4},
}

# Feature -> minimum rank that unlocks it. A plan enables a feature when its
# rank is >= the feature's min rank; lower tiers inherit nothing, higher tiers
# inherit automatically. This is the ONLY feature-gate definition in the app.
_FEATURE_MIN_RANK: dict[str, int] = {
    "pronounce":    0,   # free to all (locked product decision, 2026-08-17)
    "card_modes":   2,   # silver+
    "presentation": 2,   # silver+
}


def valid_plans() -> frozenset[str]:
    """Return the set of valid plan codes."""
    return frozenset(_PLANS)


def is_premium(plan: str) -> bool:
    """Return True if ``plan`` is a paid (premium) tier."""
    entry = _PLANS.get(plan)
    return bool(entry and entry["premium"])


def plan_label(plan: str) -> str:
    """Return the learner-facing Persian label for ``plan``."""
    entry = _PLANS.get(plan)
    return entry["label"] if entry else plan


def has_feature(plan: str, feature: str) -> bool:
    """Return True if ``plan`` is entitled to ``feature``.

    Unknown plans and unknown features are denied (fail-closed): callers treat
    a False as "not entitled" and fall back to the safe / limited behavior.
    """
    entry = _PLANS.get(plan)
    if entry is None:
        return False
    min_rank = _FEATURE_MIN_RANK.get(feature)
    if min_rank is None:
        return False
    # int() keeps the comparison fail-closed if a malformed (e.g. string) rank
    # slips past the (un-enforced at runtime) _PlanSpec typing.
    return int(entry["rank"]) >= min_rank