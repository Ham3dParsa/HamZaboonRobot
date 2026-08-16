"""Focused seam tests for the unified ``transaction()`` context manager (R1).

These lock the atomicity contract of ``services.db.schema.transaction``:

1. A clean block exit commits the immediate transaction (writes persist).
2. An exception inside the block rolls the transaction back (no partial write).
3. The nine write modules use the single ``transaction()`` seam for every write
   instead of scattering raw ``BEGIN IMMEDIATE ... commit()`` — the "replace,
   don't layer" spec from the R1 deep-module design. (The schema migration's own
   additive-then-destructive commit boundary is deliberately excluded.)
"""

import os
import sqlite3
import tempfile
import unittest

from services import db
from services.db import schema as db_schema
from services.db.schema import transaction


WRITE_MODULES = [
    "services.db",
    "services.db.users",
    "services.db.words",
    "services.db.preset_registry",
    "services.db.plans",
    "services.db.sessions",
    "services.db.settings",
    "services.db.cost_tracking",
    "services.db.reviews",
]


class TransactionSeamTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_path = db_schema.DB_PATH
        self.live_path = os.path.join(self.tempdir.name, "live.sqlite")
        db.DB_PATH = self.live_path
        db_schema.DB_PATH = self.live_path
        db.init_db()
        db.set_setting("seam_sentinel", "ok")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_path
        self.tempdir.cleanup()

    def test_clean_exit_commits(self):
        with transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                ("clean_exit_key", "committed"),
            )
        self.assertEqual(db.get_setting("clean_exit_key"), "committed")

    def test_exception_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with transaction() as conn:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?)",
                    ("rolled_back_key", "should-not-persist"),
                )
                raise RuntimeError("abort")
        self.assertEqual(db.get_setting("rolled_back_key", "missing"), "missing")

    def test_transaction_honors_path_override(self):
        with transaction() as conn:
            row = conn.execute("PRAGMA database_list").fetchone()
            self.assertEqual(row[2], self.live_path)

    def test_write_modules_use_transaction_seam(self):
        import importlib

        for module_name in WRITE_MODULES:
            module = importlib.import_module(module_name)
            with open(module.__file__, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertNotIn(
                "BEGIN IMMEDIATE",
                content,
                f"{module_name} must not scatter raw BEGIN IMMEDIATE; use transaction()",
            )
            self.assertIn(
                "transaction()",
                content,
                f"{module_name} must use the transaction() seam",
            )

    def test_schema_helper_still_backed_by_immediate(self):
        """The helper itself must issue BEGIN IMMEDIATE so the seam stays atomic."""
        import inspect

        source = inspect.getsource(db_schema.transaction)
        self.assertIn("BEGIN IMMEDIATE", source)


if __name__ == "__main__":
    unittest.main()