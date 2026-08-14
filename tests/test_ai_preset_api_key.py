"""Tests for the ai_presets api_key R3 fix.

Covers:
- R3A: the idempotent schema migration that prefixes "$" to the historical
  bare "HpOF_API_KEY" stored on the 4 HP presets (on an upgrade from the
  prior schema AND on a fresh DB), without touching other keys.
- R3B: resolve_api_key warn-on-invalid hardening (logs on a mis-stored bare
  env-name, stays silent for valid "$ENV" refs and plausible literal keys,
  never throws).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema
from services.ai import ai_presets


_HP_NAMES = ("g3_6_f_HP", "g3_5_f_HP", "g3_5_FL_HP", "g3_1_FL_HP")


class _ScratchDbTestCase(unittest.TestCase):
    """Isolate each test against its own scratch SQLite DB."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db_module.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db_module.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path

    def tearDown(self):
        db_module.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()


class PresetApiKeyMigrationTest(_ScratchDbTestCase):
    """R3A — the idempotent "$" prefix migration."""

    def _seed_bare_hp_keys(self):
        """Create the ai_presets table and insert the HP presets with the
        historical bare env-name value (as found in production before R3A)."""
        conn = sqlite3.connect(self.new_path)
        try:
            conn.execute(
                "CREATE TABLE ai_presets ("
                "name TEXT PRIMARY KEY, base_url TEXT, model TEXT, "
                "api_key TEXT NOT NULL DEFAULT '', is_custom INTEGER DEFAULT 0)"
            )
            for name in _HP_NAMES:
                conn.execute(
                    "INSERT INTO ai_presets(name, base_url, model, api_key, is_custom) "
                    "VALUES (?, '', '', 'HpOF_API_KEY', 1)",
                    (name,),
                )
            conn.commit()
        finally:
            conn.close()

    def test_upgrade_prefixes_bare_hp_keys(self):
        """Migrating a DB that has the bare 'HpOF_API_KEY' must prefix '$'."""
        self._seed_bare_hp_keys()
        db_module.init_db()
        with db_module.get_conn() as conn:
            rows = conn.execute(
                f"SELECT api_key FROM ai_presets WHERE name IN "
                f"({','.join('?' for _ in _HP_NAMES)})",
                _HP_NAMES,
            ).fetchall()
        for row in rows:
            self.assertEqual(row["api_key"], "$HpOF_API_KEY")

    def test_migration_is_idempotent(self):
        """Running init_db twice must not double-prefix ('$' + '$')."""
        self._seed_bare_hp_keys()
        db_module.init_db()
        db_module.init_db()
        with db_module.get_conn() as conn:
            rows = conn.execute(
                f"SELECT api_key FROM ai_presets WHERE name IN "
                f"({','.join('?' for _ in _HP_NAMES)})",
                _HP_NAMES,
            ).fetchall()
        for row in rows:
            self.assertEqual(row["api_key"], "$HpOF_API_KEY")

    def test_fresh_db_has_no_autoseeded_presets(self):
        """Phase 4: a fresh DB must NOT auto-seed any preset rows; the admin
        panel is the sole source of preset configuration."""
        db_module.init_db()
        with db_module.get_conn() as conn:
            rows = conn.execute("SELECT COUNT(*) as c FROM ai_presets").fetchone()
        self.assertEqual(rows["c"], 0, "fresh DB must not auto-seed presets")

    def test_migration_does_not_touch_other_keys(self):
        """Other presets (custom literal keys, ELI/GAPGPT '$' refs) must be
        left untouched by the migration."""
        conn = sqlite3.connect(self.new_path)
        try:
            conn.execute(
                "CREATE TABLE ai_presets ("
                "name TEXT PRIMARY KEY, base_url TEXT, model TEXT, "
                "api_key TEXT NOT NULL DEFAULT '', is_custom INTEGER DEFAULT 0)"
            )
            conn.execute(
                "INSERT INTO ai_presets(name, api_key, is_custom) "
                "VALUES ('custom_lit', 'sk-abcdefghijklmnopqrstuvwxyz0123456789', 1)"
            )
            conn.execute(
                "INSERT INTO ai_presets(name, api_key, is_custom) "
                "VALUES ('g3_6_f_ELI', '$ELI_API_KEY', 1)"
            )
            conn.execute(
                "INSERT INTO ai_presets(name, api_key, is_custom) "
                "VALUES ('gapgpt_G3_1F_L', '$GAPGPT_API_KEY', 0)"
            )
            conn.commit()
        finally:
            conn.close()

        db_module.init_db()
        with db_module.get_conn() as conn:
            custom_lit = conn.execute(
                "SELECT api_key FROM ai_presets WHERE name='custom_lit'"
            ).fetchone()["api_key"]
            eli = conn.execute(
                "SELECT api_key FROM ai_presets WHERE name='g3_6_f_ELI'"
            ).fetchone()["api_key"]
            gap = conn.execute(
                "SELECT api_key FROM ai_presets WHERE name='gapgpt_G3_1F_L'"
            ).fetchone()["api_key"]
        self.assertTrue(custom_lit.startswith("sk-"))
        self.assertEqual(eli, "$ELI_API_KEY")
        self.assertEqual(gap, "$GAPGPT_API_KEY")


class ResolveApiKeyHardeningTest(_ScratchDbTestCase):
    """R3B — warn-on-invalid guard in resolve_api_key."""

    def test_env_ref_resolves(self):
        os.environ["HZ_TEST_KEY"] = "sekrit"
        self.addCleanup(os.environ.pop, "HZ_TEST_KEY", None)
        self.assertEqual(ai_presets.resolve_api_key("$HZ_TEST_KEY"), "sekrit")

    def test_valid_literal_key_no_warning(self):
        with self.assertNoLogs(ai_presets.log.name, level=logging.WARNING):
            self.assertEqual(
                ai_presets.resolve_api_key("sk-abcdefghijklmnopqrstuvwxyz0123456789"),
                "sk-abcdefghijklmnopqrstuvwxyz0123456789",
            )

    def test_long_token_literal_no_warning(self):
        long_key = "ix_" + "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0"
        with self.assertNoLogs(ai_presets.log.name, level=logging.WARNING):
            self.assertEqual(ai_presets.resolve_api_key(long_key), long_key)

    def test_bare_env_name_warns_but_returns(self):
        """A bare 'HpOF_API_KEY' (no '$') must warn but still return the raw
        value (no throw), preserving fallback-chain behavior."""
        with self.assertLogs(ai_presets.log.name, level=logging.WARNING) as cm:
            result = ai_presets.resolve_api_key("HpOF_API_KEY")
        self.assertEqual(result, "HpOF_API_KEY")
        self.assertTrue(any("HpOF_API_KEY" in m for m in cm.output))
        self.assertTrue(any("not a '$ENV' reference" in m for m in cm.output))

    def test_empty_returns_empty_no_warning(self):
        with self.assertNoLogs(ai_presets.log.name, level=logging.WARNING):
            self.assertEqual(ai_presets.resolve_api_key(""), "")
            self.assertEqual(ai_presets.resolve_api_key({"api_key": ""}), "")


if __name__ == "__main__":
    unittest.main()
