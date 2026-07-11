import json
import sqlite3
import datetime
from contextlib import contextmanager

from config import (
    DB_PATH,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    DEFAULT_LEVEL,
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


def can_ask_word(user_id: int, free_limit: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT plan, words_asked_today, words_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        if row["plan"] != "free":
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


def count_users():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def set_plan(user_id: int, plan: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET plan=? WHERE user_id=?", (plan, user_id))
        conn.commit()


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
