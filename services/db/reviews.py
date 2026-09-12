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

    Also bumps the per-card lifetime counters (total_reviews, lapses) on the
    SAME open connection, atomically with the INSERT — moved here from the
    deleted record_review_event wrapper so every caller (grade batch, tests,
    future callers) gets insert-plus-counters with zero extra transactions.
    Scheduling fields are untouched. The lapse rule is the shared _is_lapse
    (grade 1, or legacy NULL grade with outcome again), identical to main's
    deleted code. Deliberately NOT swallowed: a counter failure rolls back
    the insert too, so counters can never drift below the event stream.
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

    REF3-T2: ``word_ids`` are read in chunks of at most 500 placeholders
    (SQLite IN-variable guard) and the per-word cap is applied in SQL via
    ``ROW_NUMBER() OVER (PARTITION BY word_id ORDER BY created_at DESC,
    id DESC)`` filtered to ``rn <= per_word`` (same tiebreaker as
    ``prune_old_review_events``). Input ids are de-duplicated preserving
    order first: the result is keyed by ``word_id``, so input multiplicity
    is semantically irrelevant and must not duplicate events across chunk
    boundaries. Return shape is unchanged.
    """
    if not word_ids:
        return {}
    word_ids = list(dict.fromkeys(word_ids))
    grouped: dict[int, list[dict]] = {}
    for start in range(0, len(word_ids), 500):
        chunk = word_ids[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT word_id, grade, activity_type, created_at "
                f"FROM (SELECT id, word_id, grade, activity_type, created_at, "
                f"ROW_NUMBER() OVER (PARTITION BY word_id "
                f"ORDER BY created_at DESC, id DESC) AS rn "
                f"FROM review_events "
                f"WHERE user_id=? AND word_id IN ({placeholders})) "
                f"WHERE rn <= ? "
                f"ORDER BY word_id, created_at DESC, id DESC",
                (user_id, *chunk, per_word),
            ).fetchall()
        for row in rows:
            grouped.setdefault(row["word_id"], []).append(dict(row))
    return {wid: evs[:per_word] for wid, evs in grouped.items()}


def count_review_events_for_card(user_id: int, word_id: int) -> int:
    """Prior review count for one card (T3 live-card ordinal, read-only).

    Returns ``MAX(saved_words.total_reviews, COUNT(*))``: the lifetime
    counter stays exact after ``prune_old_review_events`` deletes old rows
    (rolled up monotonically beforehand), while the ``COUNT(*)`` side covers
    pre-counter rows that bypassed the insert-time bump (e.g. direct
    ``review_events`` inserts). Single short-lived connection, never opens a
    transaction. Missing table → 0 (fail-open for badge display only).
    """
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM review_events "
                "WHERE word_id=? AND user_id=?",
                (word_id, user_id),
            ).fetchone()
            cnt = int(row["cnt"]) if row else 0
            try:
                srow = conn.execute(
                    "SELECT COALESCE(total_reviews, 0) AS total "
                    "FROM saved_words WHERE id=? AND user_id=?",
                    (word_id, user_id),
                ).fetchone()
                stored = int(srow["total"]) if srow else 0
            except Exception:
                stored = 0
        return max(cnt, stored)
    except Exception:
        return 0


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
    (MAX(stored, actual lifetime)) for each affected card — a no-op when
    counters were already bumped alongside the insert (counters exact), and a
    heal when rows bypassed the counter bump. Counters are lifetime totals, so
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
