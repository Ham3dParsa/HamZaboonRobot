import json
import datetime
from dataclasses import dataclass
from services.db.schema import get_conn, _today, _utc_now, _app_timezone
from services.fsrs_core import (
    DEFAULT_FSRS_CONFIG,
    compute_interval,
    compute_retrievability,
    initial_difficulty,
    initial_stability_first_exposure,
    short_term_stability,
    update_difficulty,
    update_stability,
)


def _normalize_word(word: str) -> str:
    return " ".join(word.split()).casefold()


# ---------- واژه‌های دلخواه + یادآوری فاصله‌دار ساده ----------

def add_saved_word(
    user_id: int,
    word: str,
    lang: str,
    card_data: dict | None = None,
    entry_source: str = "manual",
) -> bool:
    normalized_word = _normalize_word(word)
    if not normalized_word:
        return False
    word = " ".join(word.split())
    next_review = (_today() + datetime.timedelta(days=1)).isoformat()
    serialized_card = (
        json.dumps(card_data, ensure_ascii=False)
        if isinstance(card_data, dict)
        else None
    )
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "INSERT OR IGNORE INTO saved_words("
            "user_id, word, lang, normalized_word, card_data, "
            "next_review, review_status, added_at, "
            "first_exposure_done, stability, difficulty, entry_source) "
            "VALUES (?, ?, ?, ?, ?, ?, 'idle', ?, 0, 0.0, 5.0, ?)",
            (
                user_id,
                word,
                lang,
                normalized_word,
                serialized_card,
                next_review,
                _utc_now().isoformat(),
                entry_source,
            ),
        )
        if cursor.rowcount == 0 and serialized_card is not None:
            conn.execute(
                "UPDATE saved_words SET card_data=COALESCE(card_data, ?) "
                "WHERE user_id=? AND lang=? AND normalized_word=?",
                (serialized_card, user_id, lang, normalized_word),
            )
        conn.commit()
        return cursor.rowcount == 1


def toggle_review_word(
    user_id: int,
    word: str,
    lang: str,
    card_data: dict | None = None,
    entry_source: str = "manual",
) -> str:
    """Idempotently add a saved word if absent, or remove it if present.

    Returns ``"saved"`` when a row was added and ``"removed"`` when an existing
    row was deleted. The unique key is (user_id, lang, normalized_word), so
    rapid repeated taps cannot produce duplicates.
    """
    normalized_word = _normalize_word(word)
    if not normalized_word:
        return "removed"
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT id FROM saved_words "
            "WHERE user_id=? AND lang=? AND normalized_word=?",
            (user_id, lang, normalized_word),
        ).fetchone()
        if existing is not None:
            conn.execute("DELETE FROM saved_words WHERE id=?", (existing["id"],))
            conn.commit()
            return "removed"

        clean_word = " ".join(word.split())
        next_review = (_today() + datetime.timedelta(days=1)).isoformat()
        serialized_card = (
            json.dumps(card_data, ensure_ascii=False)
            if isinstance(card_data, dict)
            else None
        )
        conn.execute(
            "INSERT OR IGNORE INTO saved_words("
            "user_id, word, lang, normalized_word, card_data, "
            "next_review, review_status, added_at, "
            "first_exposure_done, stability, difficulty, entry_source) "
            "VALUES (?, ?, ?, ?, ?, ?, 'idle', ?, 0, 0.0, 5.0, ?)",
            (
                user_id,
                clean_word,
                lang,
                normalized_word,
                serialized_card,
                next_review,
                _utc_now().isoformat(),
                entry_source,
            ),
        )
        conn.commit()
        return "saved"


def update_saved_word_fields(
    word_id: int,
    user_id: int,
    patch: dict,
) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT word, card_data FROM saved_words WHERE id=? AND user_id=?",
            (word_id, user_id),
        ).fetchone()
        if not row:
            return False
        if row["card_data"]:
            try:
                card_data = json.loads(row["card_data"])
            except (TypeError, json.JSONDecodeError):
                return False
            if not isinstance(card_data, dict):
                return False
        else:
            card_data = {"word": row["word"]}
        card_data.update(patch)
        conn.execute(
            "UPDATE saved_words SET card_data=? WHERE id=? AND user_id=?",
            (
                json.dumps(card_data, ensure_ascii=False),
                word_id,
                user_id,
            ),
        )
        conn.commit()
        return True


def due_words_for_user(user_id: int):
    today = _today().isoformat()
    grace_deadline = (
        _utc_now() - datetime.timedelta(hours=48)
    ).isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE saved_words SET review_status='idle', review_requested_at=NULL "
            "WHERE user_id=? AND review_status='pending' "
            "AND review_requested_at IS NOT NULL AND review_requested_at<=?",
            (user_id, grace_deadline),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM saved_words WHERE user_id=? AND next_review<=? "
            "AND COALESCE(first_exposure_done, 0)=1 "
            "AND COALESCE(review_status, 'idle')!='pending' "
            "AND retry_at IS NULL "
            "ORDER BY (julianday('now') - julianday(next_review)) DESC",
            (user_id, today),
        ).fetchall()


def get_saved_word(word_id: int, user_id: int | None = None):
    query = "SELECT * FROM saved_words WHERE id=?"
    params: list[object] = [word_id]
    if user_id is not None:
        query += " AND user_id=?"
        params.append(user_id)
    with get_conn() as conn:
        return conn.execute(query, params).fetchone()


