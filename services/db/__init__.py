import json
import sqlite3
import datetime
import secrets
from contextlib import contextmanager
from zoneinfo import ZoneInfo
from services.scheduling import planned_datetime
from config.catalog import DEFAULT_LEVEL

from config import (
    DB_PATH,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    DEFAULT_PHONETIC_SHOW_IPA,
    DEFAULT_PHONETIC_SHOW_PERSIAN,
    FREE_DAILY_CARD_LIMIT,
    SILVER_DAILY_CARD_LIMIT,
    GOLD_DAILY_CARD_LIMIT,
    LLM_INPUT_COST_USD_PER_MILLION,
    LLM_OUTPUT_COST_USD_PER_MILLION,
    PLANS,
    APP_TIMEZONE,
    USD_TO_TOMAN_RATE,
)

INTERVALS_DAYS = [1, 3, 7, 16, 30]
_app_timezone = ZoneInfo(APP_TIMEZONE)
def _today() -> datetime.date:
    return datetime.datetime.now(_app_timezone).date()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _normalize_word(word: str) -> str:
    return " ".join(word.split()).casefold()


def _current_daily_count(asked_value, asked_date) -> int:
    today = _today().isoformat()
    if asked_date != today:
        return 0
    return asked_value or 0


def _can_consume_daily_count(
    asked_value,
    asked_date,
    daily_limit: int,
    *,
    bypass_limits: bool = False,
) -> bool:
    if bypass_limits or daily_limit < 0:
        return True
    return _current_daily_count(asked_value, asked_date) < daily_limit


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
                grammar_tips_asked_today INTEGER DEFAULT 0,
                grammar_tips_asked_date TEXT,
                optional_daily_limit INTEGER,
                preferred_delivery_minute INTEGER,
                active_window_start_minute INTEGER,
                active_window_end_minute INTEGER,
                presentation_preference TEXT,
                onboarded INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS saved_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                word TEXT,
                lang TEXT,
                normalized_word TEXT,
                card_data TEXT,
                interval_idx INTEGER DEFAULT 0,
                next_review TEXT,
                review_status TEXT DEFAULT 'idle',
                review_requested_at TEXT,
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
                card_index INTEGER,            -- card index for that day (0-based)
                card_data TEXT,                -- محتوای JSON کارت
                UNIQUE(user_id, card_date, card_index)
            );
            CREATE TABLE IF NOT EXISTS daily_progress (
                user_id INTEGER,
                card_date TEXT,
                next_index INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, card_date)
            );
            CREATE TABLE IF NOT EXISTS daily_card_sessions (
                user_id INTEGER,
                card_date TEXT,
                target_lang TEXT,
                goal TEXT,
                level TEXT,
                created_at TEXT,
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
            CREATE TABLE IF NOT EXISTS grammar_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tip_date TEXT NOT NULL,
                title TEXT NOT NULL,
                lang TEXT NOT NULL,
                goal TEXT NOT NULL,
                level TEXT NOT NULL,
                tip_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS llm_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                request_date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                plan TEXT NOT NULL,
                request_kind TEXT NOT NULL,
                model TEXT NOT NULL,
                outcome TEXT NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                input_cost_usd_per_million REAL NOT NULL,
                output_cost_usd_per_million REAL NOT NULL,
                usd_to_toman_rate REAL NOT NULL,
                cost_usd REAL NOT NULL,
                cost_toman REAL NOT NULL,
                latency_ms INTEGER,
                error_class TEXT,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS review_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                revealed_before_answer INTEGER NOT NULL DEFAULT 0,
                outcome TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_presets (
                name TEXT PRIMARY KEY,
                base_url TEXT,
                model TEXT,
                api_key TEXT NOT NULL DEFAULT '',
                daily_batch_size INTEGER DEFAULT 6,
                max_concurrency INTEGER DEFAULT 2,
                max_rpm INTEGER DEFAULT 30,
                max_tpm INTEGER DEFAULT 0,
                max_daily_req INTEGER DEFAULT 0,
                timeout_seconds REAL DEFAULT 30.0,
                temperature REAL DEFAULT 0.6,
                max_output_tokens INTEGER DEFAULT 4096,
                is_custom INTEGER DEFAULT 0,
                priority INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                is_emergency INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS preset_hourly_usage (
                preset_name TEXT NOT NULL,
                hour_bucket TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                token_count INTEGER DEFAULT 0,
                PRIMARY KEY (preset_name, hour_bucket)
            );
            CREATE TABLE IF NOT EXISTS config_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_type TEXT,
                preset_name TEXT,
                prompt TEXT,
                result TEXT,
                created_at TEXT
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
            "grammar_tips_asked_today": "INTEGER DEFAULT 0",
            "grammar_tips_asked_date": "TEXT",
            "presentation_preference": "TEXT",
        }
        for name, definition in user_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        if "daily_reminder_cap" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN daily_reminder_cap INTEGER")
        if "reminder_cap_updated_at" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN reminder_cap_updated_at TEXT")
        conn.execute(
            "UPDATE users SET daily_reminder_cap = CASE plan "
            "WHEN 'silver' THEN ? WHEN 'gold' THEN ? ELSE ? END "
            "WHERE daily_reminder_cap IS NULL",
            (SILVER_DAILY_CARD_LIMIT, GOLD_DAILY_CARD_LIMIT, FREE_DAILY_CARD_LIMIT),
        )
        conn.commit()
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
        session_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(daily_card_sessions)").fetchall()
        }
        if session_columns and "target_lang" not in session_columns:
            conn.execute("ALTER TABLE daily_card_sessions ADD COLUMN target_lang TEXT")
        if session_columns and "goal" not in session_columns:
            conn.execute("ALTER TABLE daily_card_sessions ADD COLUMN goal TEXT")
        if session_columns and "level" not in session_columns:
            conn.execute("ALTER TABLE daily_card_sessions ADD COLUMN level TEXT")
        if session_columns and "created_at" not in session_columns:
            conn.execute("ALTER TABLE daily_card_sessions ADD COLUMN created_at TEXT")
        saved_word_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(saved_words)").fetchall()
        }
        if "normalized_word" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN normalized_word TEXT")
        if "card_data" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN card_data TEXT")
        if "review_status" not in saved_word_columns:
            conn.execute(
                "ALTER TABLE saved_words ADD COLUMN review_status TEXT DEFAULT 'idle'"
            )
        if "review_requested_at" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN review_requested_at TEXT")
        if "retry_at" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN retry_at TEXT")
        if "srs_retry_attempts" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN srs_retry_attempts INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "UPDATE saved_words SET normalized_word=lower(trim(word)) "
            "WHERE normalized_word IS NULL"
        )
        conn.execute(
            "UPDATE saved_words SET review_status='idle' "
            "WHERE review_status IS NULL"
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
            "llm_input_cost_usd_per_million": str(LLM_INPUT_COST_USD_PER_MILLION),
            "llm_output_cost_usd_per_million": str(LLM_OUTPUT_COST_USD_PER_MILLION),
            "usd_to_toman_rate": str(USD_TO_TOMAN_RATE),
            "phonetic_show_ipa": "true" if DEFAULT_PHONETIC_SHOW_IPA else "false",
            "phonetic_show_persian": "true" if DEFAULT_PHONETIC_SHOW_PERSIAN else "false",
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        for tbl, col, col_def in (
            ("daily_cards", "provenance", "TEXT DEFAULT ''"),
            ("grammar_tips", "provenance", "TEXT DEFAULT ''"),
        ):
            existing = {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({tbl})").fetchall()
            }
            if col not in existing:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}")

        # Initialize ai_presets table with built-in presets
        _init_ai_presets_table(conn)

        # Initialize config_tests table for audit logging
        _init_config_tests_table(conn)

        # Initialize fallback-related settings
        fallback_defaults = {
            "ai_fallback_active": "false",
            "ai_fallback_since": "",
            "ai_consecutive_failures": "0",
            "auto_backup_enabled": "true",
        }
        for k, v in fallback_defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        existing_primary = conn.execute("SELECT value FROM settings WHERE key='ai_primary_preset'").fetchone()
        if not existing_primary:
            first = conn.execute(
                "SELECT name FROM ai_presets WHERE enabled=1 AND is_emergency=0 ORDER BY priority ASC, name ASC LIMIT 1"
            ).fetchone()
            if first:
                conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('ai_primary_preset', ?)", (first["name"],))
        existing_fallback = conn.execute("SELECT value FROM settings WHERE key='ai_fallback_preset'").fetchone()
        if not existing_fallback:
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('ai_fallback_preset', 'gapgpt_gemini_lite')")

        llm_request_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(llm_requests)").fetchall()
        }
        if llm_request_columns:
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS llm_requests_request_date_idx ON llm_requests(request_date)",
                "CREATE INDEX IF NOT EXISTS llm_requests_user_id_idx ON llm_requests(user_id)",
                "CREATE INDEX IF NOT EXISTS llm_requests_plan_idx ON llm_requests(plan)",
                "CREATE INDEX IF NOT EXISTS llm_requests_model_idx ON llm_requests(model)",
                "CREATE INDEX IF NOT EXISTS llm_requests_kind_idx ON llm_requests(request_kind)",
                "CREATE INDEX IF NOT EXISTS llm_requests_outcome_idx ON llm_requests(outcome)",
            ):
                conn.execute(index_sql)
        conn.execute(
            "DELETE FROM query_results WHERE expires_at<?",
            (_utc_now().isoformat(),),
        )

        # Reconcile preset system with legacy settings
        legacy_url = conn.execute(
            "SELECT value FROM settings WHERE key='ai_base_url'"
        ).fetchone()
        active_name = conn.execute(
            "SELECT value FROM settings WHERE key='ai_primary_preset'"
        ).fetchone()
        if legacy_url and active_name:
            legacy_url_val = legacy_url["value"]
            active_name_val = active_name["value"]
            if legacy_url_val:
                preset_row = conn.execute(
                    "SELECT base_url, model FROM ai_presets WHERE name=?",
                    (active_name_val,),
                ).fetchone()
                if preset_row and preset_row["base_url"] != legacy_url_val:
                    model_val = conn.execute(
                        "SELECT value FROM settings WHERE key='ai_model'"
                    ).fetchone()
                    conn.execute(
                        "UPDATE ai_presets SET base_url=?, model=? WHERE name=?",
                        (legacy_url_val, (model_val["value"] if model_val else ""), active_name_val),
                    )
                    conn.execute(
                        "INSERT INTO settings(key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        ("_migration_preset_synced", legacy_url_val),
                    )
            # Migrate legacy api_key to active preset's api_key if preset has none
            preset_api = conn.execute(
                "SELECT api_key FROM ai_presets WHERE name=?",
                (active_name_val,),
            ).fetchone()
            if preset_api and not preset_api["api_key"]:
                legacy_api_key = conn.execute(
                    "SELECT value FROM settings WHERE key='ai_api_key'"
                ).fetchone()
                if legacy_api_key and legacy_api_key["value"]:
                    conn.execute(
                        "UPDATE ai_presets SET api_key=? WHERE name=?",
                        (legacy_api_key["value"], active_name_val),
                    )

        conn.commit()


