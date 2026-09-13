"""Pure streak date math (REF6-T1 single owner) + Boolean-tap debt map (REF6-T2, docs-only).

Single owner for streak **date math**: ``next_streak()`` here is the only
place that computes same-day idempotency / yesterday-derived increment /
gap-reset-to-1. ``services/db/users.py:touch_streak_in_txn`` and
``touch_streak`` are thin delegates (pure math + SQL, no duplicated logic).
Invalid ISO ``today_iso`` values propagate ``ValueError`` from
``datetime.date.fromisoformat`` so the caller's transaction rollback
semantics stay byte-identical; no fail-open catch here. No SQL, no
XP/shield/daily_stats, no DB imports in this module.

REF6-T2 — Boolean-tap debt map (docs-only, no behavior change)
---------------------------------------------------------------
Current product behavior is intentionally **Boolean per-tap**: every
successful tap that reaches a streak touch advances ``last_active_date``
to today (idempotent within the day). This is registered as tech debt;
RULE-001 (SessionCompleted-only streak) is BLOCKED until owner lock.
This module documents the map; it does NOT flip defaults, add grade
gates, or merge transactions.

1) ``services/word_query.py:295`` — separate-transaction touch
   - ``ask()`` persists the card via ``db.create_query_result`` (txn 1)
     then touches streak via ``db.touch_streak(user_id)`` (txn 2).
   - Two distinct ``transaction()`` blocks; a crash between them can
     leave card persisted without streak.
   - Debt: non-atomic card+streak pair. Do NOT merge into one txn in
     this ticket (keeps quota/streak accounting unchanged; merge is
     naive risk per plan-refine-track-f-streaktech.md REF6-T2).

2) ``services/db/words.py:511-512`` and ``:578-579`` — grades always touch
   when ``with_streak=True``, regardless of grade value
   - Both ``grade_word_review(..., with_streak=False)`` and
     ``grade_first_exposure(..., with_streak=False)`` default to *no*
     streak side-effect (legacy grade-only).
   - When ``with_streak=True`` the body calls
     ``touch_streak_in_txn(conn, user_id)`` on the **same** open
     ``transaction()`` as the FSRS update + ``mark_word_graded`` +
     optional ``insert_review_event`` — one atomic per-tap txn.
   - Debt: Boolean — even ``grade=1`` (Again) touches streak when the
     caller passes ``with_streak=True``. No grade-value gate here.

3) Call sites that set ``with_streak=True`` (current Boolean-tap sources)
   - ``handlers/srs_handler.py:414-423`` — ``_handle_srs_review`` →
     ``grade_service.grade(..., activity="srs_review", with_streak=True)``
   - ``handlers/srs_handler.py:586-595`` — ``_handle_first_exposure_grade``
     → ``grade_service.grade(..., activity="first_exposure", with_streak=True)``
   - ``services/word_query.py:295`` — ``ask()`` → ``db.touch_streak``
     (separate txn, no ``with_streak`` flag; word-query always taps)
   - ``handlers/user.py`` — no direct streak tap (settings/onboarding only)
   - ``services/grade_service.py:70,88,97`` — facade preserves
     ``with_streak=False`` default; does not flip.

Constraints for this ticket (REF6-T2)
-------------------------------------
- NO default flip (``with_streak`` stays ``False``)
- NO grade gate (e.g. ``grade >= 2``)
- NO txn merge for ``word_query`` card+streak
- Companion doc: ``services/streak/TAP_MAP.md`` (same map in markdown)
- Future fix (RULE-001) will gate streak on ``SessionCompleted`` and
  remove per-tap touches — blocked until owner says "locked".
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
