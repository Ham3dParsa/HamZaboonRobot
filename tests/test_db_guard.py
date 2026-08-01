import os
import tempfile
import unittest

from config import DB_PATH as PRODUCTION_PATH
from services import db
from services.db import schema as db_schema


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


if __name__ == "__main__":
    unittest.main()
