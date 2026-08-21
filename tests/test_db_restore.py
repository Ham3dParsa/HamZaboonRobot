import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from unittest.mock import patch

from services import db
from services.db import schema as db_schema


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as backup_file:
        return backup_file.read()


def _write_foreign_backup(path: str) -> bytes:
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    return _read_bytes(path)


class DatabaseRestoreSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.live_path = os.path.join(self.tempdir.name, "live.sqlite")
        db.DB_PATH = self.live_path
        db_schema.DB_PATH = self.live_path
        db.init_db()
        db.set_setting("restore_sentinel", "live")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def test_legacy_backup_is_rejected_before_live_db_overwrite(self):
        backup_path = os.path.join(self.tempdir.name, "old-backup.sqlite")
        backup = db.export_db_bytes()
        with open(backup_path, "wb") as backup_file:
            backup_file.write(backup)
        with closing(sqlite3.connect(backup_path)) as conn:
            with conn:
                conn.execute("CREATE TABLE daily_cards (id INTEGER PRIMARY KEY)")
        legacy_backup = _read_bytes(backup_path)
        original = _read_bytes(self.live_path)

        with self.assertRaisesRegex(ValueError, "نسخه پشتیبان قدیمی"):
            db.import_db_bytes(legacy_backup)

        self.assertEqual(_read_bytes(self.live_path), original)
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    def test_foreign_backup_is_rejected_before_live_db_overwrite(self):
        backup_path = os.path.join(self.tempdir.name, "foreign.sqlite")
        backup = _write_foreign_backup(backup_path)
        original = _read_bytes(self.live_path)

        with self.assertRaisesRegex(ValueError, "پشتیبان معتبر"):
            db.import_db_bytes(backup)

        self.assertEqual(_read_bytes(self.live_path), original)
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    def test_modern_backup_missing_required_column_is_rejected(self):
        backup_path = os.path.join(self.tempdir.name, "missing-column.sqlite")
        with open(backup_path, "wb") as backup_file:
            backup_file.write(db.export_db_bytes())
        with closing(sqlite3.connect(backup_path)) as conn:
            with conn:
                conn.execute("ALTER TABLE users DROP COLUMN username")
        backup = _read_bytes(backup_path)
        original = _read_bytes(self.live_path)

        with self.assertRaisesRegex(ValueError, "نسخه فعلی ربات سازگار نیست"):
            db.import_db_bytes(backup)

        self.assertEqual(_read_bytes(self.live_path), original)
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    def test_post_cutover_backup_round_trip_preserves_user_and_saved_word(self):
        db.create_user_if_needed(7, "learner")
        self.assertTrue(db.add_saved_word(7, "persist", "en"))
        backup = db.export_db_bytes()
        db.set_setting("restore_sentinel", "changed")
        db.add_saved_word(7, "discard", "en")

        db.import_db_bytes(backup)

        self.assertEqual(db.get_setting("restore_sentinel"), "live")
        self.assertIsNotNone(db.get_user(7))
        with db.get_conn() as conn:
            words = [row[0] for row in conn.execute("SELECT word FROM saved_words")]
        self.assertEqual(words, ["persist"])

    def test_rejected_backup_preserves_existing_rollback_copy(self):
        rollback_path = f"{self.live_path}.pre_restore"
        with open(rollback_path, "wb") as rollback_file:
            rollback_file.write(b"previous rollback")
        backup_path = os.path.join(self.tempdir.name, "foreign.sqlite")
        foreign_backup = _write_foreign_backup(backup_path)

        with self.assertRaisesRegex(ValueError, "پشتیبان معتبر"):
            db.import_db_bytes(foreign_backup, backup_path=rollback_path)

        self.assertEqual(_read_bytes(rollback_path), b"previous rollback")

    def test_successful_restore_replaces_rollback_copy_after_validation(self):
        backup = db.export_db_bytes()
        db.set_setting("restore_sentinel", "changed")
        rollback_path = f"{self.live_path}.pre_restore"

        db.import_db_bytes(backup, backup_path=rollback_path)

        with closing(sqlite3.connect(rollback_path)) as rollback_conn:
            value = rollback_conn.execute(
                "SELECT value FROM settings WHERE key='restore_sentinel'"
            ).fetchone()
        self.assertEqual(value[0], "changed")
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    def test_permission_failure_preserves_existing_rollback_copy(self):
        backup = db.export_db_bytes()
        rollback_path = f"{self.live_path}.pre_restore"
        with open(rollback_path, "wb") as rollback_file:
            rollback_file.write(b"previous rollback")

        with patch("services.db.os.chmod", side_effect=PermissionError):
            with self.assertRaisesRegex(ValueError, "جایگزینی دیتابیس"):
                db.import_db_bytes(backup, backup_path=rollback_path)

        self.assertEqual(_read_bytes(rollback_path), b"previous rollback")

    def test_successful_restore_removes_stale_sqlite_sidecars(self):
        backup = db.export_db_bytes()
        sidecars = [f"{self.live_path}{suffix}" for suffix in ("-journal", "-wal", "-shm")]
        for sidecar in sidecars:
            with open(sidecar, "wb") as sidecar_file:
                sidecar_file.write(b"")

        db.import_db_bytes(backup)

        self.assertTrue(all(not os.path.exists(sidecar) for sidecar in sidecars))

    def test_storage_failure_reports_storage_error(self):
        backup = db.export_db_bytes()

        with patch("services.db.tempfile.mkstemp", side_effect=PermissionError):
            with self.assertRaisesRegex(ValueError, "فضای ذخیره‌سازی"):
                db.import_db_bytes(backup)

    def test_sqlite_storage_failure_reports_storage_error(self):
        backup = db.export_db_bytes()

        with patch(
            "services.db.init_db",
            side_effect=sqlite3.OperationalError("database or disk is full"),
        ):
            with self.assertRaisesRegex(ValueError, "فضای ذخیره‌سازی"):
                db.import_db_bytes(backup)

    def test_restore_waits_for_open_database_connection(self):
        backup = db.export_db_bytes()
        started = threading.Event()
        finished = threading.Event()
        errors = []

        def restore():
            started.set()
            try:
                db.import_db_bytes(backup)
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=restore)
        try:
            with db.get_conn():
                thread.start()
                self.assertTrue(started.wait(timeout=1))
                self.assertFalse(finished.wait(timeout=0.2))

            self.assertTrue(finished.wait(timeout=5))
        finally:
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    def test_export_waits_for_open_database_connection(self):
        started = threading.Event()
        finished = threading.Event()
        result = []

        def export():
            started.set()
            result.append(db.export_db_bytes())
            finished.set()

        thread = threading.Thread(target=export)
        try:
            with db.get_conn():
                thread.start()
                self.assertTrue(started.wait(timeout=1))
                self.assertFalse(finished.wait(timeout=0.2))

            self.assertTrue(finished.wait(timeout=5))
        finally:
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result[0].startswith(b"SQLite format 3\x00"))


if __name__ == "__main__":
    unittest.main()
