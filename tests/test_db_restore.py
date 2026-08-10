import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing

from services import db
from services.db import schema as db_schema


def _write_backup(path: str, migration_value: str | None) -> bytes:
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
            if migration_value is not None:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES "
                    "('fsrs_migration_done', ?)",
                    (migration_value,),
                )
    with open(path, "rb") as backup_file:
        return backup_file.read()


def _write_incompatible_marked_backup(path: str) -> bytes:
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT INTO settings(key, value) VALUES "
                "('fsrs_migration_done', '1')"
            )
            conn.execute("CREATE TABLE saved_words (id INTEGER PRIMARY KEY)")
    with open(path, "rb") as backup_file:
        return backup_file.read()


def _write_incomplete_marked_backup(path: str) -> bytes:
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT INTO settings(key, value) VALUES "
                "('fsrs_migration_done', '1')"
            )
            conn.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY)")
    with open(path, "rb") as backup_file:
        return backup_file.read()


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

    def test_pre_fsrs_backup_is_rejected_before_live_db_overwrite(self):
        backup_path = os.path.join(self.tempdir.name, "old-backup.sqlite")
        backup = _write_backup(backup_path, migration_value=None)
        with open(self.live_path, "rb") as live_file:
            original = live_file.read()

        with self.assertRaisesRegex(ValueError, "نسخه پشتیبان قدیمی"):
            db.import_db_bytes(backup)

        with open(self.live_path, "rb") as live_file:
            self.assertEqual(live_file.read(), original)
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    def test_nonfinal_fsrs_marker_is_rejected_before_overwrite(self):
        backup_path = os.path.join(self.tempdir.name, "partial-backup.sqlite")
        backup = _write_backup(backup_path, migration_value="0")
        with open(self.live_path, "rb") as live_file:
            original = live_file.read()

        with self.assertRaisesRegex(ValueError, "نسخه پشتیبان قدیمی"):
            db.import_db_bytes(backup)

        with open(self.live_path, "rb") as live_file:
            self.assertEqual(live_file.read(), original)

    def test_final_fsrs_marker_allows_restore(self):
        backup_path = os.path.join(self.tempdir.name, "current-backup.sqlite")
        backup = _write_backup(backup_path, migration_value="1")

        db.import_db_bytes(backup)

        self.assertEqual(db.get_setting("fsrs_migration_done"), "1")
        self.assertEqual(db.get_setting("restore_sentinel"), "")

    def test_incompatible_marked_backup_is_rejected_before_overwrite(self):
        backup_path = os.path.join(self.tempdir.name, "incompatible-backup.sqlite")
        backup = _write_incompatible_marked_backup(backup_path)
        with open(self.live_path, "rb") as live_file:
            original = live_file.read()

        with self.assertRaisesRegex(ValueError, "نسخه فعلی ربات سازگار نیست"):
            db.import_db_bytes(backup)

        with open(self.live_path, "rb") as live_file:
            self.assertEqual(live_file.read(), original)
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    def test_incomplete_marked_backup_is_rejected_before_overwrite(self):
        backup_path = os.path.join(self.tempdir.name, "incomplete-backup.sqlite")
        backup = _write_incomplete_marked_backup(backup_path)
        with open(self.live_path, "rb") as live_file:
            original = live_file.read()

        with self.assertRaisesRegex(ValueError, "نسخه فعلی ربات سازگار نیست"):
            db.import_db_bytes(backup)

        with open(self.live_path, "rb") as live_file:
            self.assertEqual(live_file.read(), original)
        self.assertEqual(db.get_setting("restore_sentinel"), "live")

    def test_restore_waits_for_open_database_connection(self):
        backup_path = os.path.join(self.tempdir.name, "locked-backup.sqlite")
        backup = _write_backup(backup_path, migration_value="1")
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
        self.assertEqual(db.get_setting("fsrs_migration_done"), "1")

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
