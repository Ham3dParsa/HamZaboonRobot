"""Pure streak date math (REF6-T1 single owner).

Tech-only extraction of the date rules formerly inline in
``services.db.users.touch_streak_in_txn``: same-day idempotency,
yesterday-derived increment, gap reset to 1. Pure stdlib only —
no SQL, no XP/shield/daily_stats, no DB imports. Invalid ISO dates
raise (``datetime.date.fromisoformat`` propagation) so grade-transaction
rollback semantics stay byte-identical; no fail-open catch here.
"""

import datetime


def next_streak(streak: int, last_active_date: str | None, today_iso: str) -> int:
    """Return the new streak for ``today_iso`` given stored state.

    - same day (``last_active_date == today_iso``) → ``streak`` (idempotent)
    - yesterday → ``streak + 1``
    - otherwise (gap / first touch / ``None``) → ``1``
    """
    if last_active_date == today_iso:
        return streak
    yesterday = (
        datetime.date.fromisoformat(today_iso) - datetime.timedelta(days=1)
    ).isoformat()
    return streak + 1 if last_active_date == yesterday else 1
