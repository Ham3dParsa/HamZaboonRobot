import json
import sqlite3
import datetime
from contextlib import contextmanager
from scheduling import planned_datetime

from config import (
    DB_PATH,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    DEFAULT_LEVEL,
    PLANS,
)

INTERVALS_DAYS = [1, 3, 7, 16, 30]


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
                UNIQUE(user_id, delivery_date, session_index)
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
        defaults = {
            "ai_base_url": DEFAULT_AI_BASE_URL,
            "ai_api_key": DEFAULT_AI_API_KEY,
            "ai_model": DEFAULT_AI_MODEL,
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
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
            (user_id, username, datetime.datetime.utcnow().isoformat()),
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
    today = datetime.date.today().isoformat()
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
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            new_streak = streak + 1 if last_date == yesterday else 1
        conn.execute(
            "UPDATE users SET streak=?, last_active_date=? WHERE user_id=?",
            (new_streak, today, user_id),
        )
        conn.commit()
        return new_streak


def can_ask_word(user_id: int, free_limit: int, bypass_limits: bool = False) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT plan, words_asked_today, words_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        if bypass_limits or row["plan"] != "free":
            return True
        today = datetime.date.today().isoformat()
        asked = row["words_asked_today"] or 0
        if row["words_asked_date"] != today:
            asked = 0
        return asked < free_limit


def increment_word_ask(user_id: int):
    today = datetime.date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT words_asked_today, words_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        asked = row["words_asked_today"] or 0
        if row["words_asked_date"] != today:
            asked = 0
        conn.execute(
            "UPDATE users SET words_asked_today=?, words_asked_date=? WHERE user_id=?",
            (asked + 1, today, user_id),
        )
        conn.commit()


def all_active_users():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE onboarded=1").fetchall()


def get_delivery_queue(delivery_date: str, statuses=("pending", "failed")):
    placeholders = ",".join("?" for _ in statuses)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM delivery_queue WHERE delivery_date=? AND status IN ({placeholders}) "
            "ORDER BY planned_for, id",
            (delivery_date, *statuses),
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
                    ),
                    key,
                ),
            )
        conn.commit()


def claim_delivery_queue(queue_id: int):
    now = datetime.datetime.utcnow().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "UPDATE delivery_queue SET status='processing', attempts=attempts+1, "
            "processing_started_at=? WHERE id=? AND status IN ('pending', 'failed')",
            (now, queue_id),
        )
        conn.commit()
        if row.rowcount != 1:
            return None
        return conn.execute("SELECT * FROM delivery_queue WHERE id=?", (queue_id,)).fetchone()


def mark_delivery_sent(queue_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue SET status='sent', sent_at=?, last_error=NULL WHERE id=?",
            (datetime.datetime.utcnow().isoformat(), queue_id),
        )
        conn.commit()


def advance_delivery_progress(queue_id: int, sent_count: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue SET sent_count=? WHERE id=? AND status='processing'",
            (sent_count, queue_id),
        )
        conn.commit()


def mark_delivery_failed(queue_id: int, error: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue SET status='failed', last_error=? WHERE id=?",
            (error[:1000], queue_id),
        )
        conn.commit()


def requeue_stale_deliveries(stale_before: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue SET status='failed', last_error='worker restarted' "
            "WHERE status='processing' AND processing_started_at<?",
            (stale_before,),
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

def add_saved_word(user_id: int, word: str, lang: str):
    next_review = (datetime.date.today() + datetime.timedelta(days=INTERVALS_DAYS[0])).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO saved_words(user_id, word, lang, interval_idx, next_review, added_at) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (user_id, word, lang, next_review, datetime.datetime.utcnow().isoformat()),
        )
        conn.commit()


def due_words_for_user(user_id: int):
    today = datetime.date.today().isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM saved_words WHERE user_id=? AND next_review<=?", (user_id, today)
        ).fetchall()


def advance_word_review(word_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT interval_idx FROM saved_words WHERE id=?", (word_id,)).fetchone()
        idx = min((row["interval_idx"] or 0) + 1, len(INTERVALS_DAYS) - 1)
        next_review = (datetime.date.today() + datetime.timedelta(days=INTERVALS_DAYS[idx])).isoformat()
        conn.execute(
            "UPDATE saved_words SET interval_idx=?, next_review=? WHERE id=?",
            (idx, next_review, word_id),
        )
        conn.commit()
