"""Loader accepts required vars beyond the hardcoded KEYS tuple (F3).

Registry key refs (e.g. GROQ_API_KEY_G1) must resolve without editing
env_loader per provider. Values here are test-only sentinels, never
asserted beyond presence.
"""

import os
import unittest

from factory.core.env_loader import KEYS, load_factory_env


class TestRequiredBeyondKeys(unittest.TestCase):
    def test_required_var_returned_without_keys_edit(self):
        os.environ["TEST_REGISTRY_VAR_G1"] = "test-value"
        try:
            got = load_factory_env(required=("TEST_REGISTRY_VAR_G1",))
        finally:
            del os.environ["TEST_REGISTRY_VAR_G1"]
        self.assertEqual(got.get("TEST_REGISTRY_VAR_G1"), "test-value")
        for key in KEYS:
            self.assertIn(key, got)

    def test_missing_required_raises_key_error(self):
        os.environ.pop("TEST_REGISTRY_VAR_MISSING", None)
        with self.assertRaises(KeyError):
            load_factory_env(required=("TEST_REGISTRY_VAR_MISSING",))


if __name__ == "__main__":
    unittest.main()
