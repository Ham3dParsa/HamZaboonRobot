"""Session scheduling — daily session quotas per plan.

Quota is stored in the settings table as:
    sessions_used_{user_id}_{date} = "<integer>"

A session is one invocation of handle_study_start(). Quota is consumed
once at the top of handle_study_start(), before build_session_list().
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from config import APP_TIMEZONE
from services.db import get_conn, get_setting, set_setting

logger = logging.getLogger(__name__)

_app_tz = ZoneInfo(APP_TIMEZONE)

PLAN_SESSION_CONFIG: dict[str, int] = {
    "free": 1,
    "silver": 4,
    "gold": 10,
}


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


def daily_session_budget(user_id: int, plan: str) -> dict:
    total = PLAN_SESSION_CONFIG.get(plan, PLAN_SESSION_CONFIG["free"])
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
    limit = PLAN_SESSION_CONFIG.get(plan, PLAN_SESSION_CONFIG["free"])
    key = _session_key(user_id)
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        try:
            used = int(row["value"]) if row else 0
        except (ValueError, TypeError):
            used = 0
        if used >= limit:
            conn.commit()
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
        conn.commit()
    logger.debug(
        "consume_session_slot user_id=%s used=%s->%s limit=%s",
        user_id, used, used + 1, limit,
    )
    return True


def release_session_slot(user_id: int) -> None:
    """Decrement session usage (rollback on error or empty session)."""
    key = _session_key(user_id)
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
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
        conn.commit()
    logger.debug(
        "release_session_slot user_id=%s used=%s->%s",
        user_id, used, max(0, used - 1),
    )
