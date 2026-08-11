import json
import datetime
from services.db.schema import get_conn, _today, _utc_now


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


def grade_word_review(word_id, grade, user_id):
    return True


def grade_first_exposure(word_id, grade, user_id):
    return True