# ---------- settings (قابل تغییر توسط ادمین از داخل ربات) ----------

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


def get_bool_setting(key: str, default: bool = False) -> bool:
    return get_setting(key, "true" if default else "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def set_bool_setting(key: str, value: bool):
    set_setting(key, "true" if value else "false")


def get_phonetic_display_settings() -> dict[str, bool]:
    return {
        "ipa": get_bool_setting("phonetic_show_ipa", DEFAULT_PHONETIC_SHOW_IPA),
        "persian": get_bool_setting("phonetic_show_persian", DEFAULT_PHONETIC_SHOW_PERSIAN),
    }


def get_llm_cost_profile() -> dict[str, float]:
    return {
        "input_cost_usd_per_million": float(
            get_setting("llm_input_cost_usd_per_million", str(LLM_INPUT_COST_USD_PER_MILLION))
        ),
        "output_cost_usd_per_million": float(
            get_setting("llm_output_cost_usd_per_million", str(LLM_OUTPUT_COST_USD_PER_MILLION))
        ),
        "usd_to_toman_rate": float(get_setting("usd_to_toman_rate", str(USD_TO_TOMAN_RATE))),
    }


def set_llm_cost_profile(
    *,
    input_cost_usd_per_million: float,
    output_cost_usd_per_million: float,
    usd_to_toman_rate: float,
):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("llm_input_cost_usd_per_million", str(input_cost_usd_per_million)),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("llm_output_cost_usd_per_million", str(output_cost_usd_per_million)),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("usd_to_toman_rate", str(usd_to_toman_rate)),
        )
        conn.commit()


