"""Thin activity-dispatched grade facade (REF4-T2).

Maps ``activity in {srs_review, first_exposure}`` to the verbatim bodies in
``services/db/words.py`` and delegates with identical kwargs:

- ``srs_review`` — owned by ``grade_word_review`` (recall-based FSRS update:
  ``update_difficulty`` + short-term vs long-term stability branch).
- ``first_exposure`` — owned by ``grade_first_exposure`` (familiarity seed via
  ``initial_stability_first_exposure`` / ``initial_difficulty`` plus
  ``first_exposure_done=1``).

Rules preserved from the owners: each tap runs exactly one immediate
transaction owned by the body (grade + ``mark_word_graded`` + optional
``insert_review_event`` when ``grade_source`` is not None + optional
``touch_streak_in_txn`` when ``with_streak`` is true, all-or-nothing); this
module is fully synchronous with zero async suspension inside the open
transaction (callers wrap it in ``asyncio.to_thread`` as before); defaults
(``grade_source=None``, ``with_streak=False``) preserve legacy grade-only
behavior. No SQL lives here. Additive only: existing import paths keep
working; nothing was moved and the twin formulas were not merged.
"""

from __future__ import annotations

# Per-activity named aliases — plain re-exports of the verbatim bodies (same
# objects, not copies), so the scheduling SQL stays single-sourced in words.py.
from services.db.words import (
    GradeResult,
    grade_first_exposure,
    grade_word_review,
)

__all__ = [
    "GRADE_ACTIVITIES",
    "ACTIVITY_OWNER",
    "grade",
    "grade_word_review",
    "grade_first_exposure",
    "GradeResult",
]

GRADE_ACTIVITIES: tuple[str, str] = ("srs_review", "first_exposure")

# activity -> owning body. Review recall and familiarity seed stay on separate
# branches (never merged into one formula path).
ACTIVITY_OWNER: dict[str, str] = {
    "srs_review": "grade_word_review",
    "first_exposure": "grade_first_exposure",
}


def _check_activity(activity: str) -> str:
    if activity not in ACTIVITY_OWNER:
        raise ValueError(
            f"unknown grade activity={activity!r}; "
            f"expected one of {', '.join(GRADE_ACTIVITIES)}"
        )
    return activity


def grade(
    word_id: int,
    grade_value: int,
    user_id: int,
    *,
    activity: str,
    grade_source: str | None = None,
    raw_signal: str | None = None,
    response_time_ms: int | None = None,
    with_streak: bool = False,
) -> GradeResult:
    """Sync pass-through: dispatch one tap to the owning grade body.

    ``activity`` selects the branch; every other argument forwards verbatim so
    the facade returns the same outcome and DB row as calling the body
    directly. Raises ``ValueError`` on unknown activity and propagates the
    body's ``ValueError`` on invalid grade (1-4 only).
    """
    _check_activity(activity)
    if activity == "srs_review":
        return grade_word_review(
            word_id,
            grade_value,
            user_id,
            grade_source=grade_source,
            raw_signal=raw_signal,
            response_time_ms=response_time_ms,
            with_streak=with_streak,
        )
    return grade_first_exposure(
        word_id,
        grade_value,
        user_id,
        grade_source=grade_source,
        raw_signal=raw_signal,
        response_time_ms=response_time_ms,
        with_streak=with_streak,
    )
