"""Integration tests for report-purge atomicity (R10-D/E).

Verifies that purge is atomic with save (one-step DELETE+INSERT) and that
lazy purge on list/load is safe (DELETE+SELECT in same transaction).
Retention window is 3 days (``REPORT_WINDOW_DAYS``); ``created_at`` is UTC
processing metadata (single source: ``services/db/session_reports.py``).
"""

from __future__ import annotations

import ast
import datetime
import os
import tempfile
import threading
import unittest
import pathlib
import re

from services import db
from services.db import schema as db_schema
from services.db.session_reports import REPORT_WINDOW_DAYS
from services.session.summary import WordReviewRecord, build_report


def _make_report():
    rec = WordReviewRecord(word_id=1, word="hello", activity_type="srs_review", grade=3, stability_before=1.0, stability_after=2.0)
    return build_report([rec])


class ReportPurgeAtomicTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new
        db_schema.DB_PATH = new
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _insert_raw_report(self, user_id, session_date, created_at_iso, report_json="{\"version\":1,\"rows\":[]}"):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO session_reports(user_id, session_date, created_at, report_json, is_admin) VALUES (?, ?, ?, ?, 0)",
                (user_id, session_date, created_at_iso, report_json),
            )
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_save_purges_expired_and_inserts_atomically(self):
        # Insert 2 expired reports older than 3 days
        now = db_schema._utc_now()
        expired1 = (now - datetime.timedelta(days=REPORT_WINDOW_DAYS + 1)).isoformat()
        expired2 = (now - datetime.timedelta(days=REPORT_WINDOW_DAYS + 10)).isoformat()
        self._insert_raw_report(1, "2026-08-10", expired1)
        self._insert_raw_report(1, "2026-08-05", expired2)
        # Verify they exist before save
        with db.get_conn() as conn:
            before = conn.execute("SELECT COUNT(*) AS c FROM session_reports").fetchone()["c"]
        self.assertEqual(before, 2)

        # Save new report — should DELETE expired WHERE created_at < cutoff then INSERT in one transaction
        report = _make_report()
        db.save_session_report(1, "2026-08-20", report)

        with db.get_conn() as conn:
            rows = conn.execute("SELECT session_date, created_at FROM session_reports").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_date"], "2026-08-20")

    def test_concurrent_saves_do_not_lose_reports(self):
        # Prove atomicity under true concurrent writers (Kilo 74, 86).
        # Uses plain start/join (no Barrier — avoids flakiness on slow CI)
        # plus a concurrent reader to exercise the list_recent_reports
        # DELETE+SELECT race. If purge+insert were not in one transaction,
        # one save's DELETE could wipe the other's just-inserted row or a
        # concurrent list could ghost-read.
        r1 = _make_report()
        r2 = build_report([WordReviewRecord(word_id=2, word="world", activity_type="first_exposure", grade=4, stability_before=0.5, stability_after=1.5)])
        errors: list[BaseException] = []

        def _save(date: str, report):
            try:
                db.save_session_report(1, date, report)
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        def _reader():
            try:
                for _ in range(5):
                    db.list_recent_reports(1)
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        t1 = threading.Thread(target=_save, args=("2026-08-19", r1))
        t2 = threading.Thread(target=_save, args=("2026-08-20", r2))
        tr = threading.Thread(target=_reader)
        t1.start()
        t2.start()
        tr.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        tr.join(timeout=10)
        self.assertFalse(errors, f"concurrent saves raised: {errors}")
        self.assertFalse(t1.is_alive(), "t1 hung (deadlock/busy_timeout)")
        self.assertFalse(t2.is_alive(), "t2 hung (deadlock/busy_timeout)")
        self.assertFalse(tr.is_alive(), "reader hung (deadlock/busy_timeout)")

        reports = db.list_recent_reports(1)
        self.assertEqual(len(reports), 2)
        dates = {e.session_date for e in reports}
        self.assertEqual(dates, {"2026-08-19", "2026-08-20"})

        # Also ensure saves don't delete each other
        with db.get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM session_reports WHERE user_id=1").fetchone()["c"]
        self.assertEqual(count, 2)

    def test_list_recent_reports_returns_only_within_window_and_purges_expired(self):
        now = db_schema._utc_now()
        expired = (now - datetime.timedelta(days=REPORT_WINDOW_DAYS + 2)).isoformat()
        fresh = (now - datetime.timedelta(days=1)).isoformat()
        # Expired for user 1, fresh for user 1
        self._insert_raw_report(1, "2026-08-01", expired)
        self._insert_raw_report(1, "2026-08-19", fresh)
        # Also expired for another user should be purged too
        self._insert_raw_report(2, "2026-08-01", expired)

        entries = db.list_recent_reports(1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].session_date, "2026-08-19")

        # Expired rows should be purged from DB entirely (lazy purge)
        with db.get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM session_reports").fetchone()["c"]
        # Only the fresh one should remain
        self.assertEqual(total, 1)

    def test_load_report_expired_returns_none_and_purges(self):
        now = db_schema._utc_now()
        expired = (now - datetime.timedelta(days=REPORT_WINDOW_DAYS + 5)).isoformat()
        # Insert expired report for user 1
        rid = self._insert_raw_report(1, "2026-08-01", expired, report_json='{"version":1,"rows":[]}')
        # Try to load — should return None and purge
        result = db.load_report(rid, 1)
        self.assertIsNone(result)
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM session_reports WHERE id=?", (rid,)).fetchone()
        self.assertIsNone(row)

        # Valid report should load correctly
        report = _make_report()
        db.save_session_report(1, "2026-08-20", report)
        fresh_entries = db.list_recent_reports(1)
        self.assertEqual(len(fresh_entries), 1)
        loaded = db.load_report(fresh_entries[0].report_id, 1)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.session_date, "2026-08-20")

    def test_no_await_inside_transaction(self):
        path = pathlib.Path(__file__).resolve().parents[2] / "services" / "db" / "session_reports.py"
        src = path.read_text(encoding="utf-8")
        # Robust check (Kilo 137): string search for "await " is brittle
        # (false positives in comments/strings, misses await in strings). Use
        # the AST so only real ``await`` syntax is flagged, and ensure no
        # ``await`` exists inside this sync DB helper at all.
        tree = ast.parse(src, filename=str(path))
        awaits = [n for n in ast.walk(tree) if isinstance(n, ast.Await)]
        self.assertEqual(len(awaits), 0, f"session_reports.py must not contain await (found {len(awaits)} Await nodes)")
        # Keep the seam count as a separate invariant — not as proxy for
        # await-safety. Count ``with transaction()`` blocks syntactically.
        blocks = re.findall(r"with\s+transaction\(\)", src)
        self.assertGreaterEqual(len(blocks), 3, "expected at least 3 transaction usages (save, list, load)")


if __name__ == "__main__":
    unittest.main()
