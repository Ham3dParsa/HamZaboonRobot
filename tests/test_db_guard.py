import os
import tempfile
import unittest

from config import DB_PATH
from services import db
from services.db import schema as db_schema

# The real production path. Under the test suite tests/__init__.py captures it
# into HAMZABAN_PRODUCTION_DB_PATH and points the active DB_PATH at a throwaway,
# so this must read the env var rather than config.DB_PATH (which is the
# throwaway in xdist workers). Standalone runs (no bootstrap) fall back to
# config.DB_PATH.
PRODUCTION_PATH = os.environ.get("HAMZABAN_PRODUCTION_DB_PATH") or DB_PATH


class TestModeGuardTest(unittest.TestCase):
    """Meta-test: prove the test-mode guard fires when it should and never
    blocks legitimate isolated databases. The blocked case raises before any
    connection is opened, so the production database is never touched here."""

    def setUp(self):
        os.environ["HAMZABAN_TEST_MODE"] = "1"
        self._prev_db_path = db.DB_PATH
        self._prev_schema_path = db_schema.DB_PATH

    def tearDown(self):
        os.environ.pop("HAMZABAN_TEST_MODE", None)
        db.DB_PATH = self._prev_db_path
        db_schema.DB_PATH = self._prev_schema_path

    def test_guard_blocks_production_path(self):
        db.DB_PATH = PRODUCTION_PATH
        db_schema.DB_PATH = PRODUCTION_PATH
        with self.assertRaises(RuntimeError):
            db_schema._check_test_mode_guard(PRODUCTION_PATH)

    def test_get_conn_blocks_production_path(self):
        db.DB_PATH = PRODUCTION_PATH
        with self.assertRaises(RuntimeError):
            with db.get_conn() as conn:
                conn.execute("SELECT 1")

    def test_init_db_blocks_production_path(self):
        db.DB_PATH = PRODUCTION_PATH
        db_schema.DB_PATH = PRODUCTION_PATH
        with self.assertRaises(RuntimeError):
            db.init_db()

    def test_guard_destructive_op_blocks_unmarked_isolated_path(self):
        # R1: a non-test database (no application_id marker) at an isolated path
        # must still be refused for destructive operations in test mode.
        tmpdir = tempfile.TemporaryDirectory()
        unmarked = os.path.join(tmpdir.name, "unmarked.sqlite")
        try:
            import sqlite3

            conn = sqlite3.connect(unmarked)
            try:
                conn.execute("CREATE TABLE t (x INTEGER)")
                conn.commit()
            finally:
                conn.close()
            with self.assertRaises(RuntimeError):
                db_schema._guard_destructive_op(unmarked)
        finally:
            tmpdir.cleanup()

    def test_guard_allows_isolated_path(self):
        tmpdir = tempfile.TemporaryDirectory()
        isolated = os.path.join(tmpdir.name, "isolated.sqlite")
        try:
            db.DB_PATH = isolated
            db_schema.DB_PATH = isolated
            with db.get_conn() as conn:
                conn.execute("CREATE TABLE t (x INTEGER)")
                conn.commit()
            with db_schema.get_conn() as conn:
                count = conn.execute("SELECT COUNT(*) AS c FROM t").fetchone()["c"]
            self.assertEqual(count, 0)
        finally:
            tmpdir.cleanup()

    def test_guard_inactive_when_not_test_mode(self):
        os.environ.pop("HAMZABAN_TEST_MODE", None)
        db.DB_PATH = PRODUCTION_PATH
        db_schema._check_test_mode_guard(PRODUCTION_PATH)  # must not raise

    def test_guard_uses_production_db_path_env_when_set(self):
        # Subprocesses get the real production path via HAMZABAN_PRODUCTION_DB_PATH
        # (see tests/__init__.py). When set, the guard protects THAT path instead
        # of config.DB_PATH, so a subprocess's throwaway DB is not misread as
        # production. (#391)
        old = os.environ.get("HAMZABAN_PRODUCTION_DB_PATH")
        try:
            os.environ["HAMZABAN_PRODUCTION_DB_PATH"] = "/opt/data/prod.sqlite"
            with self.assertRaises(RuntimeError):
                db_schema._check_test_mode_guard("/opt/data/prod.sqlite")
            db_schema._check_test_mode_guard("/elsewhere/dev.sqlite")  # must not raise
        finally:
            if old is None:
                os.environ.pop("HAMZABAN_PRODUCTION_DB_PATH", None)
            else:
                os.environ["HAMZABAN_PRODUCTION_DB_PATH"] = old


if __name__ == "__main__":
    unittest.main()
