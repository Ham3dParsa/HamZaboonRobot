import json
import os
import sqlite3
import datetime
import secrets
from contextlib import contextmanager
from zoneinfo import ZoneInfo
from config.catalog import DEFAULT_LEVEL

from config import (
    DB_PATH,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    DEFAULT_PHONETIC_SHOW_IPA,
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


def _check_test_mode_guard(path: str) -> None:
    """Refuse to open the production DB while the test suite is running.

    Every database operation funnels through get_conn(), so one guard here
    protects the real database from any test that forgets to override
    db.DB_PATH. HAMZABAN_TEST_MODE is set by tests/__init__.py and CI.
    """
    if os.environ.get("HAMZABAN_TEST_MODE") == "1":
        from config import DB_PATH as _production_path
        if os.path.abspath(path) == os.path.abspath(_production_path):
            raise RuntimeError(
                "Test mode refuses to open the production database at "
                f"{path!r}. A test must override db.DB_PATH."
            )


@contextmanager
def get_conn():
    # Read the path live from services.db (where tests set db.DB_PATH) instead
    # of the import-time copy below, so test DB isolation is actually honored.
    from services.db import DB_PATH as _active_db_path
    _check_test_mode_guard(_active_db_path)
    conn = sqlite3.connect(_active_db_path)
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
        if "bot_blocked" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN bot_blocked INTEGER DEFAULT 0")
        conn.commit()
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


def _init_ai_presets_table(conn):
    """Create ai_presets table and run migrations.

    Does NOT auto-seed or modify existing presets — all preset management is
    manual through the AI Preset Manager tool or the admin panel.
    Only seeds default presets on a completely empty table (fresh database).
    """
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
        "input_cost_per_million": "REAL",
        "output_cost_per_million": "REAL",
        "group_label": "TEXT DEFAULT ''",
        "in_fallback_chain": "INTEGER DEFAULT 1",
    }.items():
        if col_name not in preset_columns:
            conn.execute(f"ALTER TABLE ai_presets ADD COLUMN {col_name} {col_def}")
    # Migrate preset_name column on llm_requests
    llm_request_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(llm_requests)").fetchall()
    }
    if "preset_name" not in llm_request_columns:
        conn.execute("ALTER TABLE llm_requests ADD COLUMN preset_name TEXT")
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
    # Seed default presets only on first run (empty table).
    count = conn.execute("SELECT COUNT(*) as c FROM ai_presets").fetchone()["c"]
    if count == 0:
        from services.ai.ai_presets import seed_presets as get_builtins
        for p in get_builtins():
            conn.execute(
                "INSERT INTO ai_presets("
                "name, base_url, model, api_key, "
                "daily_batch_size, max_concurrency, max_rpm, "
                "max_tpm, max_daily_req, timeout_seconds, "
                "temperature, max_output_tokens, is_custom, "
                "priority, enabled, is_emergency, "
                "input_cost_per_million, output_cost_per_million, "
                "group_label, in_fallback_chain"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                p,
            )
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