# ---------- users ----------

def get_user(user_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def create_user_if_needed(user_id: int, username: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, username, created_at) VALUES (?, ?, ?)",
            (user_id, username, _utc_now().isoformat()),
        )
        conn.commit()


def set_user_lang_goal(user_id: int, lang: str, goal: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET target_lang=?, goal=? WHERE user_id=?",
            (lang, goal, user_id),
        )
        conn.commit()


def set_user_level(user_id: int, level: str):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET level=?, onboarded=1 WHERE user_id=?",
            (level, user_id),
        )
        conn.commit()


def set_presentation_preference(user_id: int, preference: str):
    if preference not in {"brief", "detailed"}:
        raise ValueError(f"Unknown presentation preference: {preference}")
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET presentation_preference=? WHERE user_id=?",
            (preference, user_id),
        )
        conn.commit()


def set_user_lang(user_id: int, lang: str):
    """تغییر فقط زبان"""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET target_lang=? WHERE user_id=?",
            (lang, user_id),
        )
        conn.commit()


def set_user_goal(user_id: int, goal: str):
    """تغییر فقط هدف"""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET goal=? WHERE user_id=?",
            (goal, user_id),
        )
        conn.commit()


def touch_streak(user_id: int) -> int:
    today = _today().isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
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
        return _can_consume_daily_count(
            row["words_asked_today"],
            row["words_asked_date"],
            daily_limit,
            bypass_limits=bypass_limits,
        )


