"""Persistent post-session report storage (R10).

Stores a finished session's :class:`SessionReport` (serialized by
``services.session.summary``) so the user can reopen it for a limited window
(3 days) via ``/reports``. One row per session completion. Mirrors
``sessions.py``: pure JSON I/O + SQL with no Telegram/handler imports, so there
is no circular dependency.

Retention uses the UTC ``created_at`` (processing metadata); the app-tz
``session_date`` is kept for user-facing display. Expired rows are purged
lazily on save and on list (R10-E) — no scheduler.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

from services.db.schema import _utc_now, transaction
from services.session.summary import SessionReport, deserialize_report, serialize_report

logger = logging.getLogger(__name__)

# Reports are kept for this many days before being purged (R10-D).
REPORT_WINDOW_DAYS = 3


@dataclass(frozen=True)
class ReportEntry:
    """Lightweight list item for ``/reports`` (R10-C)."""

    report_id: int
    session_date: str


@dataclass(frozen=True)
class LoadedReport:
    """A fully reopened report plus its identity/visibility flags."""

    session_date: str
    report: SessionReport
    is_admin: bool


def _cutoff(now: datetime.datetime | None = None) -> str:
    """ISO UTC timestamp marking the start of the retention window."""
    now = now or _utc_now()
    return (now - datetime.timedelta(days=REPORT_WINDOW_DAYS)).isoformat()


def save_session_report(
    user_id: int,
    session_date: str,
    report: SessionReport,
    *,
    is_admin: bool = False,
) -> None:
    """Persist a completed session's report (R10-B). Purges expired rows first."""
    payload = serialize_report(report)
    with transaction() as conn:
        conn.execute(
            "DELETE FROM session_reports WHERE created_at < ?",
            (_cutoff(),),
        )
        conn.execute(
            "INSERT INTO session_reports(user_id, session_date, created_at, report_json, is_admin) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, session_date, _utc_now().isoformat(), payload, 1 if is_admin else 0),
        )


def list_recent_reports(
    user_id: int,
    *,
    now: datetime.datetime | None = None,
) -> list[ReportEntry]:
    """Return the user's reports still within the retention window (R10-C/D).

    Purging is lazy: expired rows for every user are removed here and on save.
    DELETE+SELECT run in a single ``transaction()`` so purge-then-read is
    atomic and cannot race a concurrent save.
    """
    # NOTE(Kilo 82, 89): BEGIN IMMEDIATE across the read is intentional — lazy
    # purge must be atomic with the following SELECT, otherwise a concurrent
    # save's purge could interleave (ghost read). The alternative (DELETE in a
    # transaction then SELECT outside) reintroduces the race, so we keep the
    # single transaction. Lock is short (only DELETE+SELECT, no await, no I/O)
    # and bounded by _DB_BUSY_TIMEOUT (5 s); retention purge is rare (only
    # rows older than the 3-day window, lazily on save/list/load) so contention
    # is minimal.
    cutoff = _cutoff(now)
    with transaction() as conn:
        conn.execute("DELETE FROM session_reports WHERE created_at < ?", (cutoff,))
        rows = conn.execute(
            "SELECT id, session_date FROM session_reports "
            "WHERE user_id=? AND created_at >= ? "
            "ORDER BY created_at DESC",
            (user_id, cutoff),
        ).fetchall()
    return [ReportEntry(report_id=row["id"], session_date=row["session_date"]) for row in rows]


def load_report(report_id: int, user_id: int) -> LoadedReport | None:
    """Load one report, ownership-checked and within the retention window.

    Returns ``None`` for a missing, expired, or foreign report so the handler
    fails closed (R10-E) instead of rendering stale or foreign data.
    DELETE+SELECT run in a single ``transaction()`` so purge-then-read is
    atomic (same bounded-lock rationale as ``list_recent_reports`` — see
    NOTE Kilo 89 there).
    """
    cutoff = _cutoff()
    with transaction() as conn:
        conn.execute("DELETE FROM session_reports WHERE created_at < ?", (cutoff,))
        row = conn.execute(
            "SELECT session_date, report_json, is_admin FROM session_reports "
            "WHERE id=? AND user_id=? AND created_at >= ?",
            (report_id, user_id, cutoff),
        ).fetchone()
    if row is None:
        return None
    try:
        report = deserialize_report(row["report_json"])
    except (ValueError, TypeError):
        logger.warning(
            "corrupt session report id=%s user_id=%s; purging", report_id, user_id
        )
        with transaction() as conn:
            conn.execute(
                "DELETE FROM session_reports WHERE id=? AND user_id=?", (report_id, user_id)
            )
        return None
    return LoadedReport(
        session_date=row["session_date"],
        report=report,
        is_admin=bool(row["is_admin"]),
    )