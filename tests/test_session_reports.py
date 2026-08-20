"""Post-session report persistence (R10) — DB accessor + serialization.

Locked contract 2026-08-20 (rules R10-A..R10-G):
- R10-B: persist the built SessionReport as JSON; re-render on reopen.
- R10-D: retain all reports within 3 days.
- R10-E: lazy purge of expired rows on save/list/load.

DB layer is pure JSON I/O + SQL (no Telegram/handler imports).
"""

import datetime
import os
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema
from services.db import session_reports as sr_module
from services.session.summary import (
    WordReviewRecord,
    build_report,
    deserialize_report,
    serialize_report,
)


def _make_report(grade=3):
    records = [
        WordReviewRecord(
            word_id=1,
            word="hello",
            activity_type="srs_review",
            stability_before=2.0,
            stability_after=3.0,
            prior_review_date="2026-08-10",
            grade=grade,
            interval_days=3.0,
            next_review_date="2026-08-20",
            difficulty=3.2,
        )
    ]
    return build_report(records)


def _column_names(table):
    with db_module.get_conn() as conn:
        return {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }


class SessionReportTableTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "reports.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_fresh_db_has_session_reports_table(self):
        with db_module.get_conn() as conn:
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("session_reports", tables)

    def test_session_reports_columns(self):
        cols = _column_names("session_reports")
        for col in (
            "id",
            "user_id",
            "session_date",
            "created_at",
            "report_json",
            "is_admin",
        ):
            self.assertIn(col, cols, f"session_reports.{col} missing")


class SerializationTests(unittest.TestCase):
    def test_roundtrip_preserves_report(self):
        report = _make_report()
        restored = deserialize_report(serialize_report(report))
        self.assertEqual(restored.total, report.total)
        self.assertEqual(restored.rows[0].word, "hello")
        self.assertEqual(restored.rows[0].grade, 3)
        self.assertEqual(restored.rows[0].difficulty, 3.2)
        self.assertAlmostEqual(restored.recall_rate, report.recall_rate)

    def test_unsupported_version_rejected(self):
        payload = serialize_report(_make_report())
        import json

        data = json.loads(payload)
        data["version"] = 999
        with self.assertRaises(ValueError):
            deserialize_report(json.dumps(data))

    def test_missing_rows_rejected(self):
        with self.assertRaises(ValueError):
            deserialize_report('{"version": 1}')


class SessionReportAccessorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "reports.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_save_then_list_returns_entry(self):
        sr_module.save_session_report(1, "2026-08-20", _make_report())
        entries = sr_module.list_recent_reports(1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].session_date, "2026-08-20")

    def test_save_then_load_roundtrip(self):
        sr_module.save_session_report(1, "2026-08-20", _make_report())
        entries = sr_module.list_recent_reports(1)
        loaded = sr_module.load_report(entries[0].report_id, 1)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.session_date, "2026-08-20")
        self.assertEqual(loaded.report.rows[0].word, "hello")
        self.assertFalse(loaded.is_admin)

    def test_is_admin_flag_persisted(self):
        sr_module.save_session_report(1, "2026-08-20", _make_report(), is_admin=True)
        entries = sr_module.list_recent_reports(1)
        loaded = sr_module.load_report(entries[0].report_id, 1)
        self.assertTrue(loaded.is_admin)

    def test_load_missing_returns_none(self):
        sr_module.save_session_report(1, "2026-08-20", _make_report())
        self.assertIsNone(sr_module.load_report(999, 1))

    def test_load_foreign_report_returns_none(self):
        sr_module.save_session_report(1, "2026-08-20", _make_report())
        entries = sr_module.list_recent_reports(1)
        self.assertIsNone(sr_module.load_report(entries[0].report_id, 2))

    def test_list_is_newest_first(self):
        sr_module.save_session_report(1, "2026-08-18", _make_report())
        sr_module.save_session_report(1, "2026-08-20", _make_report())
        entries = sr_module.list_recent_reports(1)
        self.assertEqual([e.session_date for e in entries], ["2026-08-20", "2026-08-18"])

    def test_expired_report_is_purged_and_hidden(self):
        # Insert a report then backdate its created_at beyond the 3-day window.
        sr_module.save_session_report(1, "2026-08-10", _make_report())
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat()
        with db_module.transaction() as conn:
            conn.execute(
                "UPDATE session_reports SET created_at=? WHERE user_id=1", (old,)
            )
        self.assertEqual(sr_module.list_recent_reports(1), [])
        loaded = sr_module.load_report(1, 1)
        self.assertIsNone(loaded)
        with db_module.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM session_reports WHERE user_id=1"
            ).fetchone()[0]
        self.assertEqual(count, 0, "expired row should be purged lazily")

    def test_save_purges_expired_other_user_rows(self):
        # Backdate an old report, then saving a new one should purge it globally.
        sr_module.save_session_report(1, "2026-08-10", _make_report())
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat()
        with db_module.transaction() as conn:
            conn.execute(
                "UPDATE session_reports SET created_at=? WHERE user_id=1", (old,)
            )
        sr_module.save_session_report(2, "2026-08-20", _make_report())
        with db_module.get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM session_reports").fetchone()[0]
        self.assertEqual(count, 1, "only the fresh report should remain")

    def test_load_corrupt_report_purges(self):
        sr_module.save_session_report(1, "2026-08-20", _make_report())
        with db_module.transaction() as conn:
            conn.execute(
                "UPDATE session_reports SET report_json=? WHERE user_id=1",
                ('{"version": 999, "rows": []}',),
            )
        self.assertIsNone(sr_module.load_report(1, 1))
        with db_module.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM session_reports WHERE user_id=1"
            ).fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()