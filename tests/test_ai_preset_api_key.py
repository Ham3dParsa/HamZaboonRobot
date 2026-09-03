"""Tests for zero-preset boot and Phase 5 encryption.

Covers:
- T4: a fresh DB boots with zero presets; a saved active preset survives
  restart even when stale legacy ``settings.ai_base_url``/``ai_model`` values
  are present (the retired reconcile block must never overwrite it).
- Phase 5 (R4): resolve_api_key now decrypts the stored Fernet ciphertext.
   A bare ``$ENV`` reference left in DB (migration skipped when no master key,
   BUG-B1) is resolved via ``key_crypto._resolve_env`` to the same value as
   the migration — set→value, unset→``''``; any other non-ciphertext fails
   closed to ``''`` (never throws, never logs the literal key).
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
    """T4 — zero presets on fresh boot; saved presets survive restart."""

    def test_fresh_db_has_no_autoseeded_presets(self):
        """Phase 4: a fresh DB must NOT auto-seed any preset rows; the admin
        panel is the sole source of preset configuration."""
        db_module.init_db()
        with db_module.get_conn() as conn:
            rows = conn.execute("SELECT COUNT(*) as c FROM ai_presets").fetchone()
        self.assertEqual(rows["c"], 0, "fresh DB must not auto-seed presets")

    def test_stale_legacy_settings_do_not_overwrite_active_preset(self):
        """T4 regression: a saved muse preset kept as active must survive a
        restart even when stale legacy settings.ai_base_url/ai_model values
        are present (the retired reconcile block must never copy them)."""
        db_module.init_db()
        db_module.set_preset(
            "muse",
            base_url="https://opencode.ai/zen/v1",
            model="muse-spark-1.3-contributor-free",
            enabled=1,
        )
        db_module.set_setting("ai_primary_preset", "muse")
        db_module.set_setting(
            "ai_base_url",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        db_module.set_setting("ai_model", "gemini-2.0-flash")
        db_module.init_db()
        preset = db_module.get_preset("muse")
        self.assertIsNotNone(preset, "saved muse preset must survive restart")
        self.assertEqual(preset["base_url"], "https://opencode.ai/zen/v1")
        self.assertEqual(
            preset["model"], "muse-spark-1.3-contributor-free"
        )


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

    def test_env_reference_resolves_via_key_crypto(self):
        """BUG-B1: a leftover '$ENV' in DB resolves via os.getenv (set→value, unset→'')."""
        self._with_master_key()
        os.environ["HZ_TEST_KEY"] = "sekrit"
        self.addCleanup(os.environ.pop, "HZ_TEST_KEY", None)
        self.assertEqual(ai_presets.resolve_api_key("$HZ_TEST_KEY"), "sekrit")
        os.environ.pop("HZ_TEST_KEY", None)
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
