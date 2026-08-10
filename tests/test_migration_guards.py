"""Migration-completeness guards (WP2).

Reusable template for schema migrations. Every schema change must be verified
on BOTH a fresh database and a database upgraded from the prior schema:

    - expected columns/functions are present after init_db()
    - banned (removed) columns are absent

The FSRS migration (plan_fsrs_migration_v2.md) reuses this template: it adds
stability/difficulty/first_exposure_done columns to saved_words and drops
interval_idx. When that lands, `interval_idx` moves from EXPECTED to BANNED
here and the FSRS columns move into EXPECTED.
"""

import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager

from services import db as db_module
from services.db import schema as db_schema


# Columns that MUST exist after init_db() on both fresh and upgraded DBs.
# Update this list when a migration adds or removes columns.
EXPECTED_COLUMNS = {
    "users": {
        "user_id",
        "level",
        "onboarded",
        "bot_blocked",
        "presentation_preference",
    },
    "saved_words": {
        "id",
        "user_id",
        "word",
        "lang",
        "normalized_word",
        "card_data",
        "next_review",
        "review_status",
        "review_requested_at",
        "retry_at",
        "srs_retry_attempts",
        "first_exposure_done",  # NOTE: added in Phase 3a migration
        "stability",           # NOTE: added in Phase 3a migration
        "difficulty",          # NOTE: added in Phase 3a migration
        "entry_source",        # NOTE: added in entry_source column change
    },
    "review_events": {"id", "word_id", "user_id", "outcome", "created_at"},
    "llm_requests": {"id", "request_id", "cost_usd", "preset_name"},
    "ai_presets": {"name", "input_cost_per_million", "group_label"},
}

# Columns that MUST NOT exist after init_db(). A migration that drops a column
# adds it here so CI proves the drop actually happened.
BANNED_COLUMNS = {
    "saved_words": {"interval_idx"},
}

# Tables that must exist after init_db().
EXPECTED_TABLES = {
    "users",
    "saved_words",
    "settings",
    "query_results",
    "grammar_tips",
    "llm_requests",
    "review_events",
    "ai_presets",
    "preset_hourly_usage",
    "config_tests",
}

# Tables that MUST NOT exist after init_db().
BANNED_TABLES = {
    "daily_cards",
    "daily_progress",
    "daily_card_sessions",
}


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _closed_conn(path: str):
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _table_names(path: str) -> set[str]:
    with _closed_conn(path) as conn:
        return {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }


def _column_names(path: str, table: str) -> set[str]:
    with _closed_conn(path) as conn:
        return {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }


def _index_contract(conn: sqlite3.Connection, table: str) -> dict[str, tuple]:
    contract = {}
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        columns = tuple(
            item["name"]
            for item in conn.execute(f"PRAGMA index_info({row['name']})").fetchall()
        )
        contract[row["name"]] = (
            row["unique"],
            row["origin"],
            row["partial"],
            columns,
        )
    return contract


def assert_schema_complete(testcase, path: str) -> None:
    """Shared assertion for the migration template.

    Usage:
        assert_schema_complete(self, temp_db_path)
    Verifies expected tables/columns exist and banned columns are absent.
    """
    tables = _table_names(path)
    missing_tables = EXPECTED_TABLES - tables
    testcase.assertEqual(
        missing_tables,
        set(),
        f"Missing tables after init_db(): {sorted(missing_tables)}",
    )

    present_banned_tables = BANNED_TABLES & tables
    testcase.assertEqual(
        present_banned_tables,
        set(),
        f"Banned tables still present: {sorted(present_banned_tables)}",
    )

    for table, expected in EXPECTED_COLUMNS.items():
        if table not in tables:
            continue
        columns = _column_names(path, table)
        missing = expected - columns
        testcase.assertEqual(
            missing,
            set(),
            f"Missing columns in {table}: {sorted(missing)}",
        )

    for table, banned in BANNED_COLUMNS.items():
        if table not in tables:
            continue
        columns = _column_names(path, table)
        present = banned & columns
        testcase.assertEqual(
            present,
            set(),
            f"Banned columns still present in {table}: {sorted(present)}",
        )