def reserve_word_query(user_id: int, daily_limit: int, bypass_limits: bool = False) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT words_asked_today, words_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        asked = _current_daily_count(row["words_asked_today"], row["words_asked_date"])
        if not bypass_limits and daily_limit >= 0 and asked >= daily_limit:
            return False
        today = _today().isoformat()
        conn.execute(
            "UPDATE users SET words_asked_today=?, words_asked_date=? WHERE user_id=?",
            (asked + 1, today, user_id),
        )
        conn.commit()
        return True


def release_word_query(user_id: int):
    today = _today().isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET words_asked_today=MAX(words_asked_today - 1, 0) "
            "WHERE user_id=? AND words_asked_date=?",
            (user_id, today),
        )
        conn.commit()


def can_ask_grammar_tip(user_id: int, daily_limit: int, bypass_limits: bool = False) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT grammar_tips_asked_today, grammar_tips_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        return _can_consume_daily_count(
            row["grammar_tips_asked_today"],
            row["grammar_tips_asked_date"],
            daily_limit,
            bypass_limits=bypass_limits,
        )


def reserve_grammar_tip(user_id: int, daily_limit: int, bypass_limits: bool = False) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT grammar_tips_asked_today, grammar_tips_asked_date FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        asked = _current_daily_count(row["grammar_tips_asked_today"], row["grammar_tips_asked_date"])
        if not bypass_limits and daily_limit >= 0 and asked >= daily_limit:
            return False
        today = _today().isoformat()
        conn.execute(
            "UPDATE users SET grammar_tips_asked_today=?, grammar_tips_asked_date=? WHERE user_id=?",
            (asked + 1, today, user_id),
        )
        conn.commit()
        return True


def release_grammar_tip(user_id: int):
    today = _today().isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET grammar_tips_asked_today="
            "MAX(grammar_tips_asked_today - 1, 0) "
            "WHERE user_id=? AND grammar_tips_asked_date=?",
            (user_id, today),
        )
        conn.commit()


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
        conn.execute("BEGIN IMMEDIATE")
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
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE query_results SET saved_at=COALESCE(saved_at, ?), "
            "saved_word_id=COALESCE(saved_word_id, ?) WHERE token=?",
            (_utc_now().isoformat(), saved_word_id, token),
        )
        conn.commit()


def update_query_result_fields(
    token: str,
    user_id: int,
    patch: dict,
) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT result_json FROM query_results WHERE token=? AND user_id=?",
            (token, user_id),
        ).fetchone()
        if not row:
            return False
        try:
            result_data = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(result_data, dict):
            return False
        result_data.update(patch)
        conn.execute(
            "UPDATE query_results SET result_json=? WHERE token=? AND user_id=?",
            (json.dumps(result_data, ensure_ascii=False), token, user_id),
        )
        conn.commit()
        return True


def cleanup_expired_query_results():
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM query_results WHERE expires_at<?",
            (_utc_now().isoformat(),),
        )
        conn.commit()


def add_grammar_tip(
    user_id: int,
    title: str,
    lang: str,
    goal: str,
    level: str,
    tip_data: dict,
    provenance: str = "",
):
    title = " ".join(title.split())
    if not title:
        return
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO grammar_tips("
            "user_id, tip_date, title, lang, goal, level, tip_json, created_at, provenance"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                _today().isoformat(),
                title,
                lang,
                goal,
                level,
                json.dumps(tip_data, ensure_ascii=False),
                _utc_now().isoformat(),
                provenance,
            ),
        )
        conn.commit()


def recent_grammar_tip_titles(
    user_id: int,
    lang: str | None = None,
    limit: int = 12,
) -> list[str]:
    query = "SELECT title FROM grammar_tips WHERE user_id=?"
    params: list[object] = [user_id]
    if lang is not None:
        query += " AND lang=?"
        params.append(lang)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [row["title"] for row in rows]


