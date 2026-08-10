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
        "interval_idx",  # NOTE: moves to BANNED_COLUMNS when FSRS drops it
        "next_review",
        "review_status",
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
    # The FSRS migration drops interval_idx from saved_words; uncomment when
    # that lands. Keeping this set empty means "nothing must be removed yet".
    # "saved_words": {"interval_idx"},
}

# Tables that must exist after init_db().
EXPECTED_TABLES = {
    "users",
    "saved_words",
    "settings",
    "daily_cards",
    "daily_progress",
    "daily_card_sessions",
    "query_results",
    "grammar_tips",
    "llm_requests",
    "review_events",
    "ai_presets",
    "preset_hourly_usage",
    "config_tests",
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


def build_prior_schema(path: str) -> None:
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
                interval_idx INTEGER DEFAULT 0,
                next_review TEXT,
                added_at TEXT
            );
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT
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
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute("INSERT INTO settings(key, value) VALUES ('ai_primary_preset', 'x')")
        conn.commit()


def build_origin_backfill_schema(path: str) -> None:
    """Create a post-FSRS, pre-origin-backfill database."""
    build_prior_schema(path)
    with _closed_conn(path) as conn:
        conn.executescript(
            """
            ALTER TABLE saved_words ADD COLUMN normalized_word TEXT;
            ALTER TABLE saved_words ADD COLUMN card_data TEXT;
            ALTER TABLE saved_words ADD COLUMN entry_source TEXT DEFAULT 'manual';
            CREATE TABLE daily_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_date TEXT,
                card_index INTEGER,
                card_data TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO users(user_id, username, target_lang, onboarded) "
            "VALUES (1, 'learner', 'en', 1)"
        )
        conn.execute(
            "INSERT INTO saved_words("
            "user_id, word, lang, normalized_word, card_data, entry_source) "
            "VALUES (1, 'Daily   Word', 'en', 'daily   word', ?, 'manual')",
            ('{"word":"Daily   Word"}',),
        )
        conn.execute(
            "INSERT INTO saved_words("
            "user_id, word, lang, normalized_word, card_data, entry_source) "
            "VALUES (1, 'manual word', 'en', 'manual word', ?, 'manual')",
            ('{"word":"manual word"}',),
        )
        conn.execute(
            "INSERT INTO daily_cards(user_id, card_date, card_index, card_data) "
            "VALUES (1, '2026-08-10', 0, ?)",
            ('{"word":"daily word"}',),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES ('fsrs_migration_done', '1')"
        )


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
                "INSERT INTO users(user_id, username) VALUES (1, 'keep_me')"
            )
        db_module.DB_PATH = self.upgraded
        db_schema.DB_PATH = self.upgraded
        db_module.init_db()
        with _closed_conn(self.upgraded) as conn:
            row = conn.execute(
                "SELECT username FROM users WHERE user_id=1"
            ).fetchone()
        self.assertEqual(row["username"], "keep_me")

    def test_origin_backfill_tags_daily_matches_once(self):
        build_origin_backfill_schema(self.upgraded)
        db_module.DB_PATH = self.upgraded
        db_schema.DB_PATH = self.upgraded
        with _closed_conn(self.upgraded) as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES "
                "('entry_source_backfilled', '0')"
            )

        db_module.init_db()

        with _closed_conn(self.upgraded) as conn:
            sources = {
                row["normalized_word"]: row["entry_source"]
                for row in conn.execute(
                    "SELECT normalized_word, entry_source FROM saved_words "
                    "ORDER BY normalized_word"
                ).fetchall()
            }
            flag = conn.execute(
                "SELECT value FROM settings WHERE key='entry_source_backfilled'"
            ).fetchone()
        self.assertEqual(
            sources,
            {"daily   word": "legacy_daily", "manual word": "manual"},
        )
        self.assertEqual(flag["value"], "1")

        with _closed_conn(self.upgraded) as conn:
            conn.execute(
                "INSERT INTO saved_words("
                "user_id, word, lang, normalized_word, entry_source) "
                "VALUES (1, 'Later Word', 'en', 'later word', 'manual')"
            )
            conn.execute(
                "INSERT INTO daily_cards(user_id, card_date, card_index, card_data) "
                "VALUES (1, '2026-08-11', 0, ?)",
                ('{"word":"Later Word"}',),
            )
        db_module.init_db()
        with _closed_conn(self.upgraded) as conn:
            sources_after_repeat = {
                row["normalized_word"]: row["entry_source"]
                for row in conn.execute(
                    "SELECT normalized_word, entry_source FROM saved_words "
                    "ORDER BY normalized_word"
                ).fetchall()
            }
        self.assertEqual(
            sources_after_repeat,
            {**sources, "later word": "manual"},
        )

    def test_origin_backfill_matches_the_card_language_only(self):
        """A word saved under two languages is tagged only for the language
        the daily card was generated in."""
        build_origin_backfill_schema(self.upgraded)
        db_module.DB_PATH = self.upgraded
        db_schema.DB_PATH = self.upgraded
        with _closed_conn(self.upgraded) as conn:
            conn.execute(
                "INSERT INTO saved_words("
                "user_id, word, lang, normalized_word, entry_source) "
                "VALUES (1, 'Gift', 'en', 'gift', 'manual')"
            )
            conn.execute(
                "INSERT INTO saved_words("
                "user_id, word, lang, normalized_word, entry_source) "
                "VALUES (1, 'Gift', 'de', 'gift', 'manual')"
            )
            conn.execute(
                "INSERT INTO daily_cards(user_id, card_date, card_index, card_data) "
                "VALUES (1, '2026-08-12', 0, ?)",
                ('{"word":"gift"}',),
            )

        db_module.init_db()

        with _closed_conn(self.upgraded) as conn:
            sources = {
                (row["normalized_word"], row["lang"]): row["entry_source"]
                for row in conn.execute(
                    "SELECT normalized_word, lang, entry_source FROM saved_words"
                ).fetchall()
            }
        self.assertEqual(sources[("gift", "en")], "legacy_daily")
        self.assertEqual(sources[("gift", "de")], "manual")

    def test_origin_backfill_marks_empty_daily_table_complete(self):
        db_module.init_db()

        with _closed_conn(self.fresh) as conn:
            flag = conn.execute(
                "SELECT value FROM settings WHERE key='entry_source_backfilled'"
            ).fetchone()
        self.assertEqual(flag["value"], "1")

    def test_origin_backfill_keeps_partial_legacy_db_eligible_for_future_run(self):
        build_prior_schema(self.upgraded)
        db_module.DB_PATH = self.upgraded
        db_schema.DB_PATH = self.upgraded

        with self.assertLogs("services.db.schema", level="WARNING"):
            db_module.init_db()
        with self.assertLogs("services.db.schema", level="WARNING"):
            db_module.init_db()
        with _closed_conn(self.upgraded) as conn:
            flag = conn.execute(
                "SELECT value FROM settings WHERE key='entry_source_backfilled'"
            ).fetchone()
        self.assertIsNone(flag)

    def test_origin_backfill_treats_users_only_db_as_partial(self):
        with _closed_conn(self.upgraded) as conn:
            conn.execute(
                "CREATE TABLE users(user_id INTEGER PRIMARY KEY, username TEXT)"
            )
        db_module.DB_PATH = self.upgraded
        db_schema.DB_PATH = self.upgraded

        with self.assertLogs("services.db.schema", level="WARNING"):
            db_module.init_db()
        with _closed_conn(self.upgraded) as conn:
            flag = conn.execute(
                "SELECT value FROM settings WHERE key='entry_source_backfilled'"
            ).fetchone()
        self.assertIsNone(flag)

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


if __name__ == "__main__":
    unittest.main()
