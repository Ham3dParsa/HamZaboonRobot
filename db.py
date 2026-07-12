import json
import sqlite3
import datetime
import secrets
from contextlib import contextmanager
from zoneinfo import ZoneInfo
from scheduling import planned_datetime
from catalog import DEFAULT_LEVEL

from config import (
    DB_PATH,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    PLANS,
    APP_TIMEZONE,
)

INTERVALS_DAYS = [1, 3, 7, 16, 30]
_app_timezone = ZoneInfo(APP_TIMEZONE)


def _today() -> datetime.date:
    return datetime.datetime.now(_app_timezone).date()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _normalize_word(word: str) -> str:
    return " ".join(word.split()).casefold()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                target_lang TEXT,
                goal TEXT,
                level TEXT NOT NULL DEFAULT 'beginner',
                plan TEXT DEFAULT 'free',
                streak INTEGER DEFAULT 0,
                last_active_date TEXT,
                words_asked_today INTEGER DEFAULT 0,
                words_asked_date TEXT,
                optional_daily_limit INTEGER,
                preferred_delivery_minute INTEGER,
                active_window_start_minute INTEGER,
                active_window_end_minute INTEGER,
                onboarded INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS saved_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                word TEXT,
                lang TEXT,
                normalized_word TEXT,
                interval_idx INTEGER DEFAULT 0,
                next_review TEXT,
                added_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS daily_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_date TEXT,                -- تاریخ به فرمت YYYY-MM-DD
                card_index INTEGER,            -- شماره کارت در همان روز (از ۰ شروع)
                card_data TEXT,                -- محتوای JSON کارت
                UNIQUE(user_id, card_date, card_index)
            );
            CREATE TABLE IF NOT EXISTS daily_progress (
                user_id INTEGER,
                card_date TEXT,
                next_index INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, card_date)
            );
            CREATE TABLE IF NOT EXISTS delivery_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                delivery_date TEXT NOT NULL,
                session_index INTEGER NOT NULL,
                card_start_index INTEGER NOT NULL,
                card_count INTEGER NOT NULL,
                planned_for TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                idempotency_key TEXT NOT NULL UNIQUE,
                processing_started_at TEXT,
                sent_count INTEGER NOT NULL DEFAULT 0,
                sent_at TEXT,
                retry_at TEXT,
                UNIQUE(user_id, delivery_date, session_index)
            );
            CREATE TABLE IF NOT EXISTS query_results (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                query_text TEXT NOT NULL,
                word TEXT NOT NULL,
                lang TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                saved_at TEXT,
                saved_word_id INTEGER
            );
            """
        )
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "level" not in columns:
            conn.execute(
                f"ALTER TABLE users ADD COLUMN level TEXT NOT NULL DEFAULT "
                f"'{DEFAULT_LEVEL.replace(chr(39), chr(39) * 2)}'",
            )
        user_columns = {
            "optional_daily_limit": "INTEGER",
            "preferred_delivery_minute": "INTEGER",
            "active_window_start_minute": "INTEGER",
            "active_window_end_minute": "INTEGER",
        }
        for name, definition in user_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        delivery_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(delivery_queue)").fetchall()
        }
        if "sent_count" not in delivery_columns:
            conn.execute(
                "ALTER TABLE delivery_queue ADD COLUMN sent_count INTEGER NOT NULL DEFAULT 0"
            )
        if "retry_at" not in delivery_columns:
            conn.execute("ALTER TABLE delivery_queue ADD COLUMN retry_at TEXT")
        saved_word_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(saved_words)").fetchall()
        }
        if "normalized_word" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN normalized_word TEXT")
        conn.execute(
            "UPDATE saved_words SET normalized_word=lower(trim(word)) "
            "WHERE normalized_word IS NULL"
        )
        conn.execute(
            "DELETE FROM saved_words WHERE id NOT IN ("
            "SELECT MIN(id) FROM saved_words "
            "GROUP BY user_id, lang, normalized_word)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS saved_words_user_lang_word "
            "ON saved_words(user_id, lang, normalized_word)"
        )
        defaults = {
            "ai_base_url": DEFAULT_AI_BASE_URL,
            "ai_api_key": DEFAULT_AI_API_KEY,
            "ai_model": DEFAULT_AI_MODEL,
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        conn.execute(
            "DELETE FROM query_results WHERE expires_at<?",
            (_utc_now().isoformat(),),
        )
        conn.commit()


# ---------- settings (قابل تغییر توسط ادمین از داخل ربات) ----------

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


# ---------- users ----------

def get_user(user_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def create_user_if_needed(user_id: int, username: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, username, created_at) VALUES (?, ?, ?)",
            (user_id, username, _utc_now().isoformat()),
        )
        conn.commit()


def set_user_lang_goal(user_id: int, lang: str, goal: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET target_lang=?, goal=? WHERE user_id=?",
            (lang, goal, user_id),
        )
        conn.commit()


def set_user_level(user_id: int, level: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET level=?, onboarded=1 WHERE user_id=?",
            (level, user_id),
        )
        conn.commit()


def set_user_lang(user_id: int, lang: str):
    """تغییر فقط زبان"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET target_lang=? WHERE user_id=?",
            (lang, user_id),
        )
        conn.commit()


