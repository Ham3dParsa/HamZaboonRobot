"""Phase 2 — keyboards grouping TDD (red)."""
import datetime
import unittest

from config import APP_TZ
from services.db.session_reports import ReportEntry
from services.utils.formatting import jalali_day_label, jalali_time_label, to_persian_digits


class ReportsKeyboardsGroupingTests(unittest.TestCase):
    def test_reports_days_keyboard_grouped_labels(self):
        from config.keyboards.admin import reports_days_keyboard

        # two days: day1 has 2 sessions, day2 has 1
        dt1 = datetime.datetime(2026, 5, 31, 10, 0, tzinfo=datetime.timezone.utc)
        dt2 = datetime.datetime(2026, 5, 31, 12, 0, tzinfo=datetime.timezone.utc)
        dt3 = datetime.datetime(2026, 5, 30, 9, 0, tzinfo=datetime.timezone.utc)
        # compute day keys via APP_TZ
        def day_key(iso):
            from handlers.study_handler import _parse_iso_utc  # type: ignore

            try:
                d = _parse_iso_utc(iso)
            except Exception:
                import datetime as _dt

                raw = iso
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                d = _dt.datetime.fromisoformat(raw)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.astimezone(APP_TZ).date().isoformat()

        iso1 = dt1.isoformat()
        iso2 = dt2.isoformat()
        iso3 = dt3.isoformat()
        e1 = ReportEntry(report_id=1, session_date="2026-05-31", created_at=iso1, total=5, learned_count=2, reviewed_count=3)
        e2 = ReportEntry(report_id=2, session_date="2026-05-31", created_at=iso2, total=3, learned_count=1, reviewed_count=2)
        e3 = ReportEntry(report_id=3, session_date="2026-05-30", created_at=iso3, total=4, learned_count=0, reviewed_count=4)
        k1 = day_key(iso1)
        k3 = day_key(iso3)
        grouped = {k1: [e1, e2], k3: [e3]}
        kb = reports_days_keyboard(grouped)
        # one button per day
        self.assertEqual(len(kb.inline_keyboard), 2)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        cbs = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        # label contains 📅 and Persian digits + نشست
        for lab in labels:
            self.assertIn("📅", lab)
            self.assertIn("نشست", lab)
            self.assertTrue(any(c in lab for c in "۰۱۲۳۴۵۶۷۸۹"), f"no Persian digits in {lab!r}")
        # multi-session day => reports:day:
        # find row for k1 (2 entries)
        multi_cb = [c for c, lab in zip(cbs, labels) if "۲" in lab or to_persian_digits(2) in lab]
        # at least one multi
        self.assertTrue(any(c.startswith("reports:day:") for c in cbs), f"cbs {cbs}")
        # single-session day => direct detail
        single_cb = [c for c in cbs if c.startswith("reports:detail:")]
        self.assertTrue(len(single_cb) >= 1)
        # single should be exactly reports:detail:3:0
        self.assertIn("reports:detail:3:0", cbs)

    def test_single_session_case_direct_open(self):
        from config.keyboards.admin import reports_days_keyboard

        iso = datetime.datetime(2026, 5, 31, 10, 0, tzinfo=datetime.timezone.utc).isoformat()
        e = ReportEntry(report_id=99, session_date="2026-05-31", created_at=iso, total=7, learned_count=1, reviewed_count=6)
        # derive key
        import datetime as _dt

        d = _dt.datetime.fromisoformat(iso).astimezone(APP_TZ).date().isoformat()
        kb = reports_days_keyboard({d: [e]})
        self.assertEqual(len(kb.inline_keyboard), 1)
        btn = kb.inline_keyboard[0][0]
        self.assertEqual(btn.callback_data, "reports:detail:99:0")
        self.assertIn("📅", btn.text)
        # contains jalali day label substring?
        expected_day = jalali_day_label(iso)
        # label is "📅 {jalali} — {n} نشست" where n=1 Persian
        self.assertIn(expected_day, btn.text)

    def test_reports_day_keyboard_session_labels(self):
        from config.keyboards.admin import reports_day_keyboard

        iso1 = datetime.datetime(2026, 5, 31, 8, 5, tzinfo=datetime.timezone.utc).isoformat()
        iso2 = datetime.datetime(2026, 5, 31, 14, 30, tzinfo=datetime.timezone.utc).isoformat()
        e1 = ReportEntry(report_id=10, session_date="2026-05-31", created_at=iso1, total=5, learned_count=2, reviewed_count=3)
        e2 = ReportEntry(report_id=11, session_date="2026-05-31", created_at=iso2, total=3, learned_count=0, reviewed_count=3)
        key = datetime.datetime.fromisoformat(iso1).astimezone(APP_TZ).date().isoformat()
        kb = reports_day_keyboard(key, [e2, e1])  # unsorted input
        # should be sorted asc by created_at => e1 first, e2 second
        rows = kb.inline_keyboard
        # 2 session rows + back row = 3
        self.assertEqual(len(rows), 3)
        first = rows[0][0]
        second = rows[1][0]
        back = rows[2][0]
        self.assertEqual(first.callback_data, "reports:detail:10:0")
        self.assertEqual(second.callback_data, "reports:detail:11:0")
        self.assertEqual(back.callback_data, "reports:back")
        self.assertIn("بازگشت به روزها", back.text)
        # label contains 🕝 time and Persian digits and نشست
        for btn in (first, second):
            self.assertIn("🕝", btn.text)
            self.assertIn("نشست", btn.text)
            self.assertIn("واژه", btn.text)
            self.assertTrue(any(c in btn.text for c in "۰۱۲۳۴۵۶۷۸۹"))
        # first label should contain time of iso1
        self.assertIn(jalali_time_label(iso1), first.text)
        self.assertIn(jalali_time_label(iso2), second.text)
        # optional split: e1 has both learned/reviewed non-zero => should contain مرور and تازه
        self.assertIn("مرور", first.text)
        self.assertIn("تازه", first.text)
        # numbering: نشست ۱ and نشست ۲ with Persian digits
        self.assertIn(f"نشست {to_persian_digits(1)}", first.text)
        self.assertIn(f"نشست {to_persian_digits(2)}", second.text)

    def test_reports_list_keyboard_backward_compat(self):
        from config.keyboards.admin import reports_list_keyboard

        iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        e = ReportEntry(report_id=1, session_date="2026-09-01", created_at=iso, total=1)
        kb = reports_list_keyboard([e])
        self.assertIsNotNone(kb)


if __name__ == "__main__":
    unittest.main()
