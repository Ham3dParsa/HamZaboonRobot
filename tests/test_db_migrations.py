import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import config

from services import db as db_module
from services.db import schema as db_schema
from services.db import key_crypto


TEST_MASTER_KEY = "sd4H8UUr5ONYISGXcx468OQwFaUxaktNGGTPs9TBESg="


class AiPresetsMigrationsTests(unittest.TestCase):
    """Test the migration of new columns in _init_ai_presets_table."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db_module.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db_module.DB_PATH = new_path
        db_schema.DB_PATH = new_path

    def tearDown(self):
        db_module.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()

    def _get_columns(self, table_name):
        conn = sqlite3.connect(db_module.DB_PATH)
        try:
            columns = {
                row[1]: {"type": row[2], "notnull": row[3], "dflt_value": row[4]}
                for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            return columns
        finally:
            conn.close()

    # ---- Fresh DB tests ----

    def test_fresh_db_has_all_new_columns(self):
        db_module.init_db()
        cols = self._get_columns("ai_presets")
        for col_name in ("input_cost_per_million", "output_cost_per_million", "group_label", "in_fallback_chain"):
            self.assertIn(col_name, cols, f"Missing column {col_name}")
        llm_cols = self._get_columns("llm_requests")
        self.assertIn("preset_name", llm_cols)

    def test_cost_columns_nullable(self):
        db_module.init_db()
        cols = self._get_columns("ai_presets")
        self.assertEqual(cols["input_cost_per_million"]["notnull"], 0)
        self.assertIsNone(cols["input_cost_per_million"]["dflt_value"])
        self.assertEqual(cols["output_cost_per_million"]["notnull"], 0)
        self.assertIsNone(cols["output_cost_per_million"]["dflt_value"])

    def test_group_label_default_empty(self):
        db_module.init_db()
        cols = self._get_columns("ai_presets")
        self.assertEqual(cols["group_label"]["dflt_value"], "''")

    def test_in_fallback_chain_default_one(self):
        db_module.init_db()
        cols = self._get_columns("ai_presets")
        self.assertEqual(cols["in_fallback_chain"]["dflt_value"], "1")

    def test_llm_requests_preset_name_column(self):
        db_module.init_db()
        cols = self._get_columns("llm_requests")
        self.assertIn("preset_name", cols)
        self.assertEqual(cols["preset_name"]["notnull"], 0)

    # ---- Plans table (admin-editable plan specs) ----

    def test_fresh_db_has_plans_table_with_all_columns(self):
        db_module.init_db()
        cols = self._get_columns("plans")
        for col_name in (
            "name", "display_name", "price", "query_quota",
            "max_sessions", "cards_per_session", "is_active", "sort_order",
        ):
            self.assertIn(col_name, cols, f"Missing plans column {col_name}")

    def test_fresh_db_seeds_default_plans(self):
        db_module.init_db()
        with db_module.get_conn() as conn:
            rows = conn.execute(
                "SELECT name, query_quota, max_sessions, cards_per_session "
                "FROM plans ORDER BY sort_order"
            ).fetchall()
        expected = {
            "free": (2, 2, 3),
            "bronze": (4, 3, 3),
            "silver": (7, 3, 5),
            "gold": (12, 4, 7),
            "emerald": (20, 5, 9),
        }
        self.assertEqual({r["name"] for r in rows}, set(expected))
        for row in rows:
            self.assertEqual(
                (row["query_quota"], row["max_sessions"], row["cards_per_session"]),
                expected[row["name"]],
            )

    def test_plans_seed_does_not_overwrite_admin_edits(self):
        db_module.init_db()
        db_module.upsert_plan(
            "free", "رایگان", 0, query_quota=99, max_sessions=1,
            cards_per_session=1,
        )
        with db_module.get_conn() as conn:
            db_module._init_plans_table(conn)
            row = conn.execute(
                "SELECT query_quota FROM plans WHERE name='free'"
            ).fetchone()
        self.assertEqual(row["query_quota"], 99, "re-init must not overwrite admin edits")

    def test_migration_adds_plans_table_to_prior_schema(self):
        conn = sqlite3.connect(db_module.DB_PATH)
        try:
            conn.execute("""
                CREATE TABLE ai_presets (
                    name TEXT PRIMARY KEY,
                    base_url TEXT,
                    model TEXT,
                    api_key TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()

        with db_module.get_conn() as conn:
            db_module._init_plans_table(conn)

        cols = self._get_columns("plans")
        for col_name in ("name", "display_name", "query_quota", "max_sessions",
                         "cards_per_session", "is_active", "sort_order"):
            self.assertIn(col_name, cols, f"plans missing column {col_name}")
        with db_module.get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM plans").fetchone()["c"]
        self.assertEqual(count, 5, "plans table should be seeded on migration")

    def test_migration_from_prior_schema(self):
        conn = sqlite3.connect(db_module.DB_PATH)
        try:
            conn.execute("""
                CREATE TABLE ai_presets (
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
                )
            """)
            conn.execute("""
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
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('ai_primary_preset', 'gapgpt_gemini_lite')")
            conn.execute(
                "INSERT INTO ai_presets(name, base_url, model, api_key, is_custom, priority) "
                "VALUES ('legacy_hp', 'https://x', 'gpt-test', '$HpOF_API_KEY', 1, 3)"
            )
            conn.commit()
        finally:
            conn.close()

        with db_module.get_conn() as conn:
            db_module._init_ai_presets_table(conn)

        cols = self._get_columns("ai_presets")
        for col_name in ("input_cost_per_million", "output_cost_per_million", "group_label", "in_fallback_chain"):
            self.assertIn(col_name, cols, f"Column {col_name} not added by migration")
        # Phase 4: the obsolete is_custom column must be dropped on upgrade,
        # and every prior row must survive (becoming an ordinary preset).
        self.assertNotIn("is_custom", cols, "is_custom column must be dropped by migration")
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT name, base_url, model, api_key, priority FROM ai_presets WHERE name='legacy_hp'"
            ).fetchone()
        self.assertIsNotNone(row, "prior-schema row must be preserved by the migration")
        self.assertEqual(row["base_url"], "https://x")
        self.assertEqual(row["priority"], 3)
        llm_cols = self._get_columns("llm_requests")
        self.assertIn("preset_name", llm_cols, "preset_name not added to llm_requests")

    def test_rebuild_coalesces_legacy_null_api_key(self):
        # A prior schema could store a NULL api_key (nullable column). The Phase 4
        # rebuild rewrites ai_presets with api_key TEXT NOT NULL, so the migration
        # must COALESCE any legacy NULL to '' rather than raise IntegrityError.
        conn = sqlite3.connect(db_module.DB_PATH)
        try:
            conn.execute("""
                CREATE TABLE ai_presets (
                    name TEXT PRIMARY KEY,
                    base_url TEXT,
                    model TEXT,
                    api_key TEXT,
                    priority INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1,
                    is_custom INTEGER DEFAULT 0
                )
            """)
            conn.execute(
                "INSERT INTO ai_presets(name, base_url, model, api_key, priority) "
                "VALUES ('null_key', 'https://x', 'gpt-test', NULL, 2)"
            )
            conn.execute("""
                CREATE TABLE llm_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT
                )
            """)
            conn.commit()
        finally:
            conn.close()

        with db_module.get_conn() as conn:
            db_module._init_ai_presets_table(conn)

        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT name, api_key, priority FROM ai_presets WHERE name='null_key'"
            ).fetchone()
        self.assertIsNotNone(row, "legacy NULL-api_key row must survive the rebuild")
        self.assertEqual(row["api_key"], "", "legacy NULL api_key must be coerced to ''")
        self.assertEqual(row["priority"], 2, "other columns must be preserved")
        cols = self._get_columns("ai_presets")
        self.assertNotIn("is_custom", cols, "is_custom must be dropped by the rebuild")

    def test_fresh_db_saved_words_entry_source_default(self):
        db_module.init_db()
        cols = self._get_columns("saved_words")
        self.assertIn("entry_source", cols)
        self.assertEqual(cols["entry_source"]["dflt_value"], "'manual'")

    def test_upgrade_prior_schema_adds_entry_source_preserves_rows(self):
        conn = sqlite3.connect(db_module.DB_PATH)
        try:
            conn.execute("""
                CREATE TABLE saved_words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    word TEXT,
                    lang TEXT,
                    normalized_word TEXT
                )
            """)
            conn.execute(
                "INSERT INTO saved_words(user_id, word, lang, normalized_word) "
                "VALUES (1, 'hello', 'en', 'hello')"
            )
            conn.commit()
        finally:
            conn.close()

        db_module.init_db()

        cols = self._get_columns("saved_words")
        self.assertIn("entry_source", cols, "entry_source not added on upgrade")
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT word, entry_source FROM saved_words WHERE user_id=1"
            ).fetchone()
        self.assertEqual(row["word"], "hello", "existing row must not be lost on upgrade")
        self.assertEqual(row["entry_source"], "manual", "existing rows default to manual")

    def test_add_saved_word_entry_source_writes_value(self):
        db_module.init_db()
        db_module.create_user_if_needed(1, "learner")
        db_module.add_saved_word(1, "hello", "en", {"word": "hello"}, entry_source="manual")
        db_module.add_saved_word(1, "auto_word", "en", {"word": "auto_word"}, entry_source="auto")
        with db_module.get_conn() as conn:
            rows = conn.execute(
                "SELECT word, entry_source FROM saved_words ORDER BY word"
            ).fetchall()
        self.assertEqual(rows[0]["entry_source"], "auto")
        self.assertEqual(rows[1]["entry_source"], "manual")


class Phase5KeyEncryptionMigrationTests(unittest.TestCase):
    """R3: init_db encrypts legacy plaintext/$ENV API keys at rest.

    The Phase 5 migration must convert any still-plaintext or "$ENV" reference
    stored in ai_presets.api_key, preset_groups.api_key, or settings.ai_api_key
    into Fernet ciphertext on startup, resolve $ENV refs to real env values,
    stay idempotent on already-encrypted tokens, and never destroy values when
    no master key is configured (fail-closed).
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db_module.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db_module.DB_PATH = new_path
        db_schema.DB_PATH = new_path

    def tearDown(self):
        db_module.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()

    def _with_master_key(self, key: str = TEST_MASTER_KEY):
        p = mock.patch.object(config, "AI_MASTER_KEY", key)
        p.start()
        self.addCleanup(p.stop)

    def _stored_preset_key(self, name: str) -> str:
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT api_key FROM ai_presets WHERE name=?", (name,)
            ).fetchone()
        return row["api_key"] if row else None

    def _stored_setting(self) -> str:
        with db_module.get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='ai_api_key'"
            ).fetchone()
        return row["value"] if row else None

    def _set_plaintext_keys(self, preset_name: str, preset_key: str, setting_key: str):
        with db_module.get_conn() as conn:
            conn.execute(
                "UPDATE ai_presets SET api_key=? WHERE name=?",
                (preset_key, preset_name),
            )
            conn.execute(
                "INSERT INTO settings(key, value) VALUES ('ai_api_key', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (setting_key,),
            )
            conn.commit()

    def _create_preset(self, name: str = "p1") -> str:
        db_module.set_preset(name, base_url="http://example.test", model="m", enabled=1)
        return name

    def test_literal_preset_and_setting_are_encrypted(self):
        self._with_master_key()
        db_module.init_db()
        name = self._create_preset()
        self._set_plaintext_keys(
            name, "sk-literal-secret-9876543210", "sk-settings-secret-123456789"
        )
        db_module.init_db()

        stored = self._stored_preset_key(name)
        self.assertNotEqual(stored, "sk-literal-secret-9876543210")
        self.assertTrue(stored.startswith("v1:"))
        self.assertEqual(key_crypto.decrypt_secret(stored), "sk-literal-secret-9876543210")

        setting = self._stored_setting()
        self.assertTrue(setting.startswith("v1:"))
        self.assertEqual(key_crypto.decrypt_secret(setting), "sk-settings-secret-123456789")

    def test_env_reference_is_resolved_then_encrypted(self):
        self._with_master_key()
        os.environ["PHASE5_TEST_ENV_KEY"] = "env-secret-xyz-987654"
        self.addCleanup(os.environ.pop, "PHASE5_TEST_ENV_KEY", None)
        db_module.init_db()
        name = self._create_preset()
        self._set_plaintext_keys(name, "$PHASE5_TEST_ENV_KEY", "$PHASE5_TEST_ENV_KEY")
        db_module.init_db()

        stored = self._stored_preset_key(name)
        self.assertNotEqual(stored, "$PHASE5_TEST_ENV_KEY")
        self.assertEqual(key_crypto.decrypt_secret(stored), "env-secret-xyz-987654")

    def test_already_encrypted_token_is_not_re_encrypted(self):
        self._with_master_key()
        db_module.init_db()
        name = self._create_preset()
        self._set_plaintext_keys(name, "sk-literal-secret-9876543210", "sk-sec")
        db_module.init_db()
        first = self._stored_preset_key(name)
        self.assertTrue(first.startswith("v1:"))
        db_module.init_db()
        second = self._stored_preset_key(name)
        self.assertEqual(first, second)

    def test_missing_master_key_does_not_destroy_values(self):
        self._with_master_key("")
        db_module.init_db()
        name = self._create_preset()
        self._set_plaintext_keys(name, "sk-literal-secret-9876543210", "sk-sec")
        db_module.init_db()
        stored = self._stored_preset_key(name)
        self.assertEqual(stored, "sk-literal-secret-9876543210")


if __name__ == "__main__":
    unittest.main()
