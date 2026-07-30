import os
import sqlite3
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema


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

    # ---- Migration from prior schema ----

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
            conn.commit()
        finally:
            conn.close()

        with db_module.get_conn() as conn:
            db_module._init_ai_presets_table(conn)

        cols = self._get_columns("ai_presets")
        for col_name in ("input_cost_per_million", "output_cost_per_million", "group_label", "in_fallback_chain"):
            self.assertIn(col_name, cols, f"Column {col_name} not added by migration")
        llm_cols = self._get_columns("llm_requests")
        self.assertIn("preset_name", llm_cols, "preset_name not added to llm_requests")


if __name__ == "__main__":
    unittest.main()
