"""P1.1 / R1 snapshot-database safety tests.

These prove the pre-migrated master + per-test copy optimization can never
reach the production database, that a fresh ``init_db`` yields a *marked* test
database, that explicit-path ``init_db`` (migration/restore) still uses the real
migration path, and that the destructive-op guard rejects unmarked databases.
"""

import os
import sqlite3
import tempfile
import unittest

from services import db
from services.db import schema as db_schema

PRODUCTION_PATH = os.environ.get("HAMZABAN_PRODUCTION_DB_PATH") or (
    __import__("config", fromlist=["DB_PATH"]).DB_PATH
)


class TestSnapshotSafety(unittest.TestCase):
    def setUp(self):
        os.environ["HAMZABAN_TEST_MODE"] = "1"
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._tmp.cleanup()

    def _fresh_path(self, name: str) -> str:
        return os.path.join(self._tmp.name, name)

    def test_fresh_init_db_produces_marked_test_database(self):
        path = self._fresh_path("fresh.db")
        db.DB_PATH = path
        db_schema.DB_PATH = path
        db.init_db()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(db_schema._db_application_id(path), db_schema._TEST_APP_ID)
        with db.get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_explicit_path_init_db_honors_the_path_not_db_path(self):
        # The copy intercept only fires when path is None; an explicit path must
        # create the DB at that path (real migration), leaving DB_PATH untouched.
        db.DB_PATH = self._fresh_path("unused.db")
        explicit = self._fresh_path("explicit.db")
        db.init_db(path=explicit)
        self.assertTrue(os.path.exists(explicit))
        self.assertFalse(os.path.exists(db.DB_PATH))
        self.assertEqual(db_schema._db_application_id(explicit), db_schema._TEST_APP_ID)

    def test_active_db_path_is_never_master_or_production(self):
        active = self._fresh_path("active.db")
        db.DB_PATH = active
        db_schema.DB_PATH = active
        db.init_db()
        active_abs = os.path.abspath(active)
        # Active DB is not inside the master sandbox area.
        self.assertNotIn("hamzaban_test_area", active_abs)
        # Active DB is not the production database.
        self.assertNotEqual(active_abs, os.path.abspath(PRODUCTION_PATH))

    def test_destructive_op_guard_blocks_unmarked_database(self):
        path = self._fresh_path("unmarked.db")
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(RuntimeError):
            db_schema._guard_destructive_op(path)

    def test_destructive_op_guard_allows_marked_database(self):
        path = self._fresh_path("marked.db")
        conn = sqlite3.connect(path)
        try:
            conn.execute(f"PRAGMA application_id={db_schema._TEST_APP_ID}")
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.commit()
        finally:
            conn.close()
        db_schema._guard_destructive_op(path)  # must not raise

    def test_destructive_op_guard_blocks_production_path(self):
        # Even if (impossibly) marked, the production path is always blocked.
        path = self._fresh_path("prodlike.db")
        conn = sqlite3.connect(path)
        try:
            conn.execute(f"PRAGMA application_id={db_schema._TEST_APP_ID}")
            conn.commit()
        finally:
            conn.close()
        old_prod = os.environ.get("HAMZABAN_PRODUCTION_DB_PATH")
        try:
            os.environ["HAMZABAN_PRODUCTION_DB_PATH"] = path
            with self.assertRaises(RuntimeError):
                db_schema._guard_destructive_op(path)
        finally:
            if old_prod is None:
                os.environ.pop("HAMZABAN_PRODUCTION_DB_PATH", None)
            else:
                os.environ["HAMZABAN_PRODUCTION_DB_PATH"] = old_prod

    @staticmethod
    def _schema(path: str) -> dict:
        """Return detailed schema for comparison, read-only.

        For each table returns {(name, type, notnull, pk, dflt_value)} plus
        the set of index definitions, so type/notnull/pk/dflt and index drift
        are caught, not just column names.
        """
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            ]
            schema: dict = {}
            for t in tables:
                schema[t] = {
                    (r[1], r[2], r[3], r[5], r[4])
                    for r in conn.execute(f"PRAGMA table_info({t})")
                }
            # Include indexes/constraints as (name, tbl_name, sql)
            schema["_indexes"] = {
                (r[0], r[1], r[2])
                for r in conn.execute(
                    "SELECT name, tbl_name, sql FROM sqlite_master "
                    "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
                )
            }
            return schema
        finally:
            conn.close()

    def test_master_copy_matches_real_fresh_migration(self):
        # Finding-3 guard: the P1.1 copy must be schema-equivalent to a genuine
        # fresh migration, proving the real init_db (which builds the master once
        # per worker) still produces the same schema the copies carry.
        real = self._fresh_path("real_migrated.db")
        db.init_db(path=real)  # explicit path -> real migration, not intercepted

        copy = self._fresh_path("master_copy.db")
        db.DB_PATH = copy
        db_schema.DB_PATH = copy
        db.init_db()  # no path -> intercepted, copies the master

        self.assertEqual(self._schema(real), self._schema(copy))


