"""Review event persistence for spaced-repetition interactions."""

from __future__ import annotations

from services.db.schema import get_conn, transaction, _utc_now


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
    with transaction() as conn:
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


def recent_events_for_words(
    word_ids: list[int],
    user_id: int,
    per_word: int = 2,
) -> dict[int, list[dict]]:
    """Return the most recent review events per word, newest first.

    Used by the session summary to recover each graded word's grade /
    activity type (the newest event) and its prior review date (the next one).
    ``per_word`` caps how many events per word are returned. A word with no
    events is simply absent from the result.
    """
    if not word_ids:
        return {}
    placeholders = ",".join("?" * len(word_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT word_id, grade, activity_type, created_at "
            f"FROM review_events "
            f"WHERE user_id=? AND word_id IN ({placeholders}) "
            f"ORDER BY word_id, created_at DESC, id DESC",
            (user_id, *word_ids),
        ).fetchall()
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["word_id"], []).append(dict(row))
    return {wid: evs[:per_word] for wid, evs in grouped.items()}
