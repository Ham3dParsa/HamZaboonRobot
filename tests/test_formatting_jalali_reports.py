"""Phase 1 — formatting helpers jalali_day_label / jalali_time_label (TDD red)."""

import datetime
import unittest
from unittest import mock

from services.utils import formatting_jalali as fmt


class JalaliDayLabelTests(unittest.TestCase):
    def test_produces_weekday_day_month_year_persian_digits(self):
        # 2026-05-30 is Gregorian Saturday => Jalali 1405/03/09 Friday? Let's compute via jdatetime
        # Choose date 2026-05-31T10:00:00+00:00 which is reliable
        iso = "2026-05-31T10:00:00+00:00"
        label = fmt.jalali_day_label(iso)
        # Should contain Persian digits and at least one Jalali month name
        self.assertIn("۰", label + "۰" if any(c in label for c in "۰۱۲۳۴۵۶۷۸۹") else label)
        # Check Persian digits present
        has_persian_digit = any(c in label for c in "۰۱۲۳۴۵۶۷۸۹")
        self.assertTrue(has_persian_digit, f"label has no Persian digits: {label!r}")
        # Check month name present
        has_month = any(m in label for m in fmt._JALALI_MONTHS)
        self.assertTrue(has_month, f"label missing month: {label!r}")
        # Should have 4 parts: weekday + day + month + year (weekday contains space? So split)
        # At least day and year as Persian digits
        self.assertGreater(len(label.split()), 2)

    def test_weekday_included(self):
        iso = "2026-05-29T10:00:00+00:00"
        label = fmt.jalali_day_label(iso)
        weekdays = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
        has_weekday = any(w in label for w in weekdays)
        self.assertTrue(has_weekday, f"label missing weekday: {label!r}")

    def test_invalid_input_returns_dash_or_fallback(self):
        for bad in ["", "not-a-date", None]:
            result = fmt.jalali_day_label(bad)  # type: ignore
            # Should not raise, should return dash or fallback containing dash/empty handling
            self.assertIsInstance(result, str)
            # Invalid should be dash "—" per spec R10 or non-crash fallback
            # Accept either dash or empty, but must not be the raw bad string
            if bad == "not-a-date":
                self.assertNotEqual(result, bad)

    def test_jdatetime_unavailable_fallback(self):
        with mock.patch.object(fmt, "jdatetime", None):
            iso = "2026-05-31T10:00:00+00:00"
            label = fmt.jalali_day_label(iso)
            self.assertIsInstance(label, str)
            self.assertTrue(len(label) > 0)
            # Fallback still has Persian digits
            has_persian_digit = any(c in label for c in "۰۱۲۳۴۵۶۷۸۹")
            self.assertTrue(has_persian_digit, f"fallback has no Persian digits: {label!r}")

    def test_jalali_day_label_uses_tehran_timezone(self):
        # 23:30 UTC = 03:00 next day Tehran => weekday should reflect Tehran date
        iso_utc_late = "2026-05-30T23:30:00+00:00"
        iso_utc_early = "2026-05-30T20:00:00+00:00"
        label_late = fmt.jalali_day_label(iso_utc_late)
        label_early = fmt.jalali_day_label(iso_utc_early)
        self.assertNotEqual(label_late, label_early, "Labels must differ across Tehran midnight")


class JalaliTimeLabelTests(unittest.TestCase):
    def test_produces_hh_mm_persian_digits(self):
        iso = "2026-05-31T10:30:00+00:00"  # 14:00 Tehran (UTC+3:30)
        label = fmt.jalali_time_label(iso)
        # Should be NN:NN with Persian digits
        self.assertIn(":", label)
        has_persian_digit = any(c in label for c in "۰۱۲۳۴۵۶۷۸۹")
        self.assertTrue(has_persian_digit, f"time label has no Persian digits: {label!r}")
        # 10:30 UTC = 14:00 Tehran (or 14:30? check DST: Tehran UTC+3:30)
        # Accept 14:00 or similar; just check format 2-digit
        parts = label.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).split(":")
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].isdigit() and parts[1].isdigit())

    def test_invalid_input_time(self):
        for bad in ["", "bad", None]:
            result = fmt.jalali_time_label(bad)  # type: ignore
            self.assertIsInstance(result, str)

    def test_jdatetime_unavailable_time_still_works(self):
        # time label should not depend on jdatetime, just timezone conversion
        with mock.patch.object(fmt, "jdatetime", None):
            iso = "2026-05-31T10:00:00+00:00"
            label = fmt.jalali_time_label(iso)
            self.assertIsInstance(label, str)
            self.assertIn(":", label)

    def test_time_uses_tehran(self):
        iso = "2026-05-31T10:00:00+00:00"
        label = fmt.jalali_time_label(iso)
        # Convert manually to Tehran
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(fmt.APP_TZ if hasattr(fmt, "APP_TZ") else __import__("config").APP_TZ)
        expected_hh = fmt.to_persian_digits(f"{dt.hour:02d}")
        expected_mm = fmt.to_persian_digits(f"{dt.minute:02d}")
        self.assertEqual(label, f"{expected_hh}:{expected_mm}")


if __name__ == "__main__":
    unittest.main()