def build_prior_schema(path: str, *, migration_done: bool = True) -> None:
    """Create the prior-schema database that init_db() must upgrade from.

    This is the schema BEFORE the latest migration. New migrations extend this
    with the newest tables/columns so the upgrade path is always exercised.
    """
    with _closed_conn(path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                target_lang TEXT,
                goal TEXT,
                plan TEXT DEFAULT 'free',
                streak INTEGER DEFAULT 0,
                last_active_date TEXT,
                onboarded INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE saved_words (
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
                retry_at TEXT,
                srs_retry_attempts INTEGER NOT NULL DEFAULT 0,
                added_at TEXT,
                first_exposure_done INTEGER DEFAULT 0,
                stability REAL DEFAULT 0.0,
                difficulty REAL DEFAULT 5.0,
                entry_source TEXT DEFAULT 'manual'
            );
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE daily_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_date TEXT,
                card_index INTEGER,
                card_data TEXT,
                UNIQUE(user_id, card_date, card_index)
            );
            CREATE TABLE daily_progress (
                user_id INTEGER,
                card_date TEXT,
                next_index INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, card_date)
            );
            CREATE TABLE daily_card_sessions (
                user_id INTEGER,
                card_date TEXT,
                target_lang TEXT,
                goal TEXT,
                level TEXT,
                created_at TEXT,
                PRIMARY KEY(user_id, card_date)
            );
            CREATE TABLE llm_requests (
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
                cost_usd REAL NOT NULL,
                cost_toman REAL NOT NULL
            );
            CREATE TABLE review_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                grade INTEGER,
                activity_type TEXT,
                grade_source TEXT,
                raw_signal TEXT,
                response_time_ms INTEGER,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute("INSERT INTO settings(key, value) VALUES ('ai_primary_preset', 'x')")
        if migration_done:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES "
                "('fsrs_migration_done', '1')"
            )
        conn.commit()


