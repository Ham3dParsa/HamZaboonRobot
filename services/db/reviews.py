"""Review event persistence for spaced-repetition interactions."""

from __future__ import annotations

import datetime
import logging
import time

from services.db.schema import (
    get_conn,
    is_missing_table_error,
    transaction,
    _utc_now,
)

logger = logging.getLogger(__name__)


# review_events columns: id, word_id, user_id, revealed_before_answer,
# outcome, grade, activity_type, grade_source, raw_signal,
# response_time_ms, created_at


REVIEW_OUTCOMES = ("recalled", "recalled_after_peek", "again")


def insert_review_event(
    conn,
    word_id: int,
    user_id: int,
    grade: int,
    activity_type: str,
    *,
    grade_source: str = "direct_button",
    raw_signal: str | None = None,
    response_time_ms: int | None = None,
    created_at_iso: str | None = None,
) -> None:
    """Insert a review event on the caller's open connection (no transaction).

    Synchronous, zero await: pure SQL + outcome mapping. Used by the batched
    grade tap (F1) so grade + event + streak share one atomic transaction.
    """
    outcome = "recalled" if grade >= 2 else "again"
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
            created_at_iso or _utc_now().isoformat(),
        ),
    )


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

    ``grade`` is validated/coerced upfront so only a real DB error can roll
    back the insert — never a bad caller value.
    """
    try:
        grade = int(grade)
    except (TypeError, ValueError):
        raise ValueError(f"invalid grade {grade!r}")
    outcome = "recalled" if grade >= 2 else "again"
    with transaction() as conn:
        insert_review_event(
            conn,
            word_id,
            user_id,
            grade,
            activity_type,
            grade_source=grade_source,
            raw_signal=raw_signal,
            response_time_ms=response_time_ms,
        )
        # Per-card lifetime counters (retention rollup): incremented atomically
        # with the event insert so counters == events ever recorded. The grade
        # path (grade_word_review/grade_first_exposure + this call) therefore
        # keeps counts exact after old raw rows are pruned. Scheduling fields
        # are untouched — this only bumps total_reviews/lapses. Deliberately
        # NOT swallowed: a counter failure rolls back the insert too, so the
        # counters can never drift below the event stream. The lapse rule is
        # the shared _is_lapse (grade already coerced to int above).
        if _is_lapse(grade, outcome):
            conn.execute(
                "UPDATE saved_words SET total_reviews=COALESCE(total_reviews, 0)+1, "
                "lapses=COALESCE(lapses, 0)+1 WHERE id=? AND user_id=?",
                (word_id, user_id),
            )
        else:
            conn.execute(
                "UPDATE saved_words SET total_reviews=COALESCE(total_reviews, 0)+1 "
                "WHERE id=? AND user_id=?",
                (word_id, user_id),
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


def _is_lapse(grade, outcome) -> bool:
    """Lapse rule shared by backfill, insert path, and prune reconcile."""
    if grade is not None:
        try:
            return int(grade) == 1
        except (TypeError, ValueError):
            return False
    return outcome == "again"


def prune_old_review_events(
    retention_days: int = 90,
    keep_per_card: int = 2,
    batch: int = 500,
    *,
    deadline: float | None = None,
) -> int:
    """Aggregate-then-drop prune of review_events (per-card rollup).

    Keep rule per (user_id, word_id): the ``keep_per_card`` newest events
    (created_at DESC, id DESC) plus every event younger than retention_days.
    Before deleting, pruned rows are rolled into the per-card counters on
    saved_words (total_reviews, lapses) via a monotonic reconcile-up
    (MAX(stored, actual lifetime)) for each affected card — a no-op when all
    inserts funneled through ``record_review_event`` (counters already exact),
    and a heal when legacy rows bypassed it. Counters are lifetime totals, so
    admin per-user/global totals read them instead of the raw table.

    The table is never loaded whole: lifetime totals accumulate via keyset
    pagination (``WHERE id > ? ORDER BY id ASC LIMIT ?``, O(batch) rows in
    memory) and victims stream from a single per-card-rank query via
    ``fetchmany``. Deletes run batched by id, each batch in its own short
    ``transaction()`` (no await across it). Stops batching at ``deadline``
    (monotonic) when set so a backlog defers the remainder. Scheduling
    columns on saved_words are never touched. Idempotent. Function only —
    no scheduler wiring.
    """
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retention_days)).isoformat()
    scan = max(1, int(batch))
    # Pass 1: per-card lifetime totals, keyset-paginated (flat memory — one
    # small counter pair per card, never the event rows themselves). The lapse
    # rule stays in Python via _is_lapse, identical to the old full-scan math.
    totals: dict[tuple[int, int], list[int]] = {}
    try:
        last_seen = 0
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, user_id, word_id, grade, outcome "
                    "FROM review_events WHERE id > ? ORDER BY id ASC LIMIT ?",
                    (last_seen, scan),
                ).fetchall()
            if not rows:
                break
            for row in rows:
                key = (row["user_id"], row["word_id"])
                acc = totals.get(key)
                lapse = 1 if _is_lapse(row["grade"], row["outcome"]) else 0
                if acc is None:
                    totals[key] = [1, lapse]
                else:
                    acc[0] += 1
                    acc[1] += lapse
            last_seen = int(rows[-1]["id"])
            if len(rows) < scan:
                break
    except Exception as exc:
        # Pre-migration DB without review_events: silent 0 (as before). Any
        # other failure is logged — a stalled prune must never look like
        # success. Committed batches stay; a re-run resumes idempotently.
        if not is_missing_table_error(exc):
            logger.exception("prune_old_review_events totals scan failed")
        return 0
    # Pass 2: monotonic reconcile-up per card, batched into few transactions
    # instead of one per card. Same MAX(stored, lifetime) SQL as before.
    items = list(totals.items())
    for start in range(0, len(items), scan):
        if deadline is not None and time.monotonic() >= deadline:
            break
        chunk = items[start:start + scan]
        with transaction() as conn:
            for (user_id, word_id), (total, lapses) in chunk:
                conn.execute(
                    "UPDATE saved_words SET "
                    "total_reviews=CASE WHEN COALESCE(total_reviews, 0) < ? THEN ? "
                    "ELSE COALESCE(total_reviews, 0) END, "
                    "lapses=CASE WHEN COALESCE(lapses, 0) < ? THEN ? "
                    "ELSE COALESCE(lapses, 0) END "
                    "WHERE id=? AND user_id=?",
                    (total, total, lapses, lapses, word_id, user_id),
                )
    # Pass 3: victims in per-chunk SELECT … LIMIT inside the write txn — the
    # same per-card keep rule (beyond keep_per_card AND older than cutoff),
    # keyset-paginated by id (``WHERE id > ?``) so no read cursor is ever
    # held open across a separate write connection. Ranks only shrink for
    # survivors as older rows vanish, so ascending-id batches never skip a
    # victim. COALESCE mirrors the old Python `(created_at or "") < cutoff`
    # comparison for NULL timestamps.
    deleted = 0
    try:
        last_id = 0
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            with transaction() as conn:
                rows = conn.execute(
                    "SELECT id FROM ("
                    "SELECT id, created_at, ROW_NUMBER() OVER ("
                    "PARTITION BY user_id, word_id "
                    "ORDER BY created_at DESC, id DESC"
                    ") AS rn FROM review_events WHERE id > ?"
                    ") WHERE rn > ? AND COALESCE(created_at, '') < ? "
                    "ORDER BY id ASC LIMIT ?",
                    (last_id, keep_per_card, cutoff, scan),
                ).fetchall()
                if not rows:
                    break
                chunk_ids = [int(r["id"]) for r in rows]
                placeholders = ",".join("?" * len(chunk_ids))
                conn.execute(
                    f"DELETE FROM review_events WHERE id IN ({placeholders})",
                    chunk_ids,
                )
                deleted += len(chunk_ids)
                last_id = chunk_ids[-1]
                if len(chunk_ids) < scan:
                    break
    except Exception as exc:
        # Pre-migration DB without review_events, or a mid-run failure: report
        # progress so far (silent only for missing-table); any other failure
        # is logged so a partial run is distinguishable from a clean one.
        # Committed batches stay, a re-run resumes cleanly.
        if not is_missing_table_error(exc):
            logger.exception(
                "prune_old_review_events victims delete failed deleted=%s", deleted
            )
        return deleted
    return deleted
