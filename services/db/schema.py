import json
import os
import sqlite3
import threading
import datetime
import secrets
from contextlib import contextmanager

from config.catalog import DEFAULT_LEVEL, DISPLAY_TOGGLE_DEFAULTS

from config import (
    DB_PATH,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    LLM_INPUT_COST_USD_PER_MILLION,
    LLM_OUTPUT_COST_USD_PER_MILLION,
    APP_TZ,
    USD_TO_TOMAN_RATE,
)

_app_timezone = APP_TZ
_LEGACY_DAILY_TABLES = frozenset(
    {"daily_cards", "daily_progress", "daily_card_sessions"}
)

# Canonical ai_presets column set. This is the single source of truth for the
# table definition, reused by every CREATE so the fresh-DB schema and the
# table-rebuild migration can never drift.
_AI_PRESETS_COLUMNS = (
    "name TEXT PRIMARY KEY",
    "base_url TEXT",
    "model TEXT",
    "api_key TEXT NOT NULL DEFAULT ''",
    "daily_batch_size INTEGER DEFAULT 6",
    "max_concurrency INTEGER DEFAULT 2",
    "max_rpm INTEGER DEFAULT 30",
    "max_tpm INTEGER DEFAULT 0",
    "max_daily_req INTEGER DEFAULT 0",
    "timeout_seconds REAL DEFAULT 30.0",
    "temperature REAL DEFAULT 0.6",
    "max_output_tokens INTEGER DEFAULT 4096",
    "priority INTEGER DEFAULT 0",
    "enabled INTEGER DEFAULT 1",
    "is_emergency INTEGER DEFAULT 0",
    "input_cost_per_million REAL",
    "output_cost_per_million REAL",
    "group_label TEXT DEFAULT ''",
    "in_fallback_chain INTEGER DEFAULT 1",
)


def _ai_presets_create_sql(if_not_exists: bool = False) -> str:
    """Return a CREATE TABLE statement for ai_presets from the canonical column
    set (single source of truth), so the fresh schema and the rebuild migration
    can never drift. The rebuild uses a plain CREATE (no IF NOT EXISTS)."""
    cols = ",\n                ".join(_AI_PRESETS_COLUMNS)
    prefix = "CREATE TABLE IF NOT EXISTS " if if_not_exists else "CREATE TABLE "
    return f"{prefix}ai_presets (\n                {cols}\n            );"


def _today() -> datetime.date:
    return datetime.datetime.now(_app_timezone).date()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _normalize_word(word: str) -> str:
    return " ".join(word.split()).casefold()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _require_daily_cards_migrated(conn: sqlite3.Connection) -> None:
    """Refuse destructive daily-table cleanup on an unmigrated database."""
    tables = _table_names(conn)
    if not (_LEGACY_DAILY_TABLES & tables):
        return
    if "settings" not in tables:
        raise RuntimeError(
            "Refusing to drop legacy daily tables: "
            "settings.fsrs_migration_done=1 is missing."
        )
    migrated = conn.execute(
        "SELECT value FROM settings WHERE key='fsrs_migration_done'"
    ).fetchone()
    if not migrated or migrated["value"] != "1":
        raise RuntimeError(
            "Refusing to drop legacy daily tables: "
            "settings.fsrs_migration_done=1 is required."
        )


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
        from config import DB_PATH as _config_db_path
        _production_path = os.environ.get(
            "HAMZABAN_PRODUCTION_DB_PATH", _config_db_path
        )
        if os.path.abspath(path) == os.path.abspath(_production_path):
            raise RuntimeError(
                "Test mode refuses to open the production database at "
                f"{path!r}. A test must override db.DB_PATH."
            )


_DB_LOCK = threading.RLock()


@contextmanager
def database_lock():
    with _DB_LOCK:
        yield