def add_llm_request(
    *,
    user_id: int,
    plan: str,
    request_kind: str,
    model: str,
    outcome: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    input_cost_usd_per_million: float,
    output_cost_usd_per_million: float,
    usd_to_toman_rate: float,
    latency_ms: int | None,
    error_class: str | None = None,
    error_message: str | None = None,
):
    prompt_tokens = int(prompt_tokens or 0)
    completion_tokens = int(completion_tokens or 0)
    total_tokens = int(total_tokens or (prompt_tokens + completion_tokens))
    cost_usd = (
        (prompt_tokens / 1_000_000) * float(input_cost_usd_per_million)
        + (completion_tokens / 1_000_000) * float(output_cost_usd_per_million)
    )
    cost_toman = cost_usd * float(usd_to_toman_rate)
    request_id = secrets.token_hex(16)
    now = _utc_now()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO llm_requests("
            "request_id, created_at, request_date, user_id, plan, request_kind, model, "
            "outcome, prompt_tokens, completion_tokens, total_tokens, "
            "input_cost_usd_per_million, output_cost_usd_per_million, usd_to_toman_rate, "
            "cost_usd, cost_toman, latency_ms, error_class, error_message"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request_id,
                now.isoformat(),
                _today().isoformat(),
                user_id,
                plan,
                request_kind,
                model,
                outcome,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                float(input_cost_usd_per_million),
                float(output_cost_usd_per_million),
                float(usd_to_toman_rate),
                cost_usd,
                cost_toman,
                latency_ms,
                error_class,
                (error_message or "")[:1000] or None,
            ),
        )
        conn.commit()
    return request_id


def _llm_request_filters_where(filters: dict[str, object]) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    def add_clause(sql: str, value: object | None):
        if value is None or value == "":
            return
        clauses.append(sql)
        params.append(value)

    add_clause("request_date>=?", filters.get("start_date"))
    add_clause("request_date<=?", filters.get("end_date"))
    add_clause("user_id=?", filters.get("user_id"))
    add_clause("plan=?", filters.get("plan"))
    add_clause("request_kind=?", filters.get("request_kind"))
    add_clause("model=?", filters.get("model"))
    add_clause("outcome=?", filters.get("outcome"))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def summarize_llm_requests(filters: dict[str, object] | None = None) -> dict[str, object]:
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        row = conn.execute(
            "SELECT "
            "COUNT(*) AS request_count, "
            "SUM(COALESCE(prompt_tokens, 0)) AS prompt_tokens, "
            "SUM(COALESCE(completion_tokens, 0)) AS completion_tokens, "
            "SUM(COALESCE(total_tokens, 0)) AS total_tokens, "
            "SUM(COALESCE(cost_usd, 0)) AS cost_usd, "
            "SUM(COALESCE(cost_toman, 0)) AS cost_toman, "
            "AVG(latency_ms) AS avg_latency_ms, "
            "SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS success_count, "
            "SUM(CASE WHEN outcome='failure_billed' THEN 1 ELSE 0 END) AS billed_failure_count, "
            "SUM(CASE WHEN outcome='failure_zero_cost' THEN 1 ELSE 0 END) AS zero_cost_failure_count, "
            "SUM(CASE WHEN outcome='failure_billed' THEN COALESCE(cost_usd, 0) ELSE 0 END) "
            "AS billed_failure_cost_usd, "
            "SUM(CASE WHEN outcome='failure_billed' THEN COALESCE(cost_toman, 0) ELSE 0 END) "
            "AS billed_failure_cost_toman "
            "FROM llm_requests"
            f"{where}",
            params,
        ).fetchone()
    return dict(row or {})


def breakdown_llm_requests(
    group_by: str,
    filters: dict[str, object] | None = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    if group_by not in {"user_id", "plan", "request_kind", "model", "outcome"}:
        raise ValueError(f"Unsupported LLM breakdown: {group_by}")
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT "
            f"{group_by} AS bucket, "
            "COUNT(*) AS request_count, "
            "SUM(COALESCE(prompt_tokens, 0)) AS prompt_tokens, "
            "SUM(COALESCE(completion_tokens, 0)) AS completion_tokens, "
            "SUM(COALESCE(total_tokens, 0)) AS total_tokens, "
            "SUM(COALESCE(cost_usd, 0)) AS cost_usd, "
            "SUM(COALESCE(cost_toman, 0)) AS cost_toman, "
            "AVG(latency_ms) AS avg_latency_ms, "
            "SUM(CASE WHEN outcome='failure_billed' THEN 1 ELSE 0 END) "
            "AS billed_failure_count, "
            "SUM(CASE WHEN outcome='failure_zero_cost' THEN 1 ELSE 0 END) "
            "AS zero_cost_failure_count "
            "FROM llm_requests"
            f"{where} "
            f"GROUP BY {group_by} "
            "ORDER BY cost_usd DESC, request_count DESC, bucket ASC "
            "LIMIT ?",
            [*params, limit],
        ).fetchall()
    return [dict(row) for row in rows]


