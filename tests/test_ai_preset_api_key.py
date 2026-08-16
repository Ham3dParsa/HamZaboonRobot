"""Tests for the ai_presets api_key R3 fix and Phase 5 encryption.

Covers:
- R3A: the idempotent schema migration that prefixes "$" to the historical
  bare "HpOF_API_KEY" stored on the 4 HP presets (on an upgrade from the
  prior schema AND on a fresh DB), without touching other keys.
- Phase 5 (R4): resolve_api_key now decrypts the stored Fernet ciphertext.
  The "$ENV" indirection and the warn-on-invalid-literal guard are gone; a
  non-ciphertext value fails closed to ``''`` (never throws, never logs the
  literal key).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import config

from services import db as db_module
from services.db import schema as db_schema
from services.db import key_crypto
from services.ai import ai_presets


_HP_NAMES = ("g3_6_f_HP", "g3_5_f_HP", "g3_5_FL_HP", "g3_1_FL_HP")

TEST_MASTER_KEY = "sd4H8UUr5ONYISGXcx468OQwFaUxaktNGGTPs9TBESg="


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

    def setUp(self):
        super().setUp()
        # These legacy tests assert the raw "$ENV" prefix migration result.
        # Run them without a master key so the Phase 5 encryption migration is
        # skipped and the "$" value is left intact (the conftest provides a
        # default master key otherwise).
        self._patcher = mock.patch.object(config, "AI_MASTER_KEY", "")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

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


class ResolveApiKeyPhase5Test(_ScratchDbTestCase):
    """Phase 5 (R4) — resolve_api_key decrypts ciphertext, fails closed."""

    def _with_master_key(self, key: str = TEST_MASTER_KEY):
        p = mock.patch.object(config, "AI_MASTER_KEY", key)
        p.start()
        self.addCleanup(p.stop)

    def test_empty_returns_empty(self):
        self._with_master_key()
        self.assertEqual(ai_presets.resolve_api_key(""), "")
        self.assertEqual(ai_presets.resolve_api_key({"api_key": ""}), "")

    def test_ciphertext_roundtrips_to_plaintext(self):
        self._with_master_key()
        plain = "sk-real-secret-1234567890"
        token = key_crypto.encrypt_secret(plain)
        self.assertEqual(ai_presets.resolve_api_key(token), plain)
        self.assertEqual(ai_presets.resolve_api_key({"api_key": token}), plain)

    def test_plaintext_fails_closed_and_does_not_log_literal(self):
        self._with_master_key()
        plain = "sk-this-was-never-encrypted-12345"
        with self.assertLogs(key_crypto.log.name, level="WARNING") as cm:
            result = ai_presets.resolve_api_key(plain)
        self.assertEqual(result, "")
        self.assertFalse(any(plain in m for m in cm.output), "must not log the literal")

    def test_env_reference_no_longer_resolves(self):
        """The '$ENV' indirection is gone (R4): a '$' string is not ciphertext,
        so it fails closed to '' regardless of the environment."""
        self._with_master_key()
        os.environ["HZ_TEST_KEY"] = "sekrit"
        self.addCleanup(os.environ.pop, "HZ_TEST_KEY", None)
        self.assertEqual(ai_presets.resolve_api_key("$HZ_TEST_KEY"), "")

    def test_missing_master_key_returns_empty(self):
        self._with_master_key("")
        self.assertEqual(ai_presets.resolve_api_key("not-a-valid-token"), "")


class AiClientEnvFallbackTest(_ScratchDbTestCase):
    """BUG-2 — env-only deployments FAIL CLOSED (never fall back to plaintext).

    Client construction resolves the API key solely through the encrypt/decrypt
    seam (``db.resolve_preset_key``). When the active preset has no key and no
    ``AI_MASTER_KEY`` is configured, the resolution is empty — never a
    plaintext env-key fallback. The single ``create_client`` seam (which
    ``test_connection`` also routes through) must surface that empty key.
    """

    def _no_master_key(self):
        p = mock.patch.object(config, "AI_MASTER_KEY", "")
        p.start()
        self.addCleanup(p.stop)

    def test_env_only_resolves_fail_closed_without_master_key(self):
        self._no_master_key()
        db_module.init_db()
        import services.ai.ai as ai_module

        captor = mock.MagicMock()
        with mock.patch("services.ai.ai.OpenAI", captor):
            ai_module.create_client(
                {"base_url": "", "api_key": "", "model": "", "timeout_seconds": 30}
            )
        captor.assert_called_once()
        self.assertEqual(captor.call_args.kwargs["api_key"], "")
        # create_client is the only client seam; _client and test_connection
        # must route through it so the fail-closed contract holds everywhere.
        import inspect
        for name in ("_client", "test_connection"):
            src = inspect.getsource(getattr(ai_module, name))
            self.assertIn("create_client", src)

    def test_empty_override_falls_through_to_resolved_key(self):
        """A blank api_key_override must not bypass key resolution (review SUGGESTION)."""
        self._no_master_key()
        db_module.init_db()
        import services.ai.ai as ai_module

        resolved_key = "resolved-from-preset"
        with mock.patch.object(ai_module, "db") as db_mock:
            db_mock.get_active_preset.return_value = {
                "base_url": "",
                "model": "",
                "timeout_seconds": 30,
            }
            db_mock.resolve_preset_key.return_value = resolved_key
            captor = mock.MagicMock()
            with mock.patch("services.ai.ai.OpenAI", captor):
                # Empty override (""): treated as "not provided" -> resolved key.
                ai_module.create_client(
                    {"base_url": "", "api_key": "", "model": "", "timeout_seconds": 30},
                    api_key_override="",
                )
        captor.assert_called_once()
        self.assertEqual(captor.call_args.kwargs["api_key"], resolved_key)
        db_mock.resolve_preset_key.assert_called_once()


if __name__ == "__main__":
    unittest.main()
