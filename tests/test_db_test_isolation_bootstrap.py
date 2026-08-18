"""Meta-test: prove subprocesses spawned during the suite inherit a throwaway
DB_PATH (set in tests/__init__.py), never the real production DB path.

This guards the regression reported in #391: a stray raw connect from a
subprocess could create the real ``hamzaban.db`` at the repo root. The fix
overrides DB_PATH in the environment for every subprocess, so this test proves
the override is actually inherited by a spawned helper process.
"""

import os
import subprocess
import sys
import tempfile
import unittest

import config


class TestSubprocessDbIsolationTest(unittest.TestCase):
    def test_subprocess_inherits_throwaway_db_path(self):
        code = "import os; print(os.getenv('DB_PATH', ''), end='')"
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(__file__),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        inherited = result.stdout
        self.assertTrue(inherited, "subprocess did not inherit a DB_PATH override")

        self.assertNotEqual(
            inherited,
            config.DB_PATH,
            "subprocess received the real production DB path",
        )
        self.assertTrue(
            inherited.startswith(tempfile.gettempdir()),
            f"DB_PATH {inherited!r} is not under the temp dir",
        )
        self.assertFalse(
            inherited.endswith("hamzaban.db"),
            "subprocess DB_PATH points at the production filename",
        )


if __name__ == "__main__":
    unittest.main()