class TestKillSwitchDiagnostics(unittest.TestCase):
    def setUp(self):
        os.environ["HAMZABAN_TEST_MODE"] = "1"

    def test_kill_switch_reports_worker_pid_and_test(self):
        old_worker = os.environ.get("PYTEST_XDIST_WORKER")
        old_test = os.environ.get("HAMZABAN_CURRENT_TEST")
        old_prod = os.environ.get("HAMZABAN_PRODUCTION_DB_PATH")
        try:
            os.environ["PYTEST_XDIST_WORKER"] = "gw7"
            os.environ["HAMZABAN_CURRENT_TEST"] = "tests/x::y"
            os.environ["HAMZABAN_PRODUCTION_DB_PATH"] = "/virtual/prod.sqlite"
            with self.assertRaises(RuntimeError) as ctx:
                db_schema._check_test_mode_guard("/virtual/prod.sqlite")
            msg = str(ctx.exception)
            self.assertIn("gw7", msg)
            self.assertIn(str(os.getpid()), msg)
            self.assertIn("tests/x::y", msg)
            self.assertIn(repr(os.path.abspath("/virtual/prod.sqlite")), msg)
        finally:
            for key, old in (
                ("PYTEST_XDIST_WORKER", old_worker),
                ("HAMZABAN_CURRENT_TEST", old_test),
                ("HAMZABAN_PRODUCTION_DB_PATH", old_prod),
            ):
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old


class TestImportDbBytesContract(unittest.TestCase):
    """Regression for Must-Fix 4 + 2/3."""

    def setUp(self):
        os.environ["HAMZABAN_TEST_MODE"] = "1"
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self._tmp = tempfile.TemporaryDirectory()
        # fresh marked target for every test
        self.target = os.path.join(self._tmp.name, "target.db")
        db.DB_PATH = self.target
        db_schema.DB_PATH = self.target
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self._tmp.cleanup()

    def _unmarked_backup_bytes(self) -> bytes:
        # Valid backup without marker: build a real DB then clear application_id.
        p = os.path.join(self._tmp.name, "unmarked.db")
        db_schema.init_db(p)  # explicit path => real migration
        conn = sqlite3.connect(p)
        try:
            conn.execute("PRAGMA application_id=0")
            conn.commit()
        finally:
            conn.close()
        with open(p, "rb") as f:
            return f.read()

    def test_unmarked_backup_restore_succeeds_into_test_db(self):
        data = self._unmarked_backup_bytes()
        # Must not raise — candidate no longer requires marker (Must 2)
        db.import_db_bytes(data)

    def test_production_target_blocked_as_valueerror(self):
        # Point HAMZABAN_PRODUCTION_DB_PATH at the active target
        old = os.environ.get("HAMZABAN_PRODUCTION_DB_PATH")
        try:
            os.environ["HAMZABAN_PRODUCTION_DB_PATH"] = self.target
            with self.assertRaises(ValueError) as ctx:
                db.import_db_bytes(self._unmarked_backup_bytes())
            self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
        finally:
            if old is None:
                os.environ.pop("HAMZABAN_PRODUCTION_DB_PATH", None)
            else:
                os.environ["HAMZABAN_PRODUCTION_DB_PATH"] = old

    def test_failed_guard_creates_no_backup_side_effect(self):
        old = os.environ.get("HAMZABAN_PRODUCTION_DB_PATH")
        backup = os.path.join(self._tmp.name, "should_not_exist.bak")
        try:
            os.environ["HAMZABAN_PRODUCTION_DB_PATH"] = self.target
            with self.assertRaises(ValueError):
                db.import_db_bytes(self._unmarked_backup_bytes(), backup_path=backup)
            self.assertFalse(os.path.exists(backup))
        finally:
            if old is None:
                os.environ.pop("HAMZABAN_PRODUCTION_DB_PATH", None)
            else:
                os.environ["HAMZABAN_PRODUCTION_DB_PATH"] = old


if __name__ == "__main__":
    unittest.main()