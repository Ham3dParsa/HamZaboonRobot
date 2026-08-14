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

    def test_tagged_but_invalid_ciphertext_fails_closed(self):
        # A v1:-tagged value that is not valid Fernet ciphertext under the
        # current key must fail closed to '' with a warning, never the literal.
        with self.assertLogs(key_crypto.log.name, level=logging.WARNING) as cm:
            result = key_crypto.decrypt_secret("v1:this-is-not-real-ciphertext")
        self.assertEqual(result, "")
        self.assertFalse(any("this-is-not-real-ciphertext" in m for m in cm.output))


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

    def test_plaintext_is_encrypted_and_tagged(self):
        stored = key_crypto.encrypt_for_storage("sk-plain-secret-123456789")
        self.assertNotEqual(stored, "sk-plain-secret-123456789")
        self.assertTrue(stored.startswith(key_crypto.VERSION_PREFIX))
        self.assertEqual(key_crypto.decrypt_secret(stored), "sk-plain-secret-123456789")

    def test_plaintext_starting_with_fernet_prefix_is_still_encrypted(self):
        # Kilo SUGGESTION: a raw key that happens to begin with the Fernet
        # prefix must be encrypted fresh (tagged v1:), never passed through as
        # plaintext because it is not tagged by this module.
        raw = "gAAAAAsuspicious-literal-that-is-not-real-ciphertext"
        stored = key_crypto.encrypt_for_storage(raw)
        self.assertTrue(stored.startswith(key_crypto.VERSION_PREFIX))
        self.assertNotEqual(stored, raw)
        self.assertEqual(key_crypto.decrypt_secret(stored), raw)

    def test_already_encrypted_token_is_passed_through(self):
        token = key_crypto.encrypt_secret("sk-secret-123456789")
        self.assertEqual(key_crypto.encrypt_for_storage(token), token)

    def test_rotated_master_key_old_ciphertext_preserved_not_wrapped(self):
        # A v1:-tagged token encrypted under a previous key is preserved
        # untouched; it must NOT be re-wrapped into an undecryptable double
        # layer (the resolver fails closed and the admin re-enters).
        old_key = "sd4H8UUr5ONYISGXcx468OQwFaUxaktNGGTPs9TBESg="
        new_key = "GqaCOB9C1WdWdsG7jGaHFfbowq69GViyVRpbYTiAM-M="
        token_old = key_crypto.VERSION_PREFIX + key_crypto.Fernet(
            old_key.encode()
        ).encrypt(b"sk-rotated-secret-123456").decode()
        with mock.patch.object(config, "AI_MASTER_KEY", new_key):
            stored = key_crypto.encrypt_for_storage(token_old)
        self.assertEqual(stored, token_old)


class EncryptForStorageNoMasterKeyTest(MissingMasterKeyTest):
    def test_plaintext_without_master_key_raises(self):
        # Kilo CRITICAL: never persist a raw plaintext key when no master key
        # is configured — fail closed by raising instead of writing plaintext.
        with self.assertLogs(key_crypto.log.name, level=logging.WARNING):
            with self.assertRaises(key_crypto.MasterKeyRequiredError):
                key_crypto.encrypt_for_storage("sk-plain-123456789")

    def test_tagged_without_master_key_preserved(self):
        # A v1:-tagged ciphertext is preserved even without a master key
        # (unchanged edit / non-destructive migration).
        self.assertEqual(
            key_crypto.encrypt_for_storage("v1:this-looks-like-existing-ciphertext"),
            "v1:this-looks-like-existing-ciphertext",
        )

    def test_plaintext_fail_closed_false_passes_through(self):
        # Non-destructive migration path: when a master key is absent, a raw
        # value is preserved unchanged (resolution fails closed later) rather
        # than raising.
        self.assertEqual(
            key_crypto.encrypt_for_storage("sk-plain-123456789", fail_closed=False),
            "sk-plain-123456789",
        )


if __name__ == "__main__":
    unittest.main()