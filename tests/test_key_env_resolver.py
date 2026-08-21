"""A2-4 / BUG-B1 — $ENV resolver alignment (RED)."""
import os
import unittest
from unittest import mock

import config
from services.db import key_crypto


class EnvResolverTests(unittest.TestCase):
    def test_decrypt_resolves_env_when_set(self):
        with mock.patch.dict(os.environ, {"TEST_ENV_KEY": "sk-env-secret-123456789"}):
            self.assertEqual(key_crypto.decrypt_secret("$TEST_ENV_KEY"), "sk-env-secret-123456789")

    def test_decrypt_resolves_env_when_unset_returns_empty(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_ENV_MISSING_XYZ", None)
            self.assertEqual(key_crypto.decrypt_secret("$TEST_ENV_MISSING_XYZ"), "")

    def test_decrypt_resolves_env_without_master_key(self):
        # Even without AI_MASTER_KEY, $ENV must still resolve (fail-closed only for v1:)
        with mock.patch.object(config, "AI_MASTER_KEY", ""):
            with mock.patch.dict(os.environ, {"TEST_ENV_KEY2": "sk-env2-123456789"}):
                self.assertEqual(key_crypto.decrypt_secret("$TEST_ENV_KEY2"), "sk-env2-123456789")

    def test_migration_and_runtime_agree_on_env(self):
        # Migration path: _encrypt resolves $ENV then encrypts; runtime path must give same plaintext
        import tempfile
        from services.db import schema as db_schema
        from services import db

        # Use a fresh DB in temp dir
        tmpdir = tempfile.TemporaryDirectory()
        orig_path = db.DB_PATH
        orig_schema_path = db_schema.DB_PATH
        try:
            db.DB_PATH = os.path.join(tmpdir.name, "test.sqlite")
            db_schema.DB_PATH = db.DB_PATH
            with mock.patch.object(config, "AI_MASTER_KEY", "sd4H8UUr5ONYISGXcx468OQwFaUxaktNGGTPs9TBESg="):
                with mock.patch.dict(os.environ, {"MIG_ENV_KEY": "sk-mig-123456789"}):
                    db.init_db()
                    # Insert a $ENV reference directly (simulating pre-migration DB)
                    with db.get_conn() as conn:
                        conn.execute("INSERT INTO ai_presets(name, api_key) VALUES (?, ?)", ("test_env_preset", "$MIG_ENV_KEY"))
                        conn.commit()
                    # Run the encrypt migration (re-init will call _encrypt_key_columns)
                    db.init_db()
                    with db.get_conn() as conn:
                        row = conn.execute("SELECT api_key FROM ai_presets WHERE name='test_env_preset'").fetchone()
                        stored = row["api_key"]
                    # Runtime must decrypt to same plaintext as migration resolved
                    self.assertEqual(key_crypto.decrypt_secret(stored), "sk-mig-123456789")
        finally:
            db.DB_PATH = orig_path
            db_schema.DB_PATH = orig_schema_path
            tmpdir.cleanup()
