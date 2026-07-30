import json
import datetime
from services.db.schema import get_conn, _today, _utc_now

INTERVALS_DAYS = [1, 3, 7, 16, 30]


def _normalize_word(word: str) -> str:
    return " ".join(word.split()).casefold()


# ---------- کارت‌های روزانه (کش‌شده برای هر روز و هر کاربر) ----------

def get_daily_cards(user_id: int, card_date: str):
    """کارت‌های تولیدشده‌ی همان روز را به ترتیب برمی‌گرداند (لیست dict)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT card_data FROM daily_cards WHERE user_id=? AND card_date=? ORDER BY card_index",
            (user_id, card_date),
        ).fetchall()
    return [json.loads(r["card_data"]) for r in rows]


def get_recent_daily_words(
    user_id: int,
    target_lang: str | None = None,
    *,
    exclude_date: str | None = None,
    limit: int = 50,
) -> list[str]:
    query = (
        "SELECT d.card_data FROM daily_cards d"
        " LEFT JOIN daily_card_sessions s ON d.user_id = s.user_id AND d.card_date = s.card_date"
        " WHERE d.user_id=?"
    )
    params: list[object] = [user_id]
    if target_lang is not None:
        query += " AND (s.target_lang = ? OR s.target_lang IS NULL)"
        params.append(target_lang)
    if exclude_date is not None:
        query += " AND d.card_date<>?"
        params.append(exclude_date)
    query += " ORDER BY d.card_date DESC, d.card_index DESC LIMIT ?"
    params.append(limit)
    words: list[str] = []
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    for row in rows:
        try:
            data = json.loads(row["card_data"])
        except (TypeError, json.JSONDecodeError):
            continue
        word = data.get("word") if isinstance(data, dict) else None
        if isinstance(word, str) and word.strip():
            words.append(word.strip())
    return words


def get_recent_daily_card_dates(user_id: int, limit: int = 7):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT card_date FROM daily_cards WHERE user_id=? "
            "ORDER BY card_date DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [row["card_date"] for row in rows]


def count_daily_cards(user_id: int, card_date: str) -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM daily_cards WHERE user_id=? AND card_date=?",
            (user_id, card_date),
        ).fetchone()["c"]


def add_daily_card(user_id: int, card_date: str, card_index: int, card_data: dict, provenance: str = ""):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO daily_cards(user_id, card_date, card_index, card_data, provenance) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, card_date, card_index, json.dumps(card_data, ensure_ascii=False), provenance),
        )
        conn.commit()


def update_daily_card_fields(
    user_id: int,
    card_date: str,
    card_index: int,
    patch: dict,
) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT card_data FROM daily_cards "
            "WHERE user_id=? AND card_date=? AND card_index=?",
            (user_id, card_date, card_index),
        ).fetchone()
        if not row:
            return False
        try:
            card_data = json.loads(row["card_data"])
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(card_data, dict):
            return False
        card_data.update(patch)
        conn.execute(
            "UPDATE daily_cards SET card_data=? "
            "WHERE user_id=? AND card_date=? AND card_index=?",
            (
                json.dumps(card_data, ensure_ascii=False),
                user_id,
                card_date,
                card_index,
            ),
        )
        conn.commit()
        return True


def get_daily_progress(user_id: int, card_date: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT next_index FROM daily_progress WHERE user_id=? AND card_date=?",
            (user_id, card_date),
        ).fetchone()
    return row["next_index"] if row else 0


def set_daily_progress(user_id: int, card_date: str, next_index: int):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO daily_progress(user_id, card_date, next_index) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, card_date) DO UPDATE SET next_index=excluded.next_index",
            (user_id, card_date, next_index),
        )
        conn.commit()


def get_daily_card_session(user_id: int, card_date: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM daily_card_sessions WHERE user_id=? AND card_date=?",
            (user_id, card_date),
        ).fetchone()


def ensure_daily_card_session(
    user_id: int,
    card_date: str,
    target_lang: str,
    goal: str,
    level: str,
):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM daily_card_sessions WHERE user_id=? AND card_date=?",
            (user_id, card_date),
        ).fetchone()
        if row:
            conn.commit()
            return row
        conn.execute(
            "INSERT INTO daily_card_sessions(user_id, card_date, target_lang, goal, level, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, card_date, target_lang, goal, level, _utc_now().isoformat()),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM daily_card_sessions WHERE user_id=? AND card_date=?",
            (user_id, card_date),
        ).fetchone()


# ---------- واژه‌های دلخواه + یادآوری فاصله‌دار ساده ----------

def add_saved_word(
    user_id: int,
    word: str,
    lang: str,
    card_data: dict | None = None,
) -> bool:
    normalized_word = _normalize_word(word)
    if not normalized_word:
        return False
    word = " ".join(word.split())
    next_review = (_today() + datetime.timedelta(days=INTERVALS_DAYS[0])).isoformat()
    serialized_card = (
        json.dumps(card_data, ensure_ascii=False)
        if isinstance(card_data, dict)
        else None
    )
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "INSERT OR IGNORE INTO saved_words("
            "user_id, word, lang, normalized_word, card_data, interval_idx, "
            "next_review, review_status, added_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, 'idle', ?)",
            (
                user_id,
                word,
                lang,
                normalized_word,
                serialized_card,
                next_review,
                _utc_now().isoformat(),
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


def advance_word_review(word_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT interval_idx FROM saved_words WHERE id=?", (word_id,)).fetchone()
        if not row:
            return False
        idx = min((row["interval_idx"] or 0) + 1, len(INTERVALS_DAYS) - 1)
        next_review = (_today() + datetime.timedelta(days=INTERVALS_DAYS[idx])).isoformat()
        cursor = conn.execute(
            "UPDATE saved_words SET interval_idx=?, next_review=?, "
            "review_status='idle', review_requested_at=NULL "
            "WHERE id=? AND review_status='pending'",
            (idx, next_review, word_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def defer_word_review(word_id: int, days: int = 1) -> bool:
    next_review = (_today() + datetime.timedelta(days=max(days, 1))).isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE saved_words SET next_review=?, review_status='idle', "
            "review_requested_at=NULL WHERE id=? AND review_status='pending'",
            (next_review, word_id),
        )
        conn.commit()
        return cursor.rowcount == 1


# ---------- توابع جدید (پوسته) ----------

def get_pre_first_exposure_words(user_id):
    return []


def grade_word_review(word_id, grade, user_id):
    return True


def grade_first_exposure(word_id, grade, user_id):
    return True


def migrate_saved_words_to_fsrs():
    return True
