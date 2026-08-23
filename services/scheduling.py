"""Session scheduling — daily session quotas per plan.

Quota is stored in the settings table as:
    sessions_used_{user_id}_{date} = "<integer>"

A session is one invocation of handle_study_start(). Quota is consumed
once at the top of handle_study_start(), before build_session_list().
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from config import APP_TZ
from services.db import get_setting, set_setting
from services.db.schema import transaction

logger = logging.getLogger(__name__)

_app_tz = APP_TZ


def _today_str() -> str:
    return datetime.now(_app_tz).date().isoformat()


def _session_key(user_id: int) -> str:
    return f"sessions_used_{user_id}_{_today_str()}"


def _get_used(user_id: int) -> int:
    raw = get_setting(_session_key(user_id), "0")
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 0


def _max_sessions_for_plan(plan: str) -> int:
    """Return the plan's daily session budget (max_sessions) from the DB.

    Missing/deactivated plans fall back to the free-plan value.
    """
    from config import max_sessions_for_plan as _db_max_sessions
    return _db_max_sessions(plan)


def daily_session_budget(user_id: int, plan: str) -> dict:
    total = _max_sessions_for_plan(plan)
    used = _get_used(user_id)
    return {
        "total": total,
        "remaining": max(0, total - used),
        "used": used,
        "plan": plan,
    }


def consume_session_slot(user_id: int, plan: str = "free") -> bool:
    """Atomically check quota and increment usage if under limit.

    Returns True if a slot was consumed (session may proceed).
    Returns False if quota exceeded (session must not start).
    """
    limit = _max_sessions_for_plan(plan)
    key = _session_key(user_id)
    with transaction() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        try:
            used = int(row["value"]) if row else 0
        except (ValueError, TypeError):
            used = 0
        if used >= limit:
            logger.info(
                "session quota exceeded user_id=%s used=%s limit=%s",
                user_id, used, limit,
            )
            return False
        new_val = str(used + 1)
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, new_val),
        )
    logger.debug(
        "consume_session_slot user_id=%s used=%s->%s limit=%s",
        user_id, used, used + 1, limit,
    )
    return True


def release_session_slot(user_id: int) -> None:
    """Decrement session usage (rollback on error or empty session)."""
    key = _session_key(user_id)
    with transaction() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        try:
            used = int(row["value"]) if row else 0
        except (ValueError, TypeError):
            used = 0
        new_val = str(max(0, used - 1))
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, new_val),
        )
    logger.debug(
        "release_session_slot user_id=%s used=%s->%s",
        user_id, used, max(0, used - 1),
    )
