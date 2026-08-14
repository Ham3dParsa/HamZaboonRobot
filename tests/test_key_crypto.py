"""Tests for the key_crypto deep module (Phase 5, R11/F2).

Covers the small public interface:
- encrypt_secret(plaintext) -> str  ('' for empty; non-empty Fernet token)
- decrypt_secret(token) -> str      (roundtrip; fail-closed '' + warning, never throws)
- mask_key(plaintext) -> str        (consistent masked display)

All tests run with an explicit AI_MASTER_KEY so behavior is deterministic and
independent of any real environment config.
"""

from __future__ import annotations

import logging
import unittest
from unittest import mock

import config

from services.db import key_crypto


class _MasterKeyTestCase(unittest.TestCase):
    """Pin AI_MASTER_KEY for each test and restore config after."""

    def setUp(self):
        self._patcher = mock.patch.object(config, "AI_MASTER_KEY", self.master_key())
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def master_key(self) -> str:
        return "sd4H8UUr5ONYISGXcx468OQwFaUxaktNGGTPs9TBESg="


class EncryptSecretTest(_MasterKeyTestCase):
    def test_empty_input_returns_empty(self):
        self.assertEqual(key_crypto.encrypt_secret(""), "")

    def test_non_empty_returns_encrypted_token(self):
        token = key_crypto.encrypt_secret("sk-secret123456789")
        self.assertNotEqual(token, "sk-secret123456789")
        self.assertTrue(token)

    def test_encryption_is_not_deterministic(self):
        a = key_crypto.encrypt_secret("sk-same-key")
        b = key_crypto.encrypt_secret("sk-same-key")
        self.assertNotEqual(a, b)


class DecryptSecretTest(_MasterKeyTestCase):
    def test_roundtrip(self):
        plain = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
        token = key_crypto.encrypt_secret(plain)
        self.assertEqual(key_crypto.decrypt_secret(token), plain)

    def test_empty_token_returns_empty_no_warning(self):
        with self.assertNoLogs(key_crypto.log.name, level=logging.WARNING):
            self.assertEqual(key_crypto.decrypt_secret(""), "")

    def test_garbage_token_returns_empty_with_warning_no_throw(self):
        with self.assertLogs(key_crypto.log.name, level=logging.WARNING) as cm:
            result = key_crypto.decrypt_secret("this-is-not-a-valid-fernet-token")
        self.assertEqual(result, "")
        self.assertTrue(any("decrypt" in m for m in cm.output))


class MissingMasterKeyTest(unittest.TestCase):
    """Fail-closed when AI_MASTER_KEY is absent (Rule 1, Rule 6)."""

    def setUp(self):
        self._patcher = mock.patch.object(config, "AI_MASTER_KEY", "")
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_encrypt_returns_empty_no_plaintext_stored(self):
        with self.assertLogs(key_crypto.log.name, level=logging.WARNING):
            token = key_crypto.encrypt_secret("sk-should-never-be-stored")
        self.assertEqual(token, "")

    def test_decrypt_returns_empty_no_literal(self):
        with self.assertLogs(key_crypto.log.name, level=logging.WARNING) as cm:
            result = key_crypto.decrypt_secret("sk-some-token")
        self.assertEqual(result, "")
        self.assertFalse(any("sk-some-token" in m for m in cm.output))


class MaskKeyTest(_MasterKeyTestCase):
    def test_empty_returns_dash(self):
        self.assertEqual(key_crypto.mask_key(""), "—")

    def test_short_key_masked_fully(self):
        self.assertEqual(key_crypto.mask_key("abc"), "***")

    def test_long_key_masked_ends(self):
        masked = key_crypto.mask_key("sk-abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertTrue(masked.startswith("sk-ab"))
        self.assertTrue(masked.endswith("6789"))
        self.assertIn("…", masked)


class EncryptForStorageTest(_MasterKeyTestCase):
    def test_empty_input_stays_empty(self):
        self.assertEqual(key_crypto.encrypt_for_storage(""), "")

    def test_plaintext_is_encrypted(self):
        stored = key_crypto.encrypt_for_storage("sk-plain-secret-123456789")
        self.assertNotEqual(stored, "sk-plain-secret-123456789")
        self.assertTrue(stored.startswith("gAAAA"))
        self.assertEqual(key_crypto.decrypt_secret(stored), "sk-plain-secret-123456789")

    def test_already_encrypted_token_is_passed_through(self):
        token = key_crypto.encrypt_secret("sk-secret-123456789")
        self.assertEqual(key_crypto.encrypt_for_storage(token), token)


class EncryptForStorageNoMasterKeyTest(MissingMasterKeyTest):
    def test_plaintext_not_stored_when_no_master_key(self):
        with self.assertLogs(key_crypto.log.name, level=logging.WARNING):
            self.assertEqual(key_crypto.encrypt_for_storage("sk-plain-123456789"), "")

    def test_ciphertext_passed_through_even_without_master_key(self):
        # A token already at rest must never be re-encrypted or wiped just
        # because the master key is momentarily absent.
        token = "gAAAAA-this-looks-like-an-existing-token"
        self.assertEqual(key_crypto.encrypt_for_storage(token), token)


if __name__ == "__main__":
    unittest.main()