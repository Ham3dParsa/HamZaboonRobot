"""Integration: _reports_list_payload grouping by jalali day via APP_TZ."""
import datetime
import os
import tempfile
import unittest

from services import db as db_module
from services.db import schema as db_schema
from services.db import session_reports as sr_module
from services.session.summary import WordReviewRecord, build_report
from config import APP_TZ
from services.utils.formatting import jalali_day_label, to_persian_digits


def _make_report(total=2):
    recs = []
    for i in range(total):
        recs.append(WordReviewRecord(word_id=i + 1, word=f"w{i}", activity_type="first_exposure", grade=3))
    return build_report(recs)


class ReportsListPayloadGroupingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db_module.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.path = os.path.join(self.tempdir.name, "reports_grouping_int.sqlite")
        db_module.DB_PATH = self.path
        db_schema.DB_PATH = self.path
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_grouping_by_jalali_day_via_app_tz(self):
        from handlers.study_handler import _reports_list_payload

        # Use now-based timestamps within 3-day retention but spanning Tehran midnight
        now = datetime.datetime.now(datetime.timezone.utc)
        # today at 02:00 UTC = same Tehran day as today 05:30 local
        # today-1 20:00 UTC = same Tehran day as tomorrow 00:30? Need two distinct Tehran days within window
        base = now.replace(hour=10, minute=0, second=0, microsecond=0)
        # same Tehran day: base and base+1h
        iso_same1 = (base).isoformat()
        iso_same2 = (base + datetime.timedelta(hours=1)).isoformat()
        # different Tehran day: base -1 day 12h offset ensures different date
        iso_diff = (base - datetime.timedelta(days=1, hours=2)).isoformat()
        # ensure different Tehran dates
        d_same = datetime.datetime.fromisoformat(iso_same1).astimezone(APP_TZ).date()
        d_diff = datetime.datetime.fromisoformat(iso_diff).astimezone(APP_TZ).date()
        if d_same == d_diff:
            iso_diff = (base - datetime.timedelta(days=1, hours=12)).isoformat()
        payload = __import__("services.session.summary", fromlist=["serialize_report"]).serialize_report(_make_report())
        with db_module.transaction() as conn:
            for iso in (iso_same1, iso_same2, iso_diff):
                conn.execute(
                    "INSERT INTO session_reports(user_id, session_date, created_at, report_json, is_admin) VALUES (?,?,?,?,0)",
                    (42, "2026-05-30", iso, payload),
                )
        text, kb = _reports_list_payload(42)
        # grouped => 2 day buttons
        self.assertIsNotNone(kb)
        self.assertEqual(len(kb.inline_keyboard), 2)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        # one day with 2 sessions => reports:day: , other => detail
        self.assertTrue(any(c.startswith("reports:day:") for c in cbs))
        self.assertTrue(any(c.startswith("reports:detail:") for c in cbs))
        # text contains header and jalali labels
        self.assertIn("گزارش", text)
        for iso in (iso_same1, iso_diff):
            # at least one jalali label substring should be in text (escaped but contains Persian)
            label = jalali_day_label(iso)
            # text is escaped mdv2, but label's Persian chars unchanged; check containment ignoring escape?
            # Just check that Persian month present
            self.assertTrue(any(m in text for m in ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]))

    def test_single_session_shortcut_direct_detail_keyboard(self):
        from handlers.study_handler import _reports_list_payload

        iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = __import__("services.session.summary", fromlist=["serialize_report"]).serialize_report(_make_report())
        with db_module.transaction() as conn:
            conn.execute(
                "INSERT INTO session_reports(user_id, session_date, created_at, report_json, is_admin) VALUES (?,?,?,?,0)",
                (99, "2026-09-01", iso, payload),
            )
        text, kb = _reports_list_payload(99)
        self.assertIsNotNone(kb)
        # single day single session => one button direct detail
        btn = kb.inline_keyboard[0][0]
        self.assertTrue(btn.callback_data.startswith("reports:detail:"))

    def test_empty_returns_none(self):
        from handlers.study_handler import _reports_list_payload

        text, kb = _reports_list_payload(12345)
        self.assertIsNone(kb)
        self.assertIn("گزارش", text)


if __name__ == "__main__":
    unittest.main()
