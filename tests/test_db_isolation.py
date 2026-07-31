import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema


class DbIsolationGuardTest(unittest.TestCase):
    """Guard: when a test overrides db.DB_PATH, the DB layer must honor it.

    Regression guard for the incident where tests wiped the production AI
    presets: get_conn() used a stale import-time copy of DB_PATH, so writes
    leaked into the real database. This test only inspects the path via
    PRAGMA database_list (read-only), so it can never corrupt production data
    even if the guard itself regresses.
    """

    def _assert_conn_uses(self, expected_path: str):
        for factory in (db.get_conn, db_schema.get_conn):
            with factory() as conn:
                row = conn.execute("PRAGMA database_list").fetchone()
                self.assertEqual(
                    row[2],
                    expected_path,
                    f"{factory.__module__}.{factory.__name__} must honor db.DB_PATH override",
                )

    def test_db_layer_honors_path_override(self):
        real_path = db.DB_PATH
        tmpdir = tempfile.TemporaryDirectory()
        isolated_path = os.path.join(tmpdir.name, "isolated.sqlite")
        try:
            db.DB_PATH = isolated_path
            self._assert_conn_uses(isolated_path)
        finally:
            db.DB_PATH = real_path
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
