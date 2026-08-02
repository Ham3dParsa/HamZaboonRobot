"""Review event persistence for spaced-repetition interactions."""

from __future__ import annotations

from services.db.schema import get_conn, _utc_now


# review_events columns: id, word_id, user_id, revealed_before_answer,
# outcome, grade, activity_type, grade_source, raw_signal,
# response_time_ms, created_at


REVIEW_OUTCOMES = ("recalled", "recalled_after_peek", "again")


def record_review_event(
    word_id: int,
    user_id: int,
    grade: int,
    activity_type: str,
    *,
    grade_source: str = "direct_button",
    raw_signal: str | None = None,
    response_time_ms: int | None = None,
) -> None:
    """Persist a review event with grade, source, and raw signal.

    Writes all review_events columns including the new grade/signal fields.
    The outcome column is derived from grade for backward-compatible reads
    of historical data. It is NOT load-bearing for scheduling logic —
    new features should read 'grade' directly.

    grade=1 (Again) → outcome="again"      (failure)
    grade>=2       → outcome="recalled"    (success, including Hard)
    """
    outcome = "recalled" if grade >= 2 else "again"
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO review_events "
            "(word_id, user_id, grade, activity_type, grade_source, "
            " raw_signal, response_time_ms, outcome, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                word_id,
                user_id,
                grade,
                activity_type,
                grade_source,
                raw_signal,
                response_time_ms,
                outcome,
                _utc_now().isoformat(),
            ),
        )
        conn.commit()
