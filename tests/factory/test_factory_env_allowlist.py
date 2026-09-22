"""Canonical factory env allowlist (names only, sentinel values).

The loader allowlists the full provider-key-group set
({PROVIDER}_API_KEY_{G1,G2}) plus documented legacy fallbacks, the
Fernet master name, and the egress names. Unknown vars never load;
missing files yield the empty shape (no raise without required);
values never appear in errors or outputs.
"""

import os
import unittest

from factory.core import env_loader
from factory.core.env_loader import KEYS, load_factory_env


CANONICAL = (
    "AVALAI_API_KEY_G1", "AVALAI_API_KEY_G2",
    "OPENROUTER_API_KEY_G1", "OPENROUTER_API_KEY_G2",
    "GOOGLE_API_KEY_G1", "GOOGLE_API_KEY_G2",
    "GROQ_API_KEY_G1", "GROQ_API_KEY_G2",
)
LEGACY = (
    "AVALAI_API_KEY",
    "OPENROUTER_API_KEY", "OPENROUTER_API_KEY_2",
    "GOOGLE_AI_API_KEY",
    "GROQ_API_KEY",
    "OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_API_KEY_2",
)


class TestCanonicalAllowlist(unittest.TestCase):
    def test_canonical_group_vars_allowlisted(self):
        for var in CANONICAL:
            self.assertIn(var, KEYS)

    def test_legacy_generic_vars_allowlisted_and_marked(self):
        for var in LEGACY:
            self.assertIn(var, KEYS)
            self.assertIn(var, env_loader.LEGACY_KEY_VARS)
        for var in CANONICAL:
            self.assertNotIn(var, env_loader.LEGACY_KEY_VARS)

    def test_master_and_egress_vars_allowlisted(self):
        for var in ("AI_MASTER_KEY", "EGRESS_SUP_TOKEN",
                    "EGRESS_SUP_URL", "EGRESS_SUP_PORT"):
            self.assertIn(var, KEYS)

    def test_unknown_vars_never_load(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("NOT_A_REAL_VAR=sentinel-unknown\n")
                handle.write("GROQ_API_KEY_G1=sentinel-g1\n")
            os.environ.pop("NOT_A_REAL_VAR", None)
            old = os.environ.pop("GROQ_API_KEY_G1", None)
            try:
                got = load_factory_env(path=path)
                self.assertIsNone(os.environ.get("NOT_A_REAL_VAR"))
                self.assertEqual(os.environ.get("GROQ_API_KEY_G1"),
                                 "sentinel-g1")
                self.assertEqual(got["GROQ_API_KEY_G1"], "sentinel-g1")
            finally:
                os.environ.pop("NOT_A_REAL_VAR", None)
                os.environ.pop("GROQ_API_KEY_G1", None)
                if old is not None:
                    os.environ["GROQ_API_KEY_G1"] = old

    def test_missing_file_shape_no_raise(self):
        import tempfile
        missing = os.path.join(tempfile.gettempdir(),
                               "hamzaban-no-such-env")
        if os.path.exists(missing):
            self.skipTest("scratch path exists")
        got = load_factory_env(path=missing)
        for var in KEYS:
            self.assertIn(var, got)
            self.assertEqual(got[var], os.environ.get(var, ""))

    def test_values_never_in_outputs(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("GROQ_API_KEY_G1=sentinel-secret-xyz\n")
            old = os.environ.pop("GROQ_API_KEY_G1", None)
            try:
                got = load_factory_env(path=path)
                blob = json.dumps(got)
                # The returned mapping necessarily carries the value
                # for the caller; nothing ELSE may echo it: the error
                # path names names only.
                os.environ.pop("GROQ_API_KEY_G1", None)
                os.environ.pop("MISSING_SENTINEL_VAR", None)
                try:
                    load_factory_env(
                        required=("MISSING_SENTINEL_VAR",), path=path)
                    self.fail("expected KeyError")
                except KeyError as exc:
                    self.assertIn("MISSING_SENTINEL_VAR", str(exc))
                    self.assertNotIn("sentinel-secret-xyz", str(exc))
            finally:
                os.environ.pop("GROQ_API_KEY_G1", None)
                if old is not None:
                    os.environ["GROQ_API_KEY_G1"] = old
        self.assertNotIn("sentinel-secret-xyz", repr(KEYS))


if __name__ == "__main__":
    unittest.main()
