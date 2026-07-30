from services.db.schema import get_conn, _utc_now


REVIEW_OUTCOMES = ("recalled", "recalled_after_peek", "again")

# review_events table schema: id, word_id, user_id, revealed_before_answer,
# outcome, grade, activity_type, grade_source, raw_signal, response_time_ms, created_at


def record_review_event(
    word_id: int,
    user_id: int,
    *,
    revealed_before_answer: bool,
    outcome: str,
) -> None:
    """Persist a spaced-repetition interaction event for later retention analysis.

    Records whether the learner revealed the full card before answering and the
    final outcome, so recall confidence can be estimated without changing the
    scheduling intervals.
    """
    if outcome not in REVIEW_OUTCOMES:
        raise ValueError(f"unknown review outcome: {outcome}")
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO review_events "
            "(word_id, user_id, revealed_before_answer, outcome, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                word_id,
                user_id,
                1 if revealed_before_answer else 0,
                outcome,
                _utc_now().isoformat(),
            ),
        )
        conn.commit()


def record_review_event_v2(
    word_id: int,
    user_id: int,
    grade: int,
    activity_type: str,
    *,
    grade_source: str = "button",
    raw_signal: str = None,
    response_time_ms: int = None,
) -> None:
    """Record a review event with extended grade/signal columns.

    Currently delegates to the original record_review_event; new columns
    (grade, activity_type, grade_source, raw_signal, response_time_ms) are
    accepted as parameters and will be persisted once the schema migration
    adds them to review_events.
    """
    # grade, activity_type, grade_source, raw_signal, response_time_ms
    # are accepted but not yet written to the database.
    outcome = "recalled" if grade >= 3 else "again"
    record_review_event(
        word_id=word_id,
        user_id=user_id,
        revealed_before_answer=False,
        outcome=outcome,
    )
