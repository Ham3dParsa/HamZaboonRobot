"""Persistent study-session state (Bug 1, owner report 2026-08-15).

Stores the active study session (a JSON blob) so an in-progress session
survives a bot restart. One row per user — the current active session. The
handler owns (de)serialization of its `SessionState`/`SessionNode` dataclasses;
this module is pure JSON I/O with no Telegram/handler imports, so there is no
circular dependency (seam 1).
"""

from __future__ import annotations

import logging
import sqlite3

from services.db.schema import get_conn, _utc_now

logger = logging.getLogger(__name__)


def save_study_session(
    user_id: int, session_date: str, state_json: str
) -> None:
    """Persist (or overwrite) the user's active study-session blob."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO study_sessions(user_id, session_date, state_json, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "session_date=excluded.session_date, "
            "state_json=excluded.state_json, "
            "updated_at=excluded.updated_at",
            (user_id, session_date, state_json, _utc_now().isoformat()),
        )
        conn.commit()


def load_study_session(
    user_id: int,
) -> tuple[str, str] | None:
    """Return the user's persisted session as (session_date, state_json), or
    None when the user has no persisted session."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT session_date, state_json FROM study_sessions "
            "WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return row["session_date"], row["state_json"]


def clear_study_session(user_id: int) -> None:
    """Remove the user's persisted session row (no-op when absent)."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM study_sessions WHERE user_id=?", (user_id,)
        )
        conn.commit()