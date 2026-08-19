import os
import sqlite3
import tempfile
import threading
import unittest

from services import db as db_module
from services.db import schema as db_schema


class DbWalConcurrencyTests(unittest.TestCase):
    """Locked contract A2-1 (BN1): WAL + busy_timeout replace the global RLock."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db_module.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db_module.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path

    def tearDown(self):
        db_module.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()

    def _journal_mode(self):
        conn = sqlite3.connect(self.new_path)
        try:
            return conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()

    def _busy_timeout(self):
        conn = sqlite3.connect(self.new_path)
        try:
            return conn.execute("PRAGMA busy_timeout").fetchone()[0]
        finally:
            conn.close()

    def _set_journal_mode(self, mode):
        conn = sqlite3.connect(self.new_path)
        try:
            conn.execute(f"PRAGMA journal_mode={mode}")
        finally:
            conn.close()

    def test_fresh_db_uses_wal_after_connect(self):
        db_module.init_db()
        with db_module.get_conn():
            pass
        self.assertEqual(self._journal_mode(), "wal")

    def test_existing_rollback_db_is_converted_to_wal(self):
        # Simulate a pre-WAL (rollback journal) database: init then force delete mode.
        db_module.init_db()
        self._set_journal_mode("delete")
        self.assertEqual(self._journal_mode(), "delete")
        # Opening through get_conn must convert it to WAL (idempotent, no migration).
        with db_module.get_conn():
            pass
        self.assertEqual(self._journal_mode(), "wal")

    def test_busy_timeout_is_applied(self):
        db_module.init_db()
        with db_module.get_conn():
            pass
        self.assertEqual(self._busy_timeout(), db_schema._DB_BUSY_TIMEOUT)

    def test_concurrent_writers_do_not_raise_database_is_locked(self):
        db_module.init_db()
        NUM_THREADS = 10
        errors = []

        def writer(i):
            try:
                db_module.set_setting("concurrent_wal_test", str(i))
            except Exception as e:  # noqa: BLE001 - collect all errors for assertion
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        # All writers landed (last value written wins; presence proves no lost lock error).
        self.assertIsNotNone(
            db_module.get_setting("concurrent_wal_test", None),
            "Expected at least one write to have succeeded",
        )


class DbMaintenanceGateTests(unittest.TestCase):
    """Locked contract A2-1-6: shared/exclusive gate for maintenance and restore."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db_module.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db_module.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path

    def tearDown(self):
        db_module.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()

    def test_is_maintenance_true_during_exclusive(self):
        db_module.init_db()
        self.assertFalse(db_module.is_maintenance())
        with db_module.maintenance():
            self.assertTrue(db_module.is_maintenance())
        self.assertFalse(db_module.is_maintenance())

    def test_exclusive_waits_for_open_connection_and_blocks_new_ones(self):
        db_module.init_db()
        release = threading.Event()
        entered = threading.Event()
        result = []

        def holder():
            with db_module.get_conn():
                entered.set()
                release.wait(timeout=5)

        t = threading.Thread(target=holder)
        t.start()
        self.assertTrue(entered.wait(timeout=5))

        exclusive_entered = threading.Event()
        exclusive_done = threading.Event()

        def exclusive():
            with db_module.maintenance():
                exclusive_entered.set()
                exclusive_done.set()

        te = threading.Thread(target=exclusive)
        te.start()
        # Exclusive must NOT be granted while a shared connection is open.
        self.assertFalse(exclusive_entered.wait(timeout=0.3))
        release.set()
        t.join(timeout=5)
        self.assertTrue(exclusive_entered.wait(timeout=5))
        te.join(timeout=5)
        self.assertTrue(exclusive_done.is_set())

    def test_shared_ops_run_concurrently(self):
        db_module.init_db()
        started = threading.Event()
        results = []

        def opener():
            with db_module.get_conn():
                results.append("open")
                started.set()

        o1 = threading.Thread(target=opener)
        o1.start()
        self.assertTrue(started.wait(timeout=5))
        # A second shared hold should be granted while the first is still open.
        with db_module.get_conn():
            results.append("second")
        o1.join(timeout=5)
        self.assertIn("second", results)


class DbMaintenanceModeTests(unittest.TestCase):
    """Locked contract A2-1-7: persistent admin maintenance flag + message."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_db_path = db_module.DB_PATH
        self.old_schema_db_path = db_schema.DB_PATH
        self.new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db_module.DB_PATH = self.new_path
        db_schema.DB_PATH = self.new_path

    def tearDown(self):
        db_module.DB_PATH = self.old_db_path
        db_schema.DB_PATH = self.old_schema_db_path
        self.tempdir.cleanup()

    def test_maintenance_mode_flag_defaults_off(self):
        db_module.init_db()
        self.assertFalse(db_module.is_maintenance_mode())

    def test_set_and_clear_maintenance_mode(self):
        db_module.init_db()
        db_module.set_maintenance_mode(True)
        self.assertTrue(db_module.is_maintenance_mode())
        db_module.set_maintenance_mode(False)
        self.assertFalse(db_module.is_maintenance_mode())

    def test_maintenance_message_default_empty_then_settable(self):
        db_module.init_db()
        self.assertEqual(db_module.get_maintenance_message(), "")
        db_module.set_maintenance_message("ربات در حال تعمیر است")
        self.assertEqual(db_module.get_maintenance_message(), "ربات در حال تعمیر است")


if __name__ == "__main__":
    unittest.main()