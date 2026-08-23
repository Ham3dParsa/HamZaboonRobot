"""Plan spec persistence — admin-editable plan definitions.

Contract R1 (DB `plans` table), R2 (5 plans, gold stays a code name),
R6 (price stored + admin display only), R7 (edit + deactivate, no hard delete),
R8 (DB seed is the sole source of plan limits).

The `plans` table is the single source of truth for per-plan limits:
query_quota, max_sessions, and cards_per_session. DEFAULT_PLANS here seeds a
fresh database; armed rows are managed by the admin plan-manager wizard.
"""

from __future__ import annotations

import logging

from config.plan_identity import plan_label, valid_plans
from services.db.schema import get_conn, transaction

logger = logging.getLogger(__name__)

# Per-plan limits — the DB-seed data model (price + per-plan quotas/order).
# Plan identity (label/premium/rank) is single-sourced in config.plan_identity;
# display_name is derived from it below so a Persian plan label lives in exactly
# one place (closes the R5/F5 duplicate-label gap).
_PLAN_LIMITS: dict[str, tuple[int, int, int, int, int]] = {
    # code     price  query  sessions  cards  sort
    "free":    (0,     2,     2,        3,     0),
    "bronze":  (0,     4,     3,        3,     1),
    "silver":  (0,     7,     3,        5,     2),
    "gold":    (0,     12,    4,        7,     3),
    "emerald": (0,     20,    5,        9,     4),
}

# name -> (display_name, price_toman, query_quota, max_sessions, cards_per_session, sort_order)
# The plan code set is the single source in config.plan_identity; every seeded
# plan must also have a limit entry here, or seeding fails loudly (no silent
# drift between identity and the DB seed).
DEFAULT_PLANS: dict[str, tuple[str, int, int, int, int, int]] = {}
for _code in valid_plans():
    if _code not in _PLAN_LIMITS:
        raise RuntimeError(
            f"plan_identity defines {_code!r} but _PLAN_LIMITS has no DB seed entry"
        )
    _price, _query, _sessions, _cards, _sort = _PLAN_LIMITS[_code]
    DEFAULT_PLANS[_code] = (plan_label(_code), _price, _query, _sessions, _cards, _sort)

# Reverse check — no orphan limits without identity (R1 hardening, #18)
_extra = set(_PLAN_LIMITS) - set(valid_plans())
if _extra:
    raise RuntimeError(f"_PLAN_LIMITS has orphan entries not in plan_identity: {_extra!r}")


def validate_plan_consistency() -> None:
    """Validate that plan identity and limits are in sync (single-source guard).

    Called by tests; also runs at import via the checks above. Ensures
    `valid_plans() == set(_PLAN_LIMITS) == set(DEFAULT_PLANS)`.
    """
    vp = set(valid_plans())
    if vp != set(_PLAN_LIMITS):
        raise ValueError(f"plan limits/identity drift: valid_plans={vp} _PLAN_LIMITS={set(_PLAN_LIMITS)}")
    if vp != set(DEFAULT_PLANS):
        raise ValueError(f"DEFAULT_PLANS drift: valid_plans={vp} DEFAULT_PLANS={set(DEFAULT_PLANS)}")

_PLAN_COLUMNS = (
    "name, display_name, price, query_quota, max_sessions, "
    "cards_per_session, is_active, sort_order"
)


def get_plan(name: str) -> dict | None:
    """Return the plan row for `name`, or None if it does not exist.

    Includes inactive plans so admin can still see/edit them.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE name=?", (name,)
        ).fetchone()
    return dict(row) if row else None


def list_plans(active_only: bool = False) -> list[dict]:
    """Return all plans ordered by sort_order. Handles inactive plans."""
    where = "WHERE is_active=1" if active_only else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM plans {where} ORDER BY sort_order ASC, name ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def valid_plan_name(name: str) -> bool:
    """Return True if `name` refers to an existing plan (active or not)."""
    return get_plan(name) is not None


def upsert_plan(
    name: str,
    display_name: str,
    price: int,
    query_quota: int,
    max_sessions: int,
    cards_per_session: int,
    sort_order: int = 0,
    is_active: int = 1,
) -> None:
    """Insert or update a plan spec (admin plan-manager wizard)."""
    if name not in valid_plans():
        raise ValueError(f"Invalid plan code: {name}")
    with transaction() as conn:
        conn.execute(
            f"INSERT INTO plans({_PLAN_COLUMNS}) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            f"ON CONFLICT(name) DO UPDATE SET "
            f"display_name=excluded.display_name, price=excluded.price, "
            f"query_quota=excluded.query_quota, max_sessions=excluded.max_sessions, "
            f"cards_per_session=excluded.cards_per_session, "
            f"is_active=excluded.is_active, sort_order=excluded.sort_order",
            (
                name,
                display_name,
                int(price),
                int(query_quota),
                int(max_sessions),
                int(cards_per_session),
                int(is_active),
                int(sort_order),
            ),
        )


def set_plan_active(name: str, active: bool) -> bool:
    """Toggle a plan's is_active flag. Returns False if plan does not exist."""
    if not valid_plan_name(name):
        return False
    with transaction() as conn:
        conn.execute(
            "UPDATE plans SET is_active=? WHERE name=?",
            (1 if active else 0, name),
        )
    return True


def plan_spec(plan: str) -> dict:
    """Return the armed plan spec dict, falling back to free defaults.

    R2/R7: a missing or deactivated plan resolves to the 'free' spec. This is
    the single source of per-plan quota semantics; config delegates here (R5).
    """
    try:
        spec = get_plan(plan)
        if spec and spec.get("is_active", 1):
            return spec
    except Exception as exc:
        logger.warning(
            "plan_spec: failed to read plan %r; falling back to free: %s", plan, exc
        )
    display, price, query, sessions, cards, _ = DEFAULT_PLANS["free"]
    return {
        "display_name": display, "price": price,
        "query_quota": query, "max_sessions": sessions,
        "cards_per_session": cards, "is_active": 1,
    }


def effective_plan(plan: str, bypass_limits: bool = False) -> str:
    """Return the effective plan name after limit-bypass resolution."""
    if bypass_limits:
        return "gold"
    from config.plan_identity import valid_plans
    return plan if plan in valid_plans() else "free"