def recent_llm_requests(
    filters: dict[str, object] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, object]]:
    where, params = _llm_request_filters_where(filters or {})
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_requests"
            f"{where} "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows]


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
        conn.execute("BEGIN IMMEDIATE")
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
        conn.execute("BEGIN IMMEDIATE")
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
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE delivery_queue SET status='sent', sent_at=?, last_error=NULL WHERE id=?",
            (_utc_now().isoformat(), queue_id),
        )
        conn.commit()


def advance_delivery_progress(queue_id: int, sent_count: int):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
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
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE delivery_queue SET status='failed', last_error=?, retry_at=? WHERE id=?",
            (error[:1000], retry_at, queue_id),
        )
        conn.commit()


def requeue_stale_deliveries(stale_before: str, max_attempts: int = 5):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
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
        conn.execute("BEGIN IMMEDIATE")
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


def claim_srs_reminder(word_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE saved_words SET review_status='claiming', review_requested_at=? "
            "WHERE id=? AND review_status='idle'",
            (_utc_now().isoformat(), word_id),
        )
        conn.commit()
        return cursor.rowcount == 1


def release_srs_claim(word_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE saved_words SET review_status='idle', review_requested_at=NULL "
            "WHERE id=? AND review_status='claiming'",
            (word_id,),
        )
        conn.commit()
        return cursor.rowcount == 1


def mark_word_review_pending(word_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE saved_words SET review_status='pending', review_requested_at=? "
            "WHERE id=? AND review_status='claiming'",
            (_utc_now().isoformat(), word_id),
        )
        conn.commit()
        return cursor.rowcount == 1


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


REVIEW_OUTCOMES = ("recalled", "recalled_after_peek", "again")


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


# ---------- SRS Retry Queue ----------

def mark_srs_send_failed(word_id: int, current_attempts: int, max_attempts: int = 5):
    if current_attempts >= max_attempts:
        with get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE saved_words SET retry_at=NULL, srs_retry_attempts=? WHERE id=?",
                (current_attempts, word_id),
            )
            conn.commit()
        return
    delay = min(300 * (2 ** current_attempts), 3600)
    retry_at = (_utc_now() + datetime.timedelta(seconds=delay)).isoformat()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE saved_words SET retry_at=?, review_status='idle', srs_retry_attempts=? WHERE id=?",
            (retry_at, current_attempts, word_id),
        )
        conn.commit()


def get_due_srs_failed(max_words: int = 50):
    now = _utc_now().isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM saved_words WHERE retry_at IS NOT NULL AND retry_at<=? "
            "AND review_status='idle' ORDER BY retry_at LIMIT ?",
            (now, max_words),
        ).fetchall()


def clear_srs_retry(word_id: int):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE saved_words SET retry_at=NULL, srs_retry_attempts=0 WHERE id=?",
            (word_id,),
        )
        conn.commit()


# ---------- AI Presets (provider profiles with batch/RPM limits) ----------