def set_user_goal(user_id: int, goal: str):
    """تغییر فقط هدف"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET goal=? WHERE user_id=?",
            (goal, user_id),
        )
        conn.commit()


def touch_streak(user_id: int) -> int:
    today = _today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT streak, last_active_date FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            return 0
        streak, last_date = row["streak"] or 0, row["last_active_date"]
        if last_date == today:
            new_streak = streak
        else:
            yesterday = (_today() - datetime.timedelta(days=1)).isoformat()
            new_streak = streak + 1 if last_date == yesterday else 1
        conn.execute(
            "UPDATE users SET streak=?, last_active_date=? WHERE user_id=?",
            (new_streak, today, user_id),
        )
        conn.commit()
        return new_streak


def can_ask_word(user_id: int, daily_limit: int, bypass_limits: bool = False) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT plan, words_asked_today, words_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        if bypass_limits or daily_limit < 0:
            return True
        today = _today().isoformat()
        asked = row["words_asked_today"] or 0
        if row["words_asked_date"] != today:
            asked = 0
        return asked < daily_limit


def reserve_word_query(user_id: int, daily_limit: int, bypass_limits: bool = False) -> bool:
    today = _today().isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT words_asked_today, words_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        asked = row["words_asked_today"] or 0
        if row["words_asked_date"] != today:
            asked = 0
        if not bypass_limits and daily_limit >= 0 and asked >= daily_limit:
            return False
        conn.execute(
            "UPDATE users SET words_asked_today=?, words_asked_date=? WHERE user_id=?",
            (asked + 1, today, user_id),
        )
        conn.commit()
        return True


def _query_result_expired(row) -> bool:
    return row is not None and row["expires_at"] <= _utc_now().isoformat()


def create_query_result(
    user_id: int,
    query_text: str,
    word: str,
    lang: str,
    result_data: dict,
    ttl_seconds: int = 24 * 60 * 60,
) -> str:
    token = secrets.token_hex(16)
    now = _utc_now()
    expires_at = now + datetime.timedelta(seconds=ttl_seconds)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO query_results("
            "token, user_id, query_text, word, lang, result_json, created_at, expires_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                user_id,
                " ".join(query_text.split()),
                " ".join(word.split()),
                lang,
                json.dumps(result_data, ensure_ascii=False),
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
    return token


def get_query_result(token: str, user_id: int | None = None, include_expired: bool = False):
    with get_conn() as conn:
        params = [token]
        query = "SELECT * FROM query_results WHERE token=?"
        if user_id is not None:
            query += " AND user_id=?"
            params.append(user_id)
        row = conn.execute(query, params).fetchone()
    if row and not include_expired and _query_result_expired(row):
        return None
    return row


def mark_query_result_saved(token: str, saved_word_id: int | None = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE query_results SET saved_at=COALESCE(saved_at, ?), "
            "saved_word_id=COALESCE(saved_word_id, ?) WHERE token=?",
            (_utc_now().isoformat(), saved_word_id, token),
        )
        conn.commit()


def cleanup_expired_query_results():
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM query_results WHERE expires_at<?",
            (_utc_now().isoformat(),),
        )
        conn.commit()


def all_active_users():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE onboarded=1").fetchall()


def get_delivery_queue(
    delivery_date: str,
    statuses=("pending", "failed"),
    now: str | None = None,
):
    placeholders = ",".join("?" for _ in statuses)
    now = now or _utc_now().isoformat()
    retry_filter = " AND (status='pending' OR (status='failed' AND retry_at IS NOT NULL AND retry_at<=?))"
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM delivery_queue WHERE delivery_date=? AND status IN ({placeholders}) "
            f"{retry_filter} ORDER BY planned_for, id",
            (delivery_date, *statuses, now),
        ).fetchall()


def delivery_queue_for_user(user_id: int, delivery_date: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM delivery_queue WHERE user_id=? AND delivery_date=? ORDER BY session_index",
            (user_id, delivery_date),
        ).fetchall()


def enqueue_delivery_sessions(user_id: int, delivery_date: str, sessions):
    with get_conn() as conn:
        for session in sessions:
            key = f"{user_id}:{delivery_date}:{session.session_index}"
            conn.execute(
                "INSERT OR IGNORE INTO delivery_queue("
                "user_id, delivery_date, session_index, card_start_index, card_count, "
                "planned_for, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    delivery_date,
                    session.session_index,
                    sum(item.card_count for item in sessions[:session.session_index]),
                    session.card_count,
                    planned_datetime(
                        datetime.date.fromisoformat(delivery_date),
                        session.planned_minute,
                        APP_TIMEZONE,
                    ),
                    key,
                ),
            )
        conn.commit()


def claim_delivery_queue(queue_id: int):
    now = _utc_now().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "UPDATE delivery_queue SET status='processing', attempts=attempts+1, "
            "processing_started_at=?, retry_at=NULL "
            "WHERE id=? AND (status='pending' OR "
            "(status='failed' AND retry_at IS NOT NULL AND retry_at<=?))",
            (now, queue_id, now),
        )
        conn.commit()
        if row.rowcount != 1:
            return None
        return conn.execute("SELECT * FROM delivery_queue WHERE id=?", (queue_id,)).fetchone()


def mark_delivery_sent(queue_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue SET status='sent', sent_at=?, last_error=NULL WHERE id=?",
            (_utc_now().isoformat(), queue_id),
        )
        conn.commit()


def advance_delivery_progress(queue_id: int, sent_count: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue SET sent_count=? WHERE id=? AND status='processing'",
            (sent_count, queue_id),
        )
        conn.commit()


def mark_delivery_failed(
    queue_id: int,
    error: str,
    retry_at: str | None = None,
    *,
    terminal: bool = False,
):
    if retry_at is None and not terminal:
        retry_at = _utc_now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue SET status='failed', last_error=?, retry_at=? WHERE id=?",
            (error[:1000], retry_at, queue_id),
        )
        conn.commit()


def requeue_stale_deliveries(stale_before: str, max_attempts: int = 5):
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue SET status='failed', last_error='worker restarted', "
            "retry_at=CASE WHEN attempts<? THEN ? ELSE NULL END "
            "WHERE status='processing' AND processing_started_at<?",
            (max_attempts, _utc_now().isoformat(), stale_before),
        )
        conn.commit()


def count_users():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def set_plan(user_id: int, plan: str):
    if plan not in PLANS:
        raise ValueError(f"Unknown plan: {plan}")
    with get_conn() as conn:
        conn.execute("UPDATE users SET plan=? WHERE user_id=?", (plan, user_id))
        conn.commit()


def find_user(identifier: str):
    identifier = identifier.strip()
    if identifier.startswith("@"):
        identifier = identifier[1:]
    if identifier.isdigit():
        return get_user(int(identifier))
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (identifier,),
        ).fetchone()


# ---------- کارت‌های روزانه (کش‌شده برای هر روز و هر کاربر) ----------

def get_daily_cards(user_id: int, card_date: str):
    """کارت‌های تولیدشده‌ی همان روز را به ترتیب برمی‌گرداند (لیست dict)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT card_data FROM daily_cards WHERE user_id=? AND card_date=? ORDER BY card_index",
            (user_id, card_date),
        ).fetchall()
    return [json.loads(r["card_data"]) for r in rows]


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


