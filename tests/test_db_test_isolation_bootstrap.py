"""Meta-test: prove subprocesses spawned during the suite inherit a throwaway
active DB_PATH (set in tests/__init__.py) while the schema guard still knows
the real production path via HAMZABAN_PRODUCTION_DB_PATH.

Guards the regression reported in #391: a stray raw connect from a subprocess
could create the real ``hamzaban.db`` at the repo root. The fix overrides
DB_PATH in the environment for every subprocess, so this test proves a spawned
helper process resolves an active DB that is NOT the real production path.
"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


class TestSubprocessDbIsolationTest(unittest.TestCase):
    def test_subprocess_inherits_throwaway_db_path(self):
        code = (
            "import config, os; "
            "print(config.DB_PATH, '|', "
            "os.getenv('HAMZABAN_PRODUCTION_DB_PATH', ''), end='')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        active, production = (part.strip() for part in result.stdout.split("|", 1))
        self.assertTrue(active, "subprocess did not inherit a DB_PATH override")

        # The subprocess's active DB (what it would connect to) must be the
        # throwaway path, not the real production path. Compare against the env
        # vars directly (not config.DB_PATH, which is the throwaway in xdist
        # workers) so the test is order- and worker-independent.
        self.assertEqual(active, os.environ["DB_PATH"])
        self.assertNotEqual(active, os.environ["HAMZABAN_PRODUCTION_DB_PATH"])
        self.assertTrue(
            active.startswith(tempfile.gettempdir()),
            f"active DB_PATH {active!r} is not under the temp dir",
        )
        self.assertFalse(
            active.endswith("hamzaban.db"),
            "subprocess active DB_PATH points at the production filename",
        )

        # The schema guard must still recognize the real production path inside
        # the subprocess, so it stays protected even though DB_PATH is overridden.
        self.assertEqual(
            production,
            os.environ["HAMZABAN_PRODUCTION_DB_PATH"],
            "subprocess lost the real production path reference",
        )
        self.assertNotEqual(active, production)


if __name__ == "__main__":
    unittest.main()