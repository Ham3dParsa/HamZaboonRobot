"""Phase 1 — DB enrichment for Jalali grouping (TDD red).

Asserts:
- ReportEntry has created_at, total, learned_count, reviewed_count
- list_recent_reports parses report_json to populate counts
- ordering DESC by created_at
- jalali day key derivation via APP_TZ (midnight edge)
"""

import datetime
import os
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema
from services.db import session_reports as sr_module
from services.session.summary import WordReviewRecord, build_report
from config import APP_TZ


def _make_report(learned=1, reviewed=1):
    records = []
    for i in range(learned):
        records.append(
            WordReviewRecord(
                word_id=i + 1,
                word=f"w{i}",
                activity_type="first_exposure",
                grade=3,
            )
        )
    for i in range(reviewed):
        records.append(
            WordReviewRecord(
                word_id=100 + i,
                word=f"r{i}",
                activity_type="srs_review",
                grade=4,
            )
        )
    return build_report(records)


class ReportEntryEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "reports_grouping.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_report_entry_has_enriched_fields(self):
        sr_module.save_session_report(1, "2026-09-01", _make_report(learned=2, reviewed=1))
        entries = sr_module.list_recent_reports(1)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        # new fields must exist
        self.assertTrue(hasattr(e, "created_at"), "ReportEntry missing created_at")
        self.assertTrue(hasattr(e, "total"), "ReportEntry missing total")
        self.assertTrue(hasattr(e, "learned_count"), "ReportEntry missing learned_count")
        self.assertTrue(hasattr(e, "reviewed_count"), "ReportEntry missing reviewed_count")
        self.assertIsInstance(e.created_at, str)
        self.assertGreater(len(e.created_at), 0)
        # counts derived from report_json
        self.assertEqual(e.total, 3)
        self.assertEqual(e.learned_count, 2)
        self.assertEqual(e.reviewed_count, 1)

    def test_report_entry_defaults_for_backward_compat(self):
        # dataclass defaults should allow construction without new fields
        entry = sr_module.ReportEntry(report_id=1, session_date="2026-09-01")
        self.assertEqual(entry.created_at, "")
        self.assertEqual(entry.total, 0)

    def test_list_ordered_desc_by_created_at(self):
        # Insert two reports with explicit created_at ordering via transaction
        report = _make_report()
        from services.session.summary import serialize_report

        now = datetime.datetime.now(datetime.timezone.utc)
        earlier = (now - datetime.timedelta(hours=2)).isoformat()
        later = now.isoformat()
        payload = serialize_report(report)
        # Insert directly with custom timestamps
        with db_module.transaction() as conn:
            conn.execute(
                "INSERT INTO session_reports(user_id, session_date, created_at, report_json, is_admin) VALUES (?,?,?,?,0)",
                (1, "2026-09-01", earlier, payload),
            )
            conn.execute(
                "INSERT INTO session_reports(user_id, session_date, created_at, report_json, is_admin) VALUES (?,?,?,?,0)",
                (1, "2026-09-01", later, payload),
            )
        entries = sr_module.list_recent_reports(1)
        self.assertEqual(len(entries), 2)
        # DESC -> later first
        self.assertEqual(entries[0].created_at, later)
        self.assertEqual(entries[1].created_at, earlier)

    def test_midnight_edge_jalali_day_grouping(self):
        """23:30 UTC should be 03:00 Tehran next day => different jalali day key."""
        # 2026-05-30 23:30 UTC = 2026-05-31 03:00 Asia/Tehran
        # 2026-05-30 20:00 UTC = 2026-05-30 23:30 Asia/Tehran (same Tehran day as earlier date)
        from services.utils.formatting import jalali_day_label

        iso_before_midnight = "2026-05-30T23:30:00+00:00"
        iso_same_tehran_day = "2026-05-30T20:00:00+00:00"
        iso_next_tehran_day = "2026-05-30T23:30:00+00:00"

        # Same Tehran day should give same label
        label_a = jalali_day_label(iso_same_tehran_day)
        # Convert iso_before vs after? Use distinct day boundary
        # For grouping test, derive jalali day key by calling helper
        label_b = jalali_day_label(iso_next_tehran_day)
        # 20:00 UTC is 23:30 Tehran same day 2026-05-30
        # 23:30 UTC is 03:00 Tehran next day 2026-05-31 -> labels must differ
        # Actually check: parse in Tehran
        dt_a = datetime.datetime.fromisoformat(iso_same_tehran_day).astimezone(APP_TZ)
        dt_b = datetime.datetime.fromisoformat(iso_next_tehran_day).astimezone(APP_TZ)
        self.assertNotEqual(dt_a.date(), dt_b.date(), "Test data must span Tehran midnight")
        self.assertNotEqual(label_a, label_b)

    def test_per_day_numbering_sorted_desc(self):
        """Entries sorted desc; per-day index concept: later entry has higher index when sorted asc."""
        report = _make_report()
        from services.session.summary import serialize_report

        base = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5)
        payload = serialize_report(report)
        # 3 entries same Tehran day (within retention), different times asc
        times = [
            (base + datetime.timedelta(hours=i)).isoformat() for i in range(3)
        ]
        with db_module.transaction() as conn:
            for t in times:
                conn.execute(
                    "INSERT INTO session_reports(user_id, session_date, created_at, report_json, is_admin) VALUES (?,?,?,?,0)",
                    (1, "2026-09-01", t, payload),
                )
        entries = sr_module.list_recent_reports(1)
        self.assertEqual(len(entries), 3)
        # DESC order
        sorted_desc = sorted(times, reverse=True)
        self.assertEqual([e.created_at for e in entries], sorted_desc)


if __name__ == "__main__":
    unittest.main()