def add_daily_card(user_id: int, card_date: str, card_index: int, card_data: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO daily_cards(user_id, card_date, card_index, card_data) "
            "VALUES (?, ?, ?, ?)",
            (user_id, card_date, card_index, json.dumps(card_data, ensure_ascii=False)),
        )
        conn.commit()


def get_daily_progress(user_id: int, card_date: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT next_index FROM daily_progress WHERE user_id=? AND card_date=?",
            (user_id, card_date),
        ).fetchone()
    return row["next_index"] if row else 0


def set_daily_progress(user_id: int, card_date: str, next_index: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO daily_progress(user_id, card_date, next_index) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, card_date) DO UPDATE SET next_index=excluded.next_index",
            (user_id, card_date, next_index),
        )
        conn.commit()


# ---------- واژه‌های دلخواه + یادآوری فاصله‌دار ساده ----------

def add_saved_word(user_id: int, word: str, lang: str) -> bool:
    normalized_word = _normalize_word(word)
    if not normalized_word:
        return False
    word = " ".join(word.split())
    next_review = (_today() + datetime.timedelta(days=INTERVALS_DAYS[0])).isoformat()
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO saved_words("
            "user_id, word, lang, normalized_word, interval_idx, next_review, added_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (user_id, word, lang, normalized_word, next_review, _utc_now().isoformat()),
        )
        conn.commit()
        return cursor.rowcount == 1


def due_words_for_user(user_id: int):
    today = _today().isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM saved_words WHERE user_id=? AND next_review<=?", (user_id, today)
        ).fetchall()


def advance_word_review(word_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT interval_idx FROM saved_words WHERE id=?", (word_id,)).fetchone()
        idx = min((row["interval_idx"] or 0) + 1, len(INTERVALS_DAYS) - 1)
        next_review = (_today() + datetime.timedelta(days=INTERVALS_DAYS[idx])).isoformat()
        conn.execute(
            "UPDATE saved_words SET interval_idx=?, next_review=? WHERE id=?",
            (idx, next_review, word_id),
        )
        conn.commit()