def _init_ai_presets_table(conn):
    """Create ai_presets table and seed built-in presets."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_presets (
            name TEXT PRIMARY KEY,
            base_url TEXT,
            model TEXT,
            api_key TEXT NOT NULL DEFAULT '',
            daily_batch_size INTEGER DEFAULT 6,
            max_concurrency INTEGER DEFAULT 2,
            max_rpm INTEGER DEFAULT 30,
            max_tpm INTEGER DEFAULT 0,
            max_daily_req INTEGER DEFAULT 0,
            timeout_seconds REAL DEFAULT 30.0,
            temperature REAL DEFAULT 0.6,
            max_output_tokens INTEGER DEFAULT 4096,
            is_custom INTEGER DEFAULT 0,
            priority INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            is_emergency INTEGER DEFAULT 0
        );
        """
    )
    # Migrate missing columns for existing databases
    preset_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(ai_presets)").fetchall()
    }
    for col_name, col_def in {
        "api_key": "TEXT NOT NULL DEFAULT ''",
        "max_tpm": "INTEGER DEFAULT 0",
        "max_daily_req": "INTEGER DEFAULT 0",
        "priority": "INTEGER DEFAULT 0",
        "enabled": "INTEGER DEFAULT 1",
        "is_emergency": "INTEGER DEFAULT 0",
    }.items():
        if col_name not in preset_columns:
            conn.execute(f"ALTER TABLE ai_presets ADD COLUMN {col_name} {col_def}")
    # Create preset_hourly_usage table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_hourly_usage (
            preset_name TEXT NOT NULL,
            hour_bucket TEXT NOT NULL,
            request_count INTEGER DEFAULT 0,
            token_count INTEGER DEFAULT 0,
            PRIMARY KEY (preset_name, hour_bucket)
        );
        """
    )
    # Replace all presets with current BUILTIN_PRESETS
    from services.ai.ai_presets import seed_presets as get_builtins
    builtin_names = {p[0] for p in get_builtins()}
    conn.execute("DELETE FROM ai_presets WHERE name NOT IN ({})".format(
        ",".join("?" for _ in builtin_names)
    ), list(builtin_names))
    for p in get_builtins():
        conn.execute(
            "INSERT OR REPLACE INTO ai_presets(name, base_url, model, api_key, daily_batch_size, max_concurrency, max_rpm, max_tpm, max_daily_req, timeout_seconds, temperature, max_output_tokens, is_custom, priority, enabled, is_emergency) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            p,
        )
    # Reset old fallback settings that may point to deleted presets
    first = conn.execute(
        "SELECT name FROM ai_presets WHERE enabled=1 AND is_emergency=0 ORDER BY priority ASC, name ASC LIMIT 1"
    ).fetchone()
    if first:
        conn.execute(
            "UPDATE settings SET value=? WHERE key='ai_primary_preset'",
            (first["name"],),
        )
    conn.execute("DELETE FROM settings WHERE key IN ('ai_fallback_preset', 'ai_fallback_active', 'ai_fallback_threshold')")
    conn.commit()


def _init_config_tests_table(conn):
    """Create config_tests table for audit logging."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS config_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_type TEXT,
            preset_name TEXT,
            prompt TEXT,
            result TEXT,
            created_at TEXT
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS config_tests_created_at_idx ON config_tests(created_at)"
    )


# Add table initializations to init_db (called after existing tables)
# We'll append these calls to the existing init_db function's conn block


def get_presets() -> list[dict]:
    """Return all presets as list of dicts."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM ai_presets ORDER BY is_custom, name").fetchall()
    return [dict(row) for row in rows]


def get_preset(name: str) -> dict | None:
    """Return a single preset by name."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_presets WHERE name=?", (name,)).fetchone()
    return dict(row) if row else None


def get_active_preset_name() -> str:
    """Get the currently active preset name (considers fallback)."""
    if get_bool_setting("ai_fallback_active", False):
        return get_setting("ai_fallback_preset", "gapgpt_gemini_lite")
    return get_setting("ai_primary_preset", _first_enabled_name())


def get_active_preset() -> dict:
    """Get the active preset dict (with fallback logic)."""
    name = get_active_preset_name()
    preset = get_preset(name)
    if not preset:
        preset = get_preset(_first_enabled_name())
    return preset or {}


def set_preset(
    name: str,
    base_url: str = "",
    model: str = "",
    api_key: str = "",
    daily_batch_size: int = 6,
    max_concurrency: int = 2,
    max_rpm: int = 30,
    timeout_seconds: float = 30.0,
    temperature: float = 0.6,
    max_output_tokens: int = 4096,
    is_custom: int = 1,
):
    """Upsert a preset (custom presets only)."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO ai_presets(name, base_url, model, api_key, daily_batch_size, max_concurrency, max_rpm, timeout_seconds, temperature, max_output_tokens, is_custom) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "base_url=excluded.base_url, model=excluded.model, api_key=excluded.api_key, "
            "daily_batch_size=excluded.daily_batch_size, "
            "max_concurrency=excluded.max_concurrency, max_rpm=excluded.max_rpm, "
            "timeout_seconds=excluded.timeout_seconds, temperature=excluded.temperature, "
            "max_output_tokens=excluded.max_output_tokens, is_custom=excluded.is_custom",
            (
                name,
                base_url,
                model,
                api_key,
                daily_batch_size,
                max_concurrency,
                max_rpm,
                timeout_seconds,
                temperature,
                max_output_tokens,
                is_custom,
            ),
        )
        conn.commit()


def delete_preset(name: str) -> bool:
    """Delete a preset (built-in or custom)."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "DELETE FROM ai_presets WHERE name=?", (name,)
        )
        conn.commit()
        return cursor.rowcount > 0