@contextmanager
def get_conn(path: str | None = None):
    # Read the path live from services.db (where tests set db.DB_PATH) instead
    # of the import-time copy below, so test DB isolation is actually honored.
    if path is None:
        from services.db import DB_PATH as _active_db_path
    else:
        _active_db_path = path
    with database_lock():
        _check_test_mode_guard(_active_db_path)
        conn = sqlite3.connect(_active_db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


@contextmanager
def transaction(path: str | None = None):
    """Single atomicity seam: immediate-transaction write context.

    Wraps ``get_conn`` + ``BEGIN IMMEDIATE`` and commits on clean exit or rolls
    back on any exception. Callers never manage commit/rollback themselves —
    this is the one place atomic-write policy lives. Use it for every write
    that may contend (quota reservations, delivery queue, saved words, plans).
    """
    with get_conn(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def init_db(path: str | None = None):
    with get_conn(path) as conn:
        _require_daily_cards_migrated(conn)
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
                display_toggles TEXT,
                display_toggles_forced TEXT,
                first_exposure_mode TEXT,
                review_mode TEXT,
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
                next_review TEXT,
                review_status TEXT DEFAULT 'idle',
                review_requested_at TEXT,
                added_at TEXT,
                first_exposure_done INTEGER DEFAULT 0,
                stability REAL DEFAULT 0.0,
                difficulty REAL DEFAULT 5.0,
                entry_source TEXT DEFAULT 'manual',
                last_review_at TEXT,
                next_review_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
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
            CREATE INDEX IF NOT EXISTS query_results_user_lang_text_idx
                ON query_results(user_id, lang, query_text);
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
            CREATE TABLE IF NOT EXISTS study_sessions (
                user_id INTEGER PRIMARY KEY,
                session_date TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
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
            "display_toggles": "TEXT",
            "display_toggles_forced": "TEXT",
            "first_exposure_mode": "TEXT",
            "review_mode": "TEXT",
        }
        for name, definition in user_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        if "bot_blocked" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN bot_blocked INTEGER DEFAULT 0")
        conn.commit()
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
        if "first_exposure_done" not in saved_word_columns:
            conn.execute(
                "ALTER TABLE saved_words ADD COLUMN first_exposure_done INTEGER DEFAULT 0"
            )
        if "stability" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN stability REAL DEFAULT 0.0")
        if "difficulty" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN difficulty REAL DEFAULT 5.0")
        if "entry_source" not in saved_word_columns:
            conn.execute(
                "ALTER TABLE saved_words ADD COLUMN entry_source TEXT DEFAULT 'manual'"
            )
        added_timestamp_columns = False
        if "last_review_at" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN last_review_at TEXT")
            added_timestamp_columns = True
        if "next_review_at" not in saved_word_columns:
            conn.execute("ALTER TABLE saved_words ADD COLUMN next_review_at TEXT")
            added_timestamp_columns = True
        if added_timestamp_columns and "next_review" in saved_word_columns:
            # A row marked first_exposure_done=1 with a NULL last_review_at is
            # inconsistent (exposed without a grade time). Reset it to a
            # deterministic first-exposure state and clear transient review
            # fields, without fabricating a review timestamp. Runs only when
            # the timestamp columns are introduced (idempotent on re-init).
            conn.execute(
                """
                UPDATE saved_words
                SET first_exposure_done = 0,
                    stability = 0.0,
                    difficulty = 5.0,
                    last_review_at = NULL,
                    next_review_at = NULL,
                    next_review = ?,
                    review_status = 'idle',
                    review_requested_at = NULL,
                    retry_at = NULL,
                    srs_retry_attempts = 0
                WHERE COALESCE(first_exposure_done, 0) = 1
                  AND last_review_at IS NULL
                """,
                (_today().isoformat(),),
            )
        review_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(review_events)").fetchall()
        }
        for col, col_def in (
            ("grade", "INTEGER"),
            ("activity_type", "TEXT"),
            ("grade_source", "TEXT"),
            ("raw_signal", "TEXT"),
            ("response_time_ms", "INTEGER"),
        ):
            if col not in review_columns:
                conn.execute(f"ALTER TABLE review_events ADD COLUMN {col} {col_def}")
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
            "display_toggle_defaults": json.dumps(DISPLAY_TOGGLE_DEFAULTS),
            "first_exposure_mode": "staged",
            "review_mode": "staged",
            "first_exposure_mode_gate": "premium",
            "review_mode_gate": "premium",
        }
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        for tbl, col, col_def in (
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

        # Initialize plans table with default plan specs (admin-editable)
        _init_plans_table(conn)

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
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('ai_fallback_preset', '')")

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

        # Phase 5 (R3): encrypt any API keys still at rest as plaintext or
        # "$ENV" references (see _encrypt_key_columns). Runs after the legacy
        # settings->preset sync so a copied legacy key is also encrypted, and
        # before the destructive cleanup commit below.
        _encrypt_key_columns(conn)

        # Commit all additive migrations before the destructive cleanup so a
        # failure in DROP COLUMN/TABLE rolls back the destructive transaction.
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        saved_word_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(saved_words)").fetchall()
        }
        if "interval_idx" in saved_word_columns:
            conn.execute("ALTER TABLE saved_words DROP COLUMN interval_idx")
        for table in sorted(_LEGACY_DAILY_TABLES):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()