# ---------- توابع جدید (پوسته) ----------

def get_pre_first_exposure_words(user_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM saved_words WHERE user_id=? AND first_exposure_done=0 "
            "ORDER BY added_at ASC",
            (user_id,),
        ).fetchall()


@dataclass(frozen=True)
class GradeResult:
    ok: bool
    reason: str = ""
    next_review_at: datetime.datetime | None = None
    interval_seconds: int | None = None


def _validate_grade(grade: int) -> None:
    if grade not in (1, 2, 3, 4):
        raise ValueError(f"invalid grade: {grade!r}")


def _parse_utc(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


def _schedule(stability: float, now: datetime.datetime):
    interval_days = compute_interval(stability, config=DEFAULT_FSRS_CONFIG)
    if interval_days < 1.0:
        next_review_at = now + datetime.timedelta(days=interval_days)
        interval_seconds = int(interval_days * 86400)
    else:
        interval_days = max(1, round(interval_days))
        next_review_at = now + datetime.timedelta(days=interval_days)
        interval_seconds = int(interval_days * 86400)
    return next_review_at, interval_seconds


def _apply_scheduling_fields(
    conn,
    word_id: int,
    user_id: int,
    stability: float,
    difficulty: float,
    now,
    next_review_at,
    next_review: str,
    first_exposure_done: int | None = None,
) -> None:
    if first_exposure_done is not None:
        conn.execute(
            "UPDATE saved_words SET "
            "first_exposure_done=?, last_review_at=?, next_review_at=?, next_review=?, "
            "stability=?, difficulty=?, "
            "review_status='idle', review_requested_at=NULL, retry_at=NULL, "
            "srs_retry_attempts=0 "
            "WHERE id=? AND user_id=?",
            (
                first_exposure_done,
                now.isoformat(),
                next_review_at.isoformat(),
                next_review,
                stability,
                difficulty,
                word_id,
                user_id,
            ),
        )
    else:
        conn.execute(
            "UPDATE saved_words SET "
            "last_review_at=?, next_review_at=?, next_review=?, "
            "stability=?, difficulty=?, "
            "review_status='idle', review_requested_at=NULL, retry_at=NULL, "
            "srs_retry_attempts=0 "
            "WHERE id=? AND user_id=?",
            (
                now.isoformat(),
                next_review_at.isoformat(),
                next_review,
                stability,
                difficulty,
                word_id,
                user_id,
            ),
        )


def grade_word_review(word_id, grade, user_id):
    """Deep, atomic regular-review transition.

    Enforces ``(word_id, user_id)`` ownership inside the same immediate
    transaction that reads and updates scheduling state. Never partially
    mutates the row on expected failure. Does not write ``review_events``
    (telemetry wiring lives in Phase 05 handler integration).
    """
    _validate_grade(grade)
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM saved_words WHERE id=? AND user_id=?",
            (word_id, user_id),
        ).fetchone()
        if row is None:
            conn.rollback()
            return GradeResult(ok=False, reason="not_found")
        if not row["first_exposure_done"] or not row["last_review_at"]:
            conn.rollback()
            return GradeResult(ok=False, reason="wrong_state")

        now = _utc_now()
        s_old = row["stability"] or 0.1
        d_old = row["difficulty"] or 5.0
        last_review = _parse_utc(row["last_review_at"])
        elapsed_days = (now - last_review).total_seconds() / 86400

        d_new = update_difficulty(d_old, grade)
        if elapsed_days < 1:
            s_new = short_term_stability(s_old, grade)
        else:
            r = compute_retrievability(elapsed_days, s_old)
            s_new = update_stability(d_old, s_old, r, grade)

        next_review_at, interval_seconds = _schedule(s_new, now)
        next_review = next_review_at.astimezone(_app_timezone).date().isoformat()
        _apply_scheduling_fields(
            conn, word_id, user_id, s_new, d_new, now, next_review_at, next_review
        )
        conn.commit()
        return GradeResult(
            ok=True,
            next_review_at=next_review_at,
            interval_seconds=interval_seconds,
        )


def grade_first_exposure(word_id, grade, user_id):
    """Deep, atomic first-exposure transition.

    Precondition: ``first_exposure_done = 0``. Familiarity-based stability
    seeds the schedule. Ownership + state guards run inside the same immediate
    transaction as the update, so expected failures never partially mutate.
    """
    _validate_grade(grade)
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM saved_words WHERE id=? AND user_id=?",
            (word_id, user_id),
        ).fetchone()
        if row is None:
            conn.rollback()
            return GradeResult(ok=False, reason="not_found")
        if row["first_exposure_done"]:
            conn.rollback()
            return GradeResult(ok=False, reason="wrong_state")

        now = _utc_now()
        s = initial_stability_first_exposure(grade)
        d = initial_difficulty(grade)
        next_review_at, interval_seconds = _schedule(s, now)
        next_review = next_review_at.astimezone(_app_timezone).date().isoformat()
        _apply_scheduling_fields(
            conn, word_id, user_id, s, d, now, next_review_at, next_review,
            first_exposure_done=1,
        )
        conn.commit()
        return GradeResult(
            ok=True,
            next_review_at=next_review_at,
            interval_seconds=interval_seconds,
        )