def activate_preset(name: str) -> bool:
    """Set the active primary preset."""
    preset = get_preset(name)
    if not preset:
        return False
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_primary_preset", name),
        )
        # Also sync to legacy settings for backward compatibility
        if preset.get("base_url"):
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_base_url", preset["base_url"]),
            )
        if preset.get("model"):
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_model", preset["model"]),
            )
        if preset.get("api_key"):
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_api_key", preset["api_key"]),
            )
        conn.commit()
    return True


# ---------- Fallback State Management ----------

def set_fallback_active(active: bool, fallback_preset: str | None = None):
    """Activate or deactivate fallback mode."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_fallback_active", "true" if active else "false"),
        )
        if active:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_fallback_since", _utc_now().isoformat()),
            )
            if fallback_preset:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("ai_fallback_preset", fallback_preset),
                )
        else:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_fallback_since", ""),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("ai_consecutive_failures", "0"),
            )
        conn.commit()


def increment_consecutive_failures() -> int:
    """Increment and return the consecutive failures counter."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = int(get_setting("ai_consecutive_failures", "0")) + 1
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_consecutive_failures", str(current)),
        )
        conn.commit()
        return current


def reset_consecutive_failures():
    """Reset the consecutive failures counter."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("ai_consecutive_failures", "0"),
        )
        conn.commit()


def _first_enabled_name() -> str:
    """Get the first enabled non-emergency preset name (chain-based default)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM ai_presets WHERE enabled=1 AND is_emergency=0 ORDER BY priority ASC, name ASC LIMIT 1"
        ).fetchone()
    return row["name"] if row else "google_35_flash_hpof"


def get_fallback_status() -> dict:
    """Get current fallback status info."""
    return {
        "fallback_active": get_bool_setting("ai_fallback_active", False),
        "primary_preset": get_setting("ai_primary_preset", _first_enabled_name()),
        "fallback_preset": get_setting("ai_fallback_preset", "gapgpt_gemini_lite"),
        "fallback_since": get_setting("ai_fallback_since", ""),
        "consecutive_failures": int(get_setting("ai_consecutive_failures", "0")),
    }


# ---------- Preset Hourly Usage ----------

def get_hourly_usage(preset_name: str, hours_back: int = 24) -> tuple[int, int]:
    """Return (request_count, token_count) for a preset over the last N hours."""
    import datetime as dt
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_back)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(request_count), 0) req, COALESCE(SUM(token_count), 0) tok "
            "FROM preset_hourly_usage WHERE preset_name=? AND hour_bucket >= ?",
            (preset_name, cutoff[:13]),
        ).fetchone()
    return (row["req"], row["tok"])


def increment_hourly_usage(preset_name: str, hour_bucket: str, req_count: int = 1, token_count: int = 0):
    """Increment usage counters for a preset in a given hour bucket."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO preset_hourly_usage(preset_name, hour_bucket, request_count, token_count) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(preset_name, hour_bucket) DO UPDATE SET "
            "request_count=request_count+excluded.request_count, "
            "token_count=token_count+excluded.token_count",
            (preset_name, hour_bucket, req_count, token_count),
        )
        conn.commit()


# ---------- Preset Management ----------

def get_enabled_presets_ordered() -> list[dict]:
    """Return enabled presets ordered by is_emergency, priority, name."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_presets WHERE enabled=1 ORDER BY is_emergency ASC, priority ASC, name ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def set_preset_priority(name: str, priority: int):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE ai_presets SET priority=? WHERE name=?", (priority, name))
        conn.commit()


def set_preset_enabled(name: str, enabled: bool):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE ai_presets SET enabled=? WHERE name=?", (1 if enabled else 0, name))
        conn.commit()


def set_preset_emergency(name: str, is_emergency: bool):
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE ai_presets SET is_emergency=? WHERE name=?", (1 if is_emergency else 0, name))
        conn.commit()


# ---------- Config Tests Audit ----------

def log_config_test(test_type: str, preset_name: str, prompt: str, result: dict):
    """Log a config test result."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO config_tests(test_type, preset_name, prompt, result, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                test_type,
                preset_name,
                prompt,
                json.dumps(result, ensure_ascii=False),
                _utc_now().isoformat(),
            ),
        )
        conn.commit()


# ---------- Backup / Restore ----------

def export_db_bytes() -> bytes:
    """Read the entire SQLite database file as bytes."""
    with open(DB_PATH, "rb") as f:
        return f.read()


def import_db_bytes(data: bytes) -> None:
    """Replace the current database file with the provided bytes, then re-initialize."""
    with open(DB_PATH, "wb") as f:
        f.write(data)
    init_db()