def _init_ai_presets_table(conn):
    """Create ai_presets table and run migrations.

    Does NOT auto-seed or modify existing presets — all preset management is
    manual through the AI Preset Manager tool or the admin panel. A fresh
    database starts with zero presets.
    """
    conn.execute(_ai_presets_create_sql(if_not_exists=True))
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
    # Additive optional group-key table. A group shares one default API key;
    # a preset uses its own key if set, else its group's key. Empty by default.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_groups (
            group_label TEXT PRIMARY KEY,
            api_key TEXT NOT NULL DEFAULT ''
        );
        """
    )
    # Phase 4 migration: drop the now-obsolete is_custom column. Existing DBs
    # (created before Phase 4) may still have it; a fresh DB never does. Because
    # SQLite cannot always DROP COLUMN portably, rebuild the table without the
    # column when it is present. All rows are preserved (they become ordinary
    # presets). We rebuild with the full new column set and copy every remaining
    # column by name so migrated columns (costs, group_label, in_fallback_chain,
    # etc.) are never lost.
    _cols = {row["name"] for row in conn.execute("PRAGMA table_info(ai_presets)").fetchall()}
    if "is_custom" in _cols:
        _keep = [c for c in _cols if c != "is_custom"]
        _cols_sql = ", ".join(_keep)
        # api_key is NOT NULL in the canonical schema; coerce any legacy NULL to
        # '' so the INSERT can never raise IntegrityError and block startup.
        _sel_sql = ", ".join(
            "COALESCE(api_key, '')" if c == "api_key" else c for c in _keep
        )
        conn.execute("ALTER TABLE ai_presets RENAME TO ai_presets_old")
        conn.execute(_ai_presets_create_sql())
        conn.execute(
            f"INSERT INTO ai_presets({_cols_sql}) SELECT {_sel_sql} FROM ai_presets_old"
        )
        conn.execute("DROP TABLE ai_presets_old")
    # Data fix (R3A): historical databases seeded before the "$ENV" convention
    # stored the HpOF env-var name bare (e.g. "HpOF_API_KEY" without the "$"
    # prefix), so resolve_api_key treated it as a literal key and the provider
    # rejected it. Prefix "$" idempotently — only for these known HP presets
    # and only when the stored value is exactly the bare env name (never
    # touching custom/ELI/GAPGPT keys or real literal key values).
    conn.execute(
        "UPDATE ai_presets SET api_key = '$' || api_key "
        "WHERE name IN ('g3_6_f_HP', 'g3_5_f_HP', 'g3_5_FL_HP', 'g3_1_FL_HP') "
        "AND api_key = 'HpOF_API_KEY'"
    )
    conn.commit()


def _encrypt_key_columns(conn):
    """Phase 5 (R3): encrypt API keys at rest across all storage sites.

    Converts any still-plaintext or ``$ENV`` reference stored in
    ``ai_presets.api_key``, ``preset_groups.api_key``, and ``settings.ai_api_key``
    into Fernet ciphertext. Idempotent: a value that already decrypts under the
    current master key is left untouched (so an unchanged re-run, a plaintext
    value, or a token from a *previous* key after rotation are all handled by
    ``encrypt_for_storage``). A ``$ENV`` reference is resolved to the real
    environment value before encryption; if the env var is unset the stored
    value becomes empty (R3). Fail-closed: when no master key is configured we
    MUST NOT destroy existing values, so the migration is skipped entirely and
    re-runs once a key is added.
    """
    from services.db.key_crypto import encrypt_for_storage, _fernet

    if _fernet() is None:
        return

    def _encrypt(raw: str) -> str:
        if not raw:
            return ""
        if raw.startswith("$"):
            return encrypt_for_storage(os.getenv(raw[1:], "") or "")
        return encrypt_for_storage(raw)

    for row in conn.execute("SELECT name, api_key FROM ai_presets").fetchall():
        enc = _encrypt(row["api_key"] or "")
        if enc != (row["api_key"] or ""):
            conn.execute(
                "UPDATE ai_presets SET api_key=? WHERE name=?", (enc, row["name"])
            )
    for row in conn.execute(
        "SELECT group_label, api_key FROM preset_groups"
    ).fetchall():
        enc = _encrypt(row["api_key"] or "")
        if enc != (row["api_key"] or ""):
            conn.execute(
                "UPDATE preset_groups SET api_key=? WHERE group_label=?",
                (enc, row["group_label"]),
            )
    row = conn.execute("SELECT value FROM settings WHERE key='ai_api_key'").fetchone()
    if row:
        enc = _encrypt(row["value"] or "")
        if enc != (row["value"] or ""):
            conn.execute(
                "UPDATE settings SET value=? WHERE key='ai_api_key'", (enc,)
            )


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


def _init_plans_table(conn):
    """Create the administrative plans table and seed default plans.

    Plan specs are admin-editable; the seed only runs when the table is empty
    (fresh database / upgrade), so admin edits persist across restarts.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            name TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            query_quota INTEGER NOT NULL DEFAULT 0,
            max_sessions INTEGER NOT NULL DEFAULT 1,
            cards_per_session INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            first_exposure_mode TEXT,
            review_mode TEXT
        );
        """
    )
    plan_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(plans)").fetchall()
    }
    for col in ("first_exposure_mode", "review_mode"):
        if col not in plan_columns:
            conn.execute(f"ALTER TABLE plans ADD COLUMN {col} TEXT")
    count = conn.execute("SELECT COUNT(*) AS c FROM plans").fetchone()["c"]
    if count == 0:
        from services.db.plans import DEFAULT_PLANS
        for name, (display_name, price, query_quota, max_sessions,
                   cards_per_session, sort_order) in DEFAULT_PLANS.items():
            conn.execute(
                "INSERT INTO plans("
                "name, display_name, price, query_quota, max_sessions, "
                "cards_per_session, is_active, sort_order"
                ") VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    name, display_name, price, query_quota, max_sessions,
                    cards_per_session, sort_order,
                ),
            )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS plans_sort_idx ON plans(sort_order)"
    )
    conn.commit()
