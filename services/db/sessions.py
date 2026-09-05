"""Persistent study-session state (Bug 1, owner report 2026-08-15).

Stores the active study session (a JSON blob) so an in-progress session
survives a bot restart. One row per user — the current active session. The
handler owns (de)serialization of its `SessionState`/`SessionNode` dataclasses;
this module is pure JSON I/O with no Telegram/handler imports, so there is no
circular dependency (seam 1).
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
import time

from services.db.schema import get_conn, transaction, _today, _utc_now

logger = logging.getLogger(__name__)


def save_study_session(
    user_id: int, session_date: str, state_json: str
) -> None:
    """Persist (or overwrite) the user's active study-session blob."""
    with transaction() as conn:
        conn.execute(
            "INSERT INTO study_sessions(user_id, session_date, state_json, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "session_date=excluded.session_date, "
            "state_json=excluded.state_json, "
            "updated_at=excluded.updated_at",
            (user_id, session_date, state_json, _utc_now().isoformat()),
        )


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
    with transaction() as conn:
        conn.execute(
            "DELETE FROM study_sessions WHERE user_id=?", (user_id,)
        )


# ---------------------------------------------------------------------------
# Durable session grade ledger (Bug report 2026-08-19, contract R2)
#
# A per-user ledger of word_ids already graded in the current study session.
# The ledger survives the session JSON being cleared at completion, a network
# timeout on the advance/report edit, and a bot restart, so a re-tap on a
# graded card can never re-run the FSRS transition. It is written atomically
# inside the same transaction as the grade (see words.grade_*). It is reset
# ONLY when a NEW study session is built (handle_study_start fresh-build path),
# which is what lets a word legitimately reappear in a later same-day session.
# ---------------------------------------------------------------------------

_LEDGER_INSERT = (
    "INSERT INTO session_grade_ledger(user_id, word_id, activity_type, graded_at) "
    "VALUES (?, ?, ?, ?) "
    "ON CONFLICT(user_id, word_id, activity_type) DO NOTHING"
)


def mark_word_graded(
    user_id: int,
    word_id: int,
    activity_type: str,
    *,
    conn: sqlite3.Connection | None = None,
    graded_at_iso: str | None = None,
) -> None:
    """Record ``word_id`` as graded (``activity_type``) in the current session.

    The ledger is keyed by activity type so a word first-exposed in one session
    can be legitimately reviewed in a later session (fresh build clears it) and
    an old first-exposure grade never blocks a real review grade (R2). When
    ``conn`` is provided the write joins the caller's open transaction (used by
    the atomic grade transition); otherwise a dedicated transaction is used.
    Repeating the same (user, word, activity) is a no-op.
    """
    ts = graded_at_iso or _utc_now().isoformat()
    if conn is None:
        with transaction() as conn:
            conn.execute(_LEDGER_INSERT, (user_id, word_id, activity_type, ts))
    else:
        conn.execute(_LEDGER_INSERT, (user_id, word_id, activity_type, ts))


def is_word_graded(user_id: int, word_id: int, activity_type: str) -> bool:
    """True when ``word_id`` was already graded with ``activity_type`` in the
    user's current session."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM session_grade_ledger "
            "WHERE user_id=? AND word_id=? AND activity_type=?",
            (user_id, word_id, activity_type),
        ).fetchone()
    return row is not None


def clear_session_grades(user_id: int) -> None:
    """Reset the ledger for a new study session (fresh build only)."""
    with transaction() as conn:
        conn.execute(
            "DELETE FROM session_grade_ledger WHERE user_id=?", (user_id,)
        )


def purge_stale_study_sessions(*, batch: int = 500, deadline: float | None = None) -> dict[str, int]:
    """Midnight sweep: delete sessions/ledger rows older than yesterday.

    A session lives until 00:00 the next night; the next day starts from zero.
    ``study_sessions.session_date`` is an app-tz day, so rows with
    ``session_date`` older than yesterday (app-tz) go. The ledger has no
    session-date column — ``graded_at`` (UTC processing metadata) older than
    ~2 days is the proxy, which always keeps today plus yesterday in any tz.
    Same-day resume (``load_study_session``) and today's grading guards
    (``is_word_graded``) are untouched. DELETE-only, batched via rowid, each
    batch in its own short ``transaction()``. Stops batching at ``deadline``
    (monotonic) when set. Function only — no scheduler wiring (per T1
    contract). Returns per-table deleted counts.
    """
    day_cutoff = (_today() - datetime.timedelta(days=1)).isoformat()
    ledger_cutoff = (_utc_now() - datetime.timedelta(days=2)).isoformat()
    counts = {"study_sessions": 0, "session_grade_ledger": 0}
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            break
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM study_sessions WHERE rowid IN ("
                "SELECT rowid FROM study_sessions WHERE session_date < ? LIMIT ?)",
                (day_cutoff, batch),
            )
            n = cur.rowcount or 0
        counts["study_sessions"] += n
        if n < batch:
            break
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            break
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM session_grade_ledger WHERE rowid IN ("
                "SELECT rowid FROM session_grade_ledger WHERE graded_at < ? LIMIT ?)",
                (ledger_cutoff, batch),
            )
            n = cur.rowcount or 0
        counts["session_grade_ledger"] += n
        if n < batch:
            break
    if counts["study_sessions"] or counts["session_grade_ledger"]:
        logger.debug(
            "purge_stale_study_sessions deleted=%s day_cutoff=%s",
            counts, day_cutoff,
        )
    return counts
