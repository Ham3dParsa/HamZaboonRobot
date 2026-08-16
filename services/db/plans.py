"""Plan spec persistence — admin-editable plan definitions.

Contract R1 (DB `plans` table), R2 (5 plans, gold stays a code name),
R6 (price stored + admin display only), R7 (edit + deactivate, no hard delete),
R8 (DB seed is the sole source of plan limits).

The `plans` table is the single source of truth for per-plan limits:
query_quota, max_sessions, and cards_per_session. DEFAULT_PLANS here seeds a
fresh database; armed rows are managed by the admin plan-manager wizard.
"""

from __future__ import annotations

from services.db.schema import get_conn, transaction

# name -> (display_name, price_toman, query_quota, max_sessions, cards_per_session, sort_order)
DEFAULT_PLANS: dict[str, tuple[str, int, int, int, int, int]] = {
    # code     display   price  query  sessions  cards  sort
    "free":    ("رایگان", 0,      2,     2,        3,     0),
    "bronze":  ("برنزی",  0,      4,     3,        3,     1),
    "silver":  ("نقره‌ای", 0,     7,     3,        5,     2),
    "gold":    ("طلایی",  0,     12,     4,        7,     3),
    "emerald": ("زمردی",  0,     20,     5,        9,     4),
}

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
    except Exception:
        pass
    display, price, query, sessions, cards, _ = DEFAULT_PLANS["free"]
    return {
        "display_name": display, "price": price,
        "query_quota": query, "max_sessions": sessions,
        "cards_per_session": cards, "is_active": 1,
    }


def is_premium(plan: str) -> bool:
    """Return True if `plan` is a premium tier (silver/gold/emerald)."""
    from config import PREMIUM_PLANS
    return plan in PREMIUM_PLANS


def effective_plan(plan: str, bypass_limits: bool = False) -> str:
    """Return the effective plan name after limit-bypass resolution."""
    if bypass_limits:
        return "gold"
    from config import PLANS
    return plan if plan in PLANS else "free"