class MigrationGuardTests(unittest.TestCase):
    """The migration-completeness template, exercised against the live schema."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema_db = db_schema.DB_PATH
        self.fresh = os.path.join(self.tempdir.name, "fresh.sqlite")
        self.upgraded = os.path.join(self.tempdir.name, "upgraded.sqlite")
        db_module.DB_PATH = self.fresh
        db_schema.DB_PATH = self.fresh

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema_db
        self.tempdir.cleanup()

    def test_fresh_db_matches_expected_schema(self):
        db_module.init_db()
        assert_schema_complete(self, self.fresh)

    def test_upgraded_db_matches_expected_schema(self):
        build_prior_schema(self.upgraded)
        # Point the live connection at the prior-schema DB and upgrade it.
        db_module.DB_PATH = self.upgraded
        db_schema.DB_PATH = self.upgraded
        db_module.init_db()
        assert_schema_complete(self, self.upgraded)

    def test_upgrade_preserves_existing_rows(self):
        """The upgrade path must not wipe data present in the prior schema."""
        build_prior_schema(self.upgraded)
        with _closed_conn(self.upgraded) as conn:
            conn.execute(
                "INSERT INTO users(user_id, username, target_lang, goal, plan, "
                "streak, last_active_date, onboarded, created_at) VALUES "
                "(1, 'keep_me', 'en', 'general', 'silver', 7, '2026-08-08', "
                "1, '2026-08-01T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO saved_words("
                "user_id, word, lang, normalized_word, card_data, interval_idx, "
                "next_review, review_status, review_requested_at, retry_at, "
                "srs_retry_attempts, added_at, first_exposure_done, stability, "
                "difficulty, entry_source) VALUES "
                "(1, 'retain', 'en', 'retain', ?, 4, '2026-08-10', 'pending', "
                "'2026-08-09T00:00:00+00:00', '2026-08-09T01:00:00+00:00', "
                "2, '2026-08-09T00:00:00+00:00', 1, 8.5, 6.25, 'manual')",
                ('{"word":"retain","fa_meaning":"keep"}',),
            )
            conn.execute(
                "INSERT INTO review_events("
                "word_id, user_id, outcome, grade, activity_type, grade_source, "
                "raw_signal, response_time_ms, created_at) VALUES "
                "(1, 1, 'recalled', 3, 'srs_review', 'direct_button', "
                "'{\"button_value\":3}', 1200, '2026-08-09T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO llm_requests("
                "request_id, created_at, request_date, user_id, plan, "
                "request_kind, model, outcome, prompt_tokens, completion_tokens, "
                "total_tokens, cost_usd, cost_toman) VALUES "
                "('req-keep', '2026-08-09T00:00:00+00:00', '2026-08-09', 1, "
                "'silver', 'card', 'model-keep', 'success', 100, 50, 150, "
                "0.001, 85.0)"
            )

            retained_tables = (
                "users",
                "saved_words",
                "settings",
                "llm_requests",
                "review_events",
            )
            retained_columns = {}
            retained_schema = {}
            retained_rows = {}
            retained_indexes = {}
            for table in retained_tables:
                table_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
                columns = [
                    row["name"]
                    for row in table_info
                    if row["name"] != "interval_idx"
                ]
                retained_columns[table] = columns
                retained_schema[table] = {
                    row["name"]: (
                        row["type"],
                        row["notnull"],
                        row["dflt_value"],
                        row["pk"],
                    )
                    for row in table_info
                    if row["name"] != "interval_idx"
                }
                retained_rows[table] = [
                    tuple(row[column] for column in columns)
                    for row in conn.execute(f"SELECT * FROM {table}").fetchall()
                ]
                retained_indexes[table] = {
                    name: signature
                    for name, signature in _index_contract(conn, table).items()
                    if "interval_idx" not in signature[3]
                }
        db_module.DB_PATH = self.upgraded
        db_schema.DB_PATH = self.upgraded
        db_module.init_db()
        with _closed_conn(self.upgraded) as conn:
            for table in retained_tables:
                after_info = {
                    row["name"]: (
                        row["type"],
                        row["notnull"],
                        row["dflt_value"],
                        row["pk"],
                    )
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for column, signature in retained_schema[table].items():
                    self.assertEqual(after_info[column], signature)

                columns = retained_columns[table]
                selected = ", ".join(columns)
                after_rows = [
                    tuple(row[column] for column in columns)
                    for row in conn.execute(
                        f"SELECT {selected} FROM {table}"
                    ).fetchall()
                ]
                for row in retained_rows[table]:
                    self.assertIn(row, after_rows)

                after_indexes = _index_contract(conn, table)
                for name, signature in retained_indexes[table].items():
                    self.assertEqual(after_indexes[name], signature)

    def test_unmigrated_daily_schema_aborts_without_deleting(self):
        build_prior_schema(self.upgraded, migration_done=False)
        db_module.DB_PATH = self.upgraded
        db_schema.DB_PATH = self.upgraded

        with self.assertRaisesRegex(RuntimeError, "fsrs_migration_done"):
            db_module.init_db()

        self.assertTrue(BANNED_TABLES.issubset(_table_names(self.upgraded)))
        self.assertIn("interval_idx", _column_names(self.upgraded, "saved_words"))

    def test_nonfinal_migration_flag_aborts_without_deleting(self):
        build_prior_schema(self.upgraded)
        with _closed_conn(self.upgraded) as conn:
            conn.execute(
                "UPDATE settings SET value='0' WHERE key='fsrs_migration_done'"
            )
        db_module.DB_PATH = self.upgraded
        db_schema.DB_PATH = self.upgraded

        with self.assertRaisesRegex(RuntimeError, "fsrs_migration_done"):
            db_module.init_db()

        self.assertTrue(BANNED_TABLES.issubset(_table_names(self.upgraded)))
        self.assertIn("interval_idx", _column_names(self.upgraded, "saved_words"))

    def test_template_flags_banned_column(self):
        """The template's absence check works: a banned column that still
        exists must be reported, not silently accepted."""
        db_module.init_db()
        with _closed_conn(self.fresh) as conn:
            conn.execute("ALTER TABLE saved_words ADD COLUMN fake_banned TEXT")
            conn.commit()

        original = dict(BANNED_COLUMNS)
        BANNED_COLUMNS["saved_words"] = {"fake_banned"}
        try:
            with self.assertRaises(AssertionError):
                assert_schema_complete(self, self.fresh)
        finally:
            BANNED_COLUMNS.clear()
            BANNED_COLUMNS.update(original)

    def test_template_flags_banned_table(self):
        db_module.init_db()
        with _closed_conn(self.fresh) as conn:
            conn.execute("CREATE TABLE fake_banned (id INTEGER)")

        original = set(BANNED_TABLES)
        BANNED_TABLES.add("fake_banned")
        try:
            with self.assertRaises(AssertionError):
                assert_schema_complete(self, self.fresh)
        finally:
            BANNED_TABLES.clear()
            BANNED_TABLES.update(original)


if __name__ == "__main__":
    unittest.main()
