"""Integration: end-of-session quotes — M10 on weak recall, M01 on same-day dues."""

from __future__ import annotations

import unittest

from services import nudges
from services.send_pretty import Backend
from services.session.summary import WordReviewRecord, build_report
from services.utils.formatting import format_session_summary


def _record(i: int, grade: int, next_review_date=None) -> WordReviewRecord:
    return WordReviewRecord(
        word_id=i, word=f"w{i}", activity_type="srs_review",
        grade=grade, next_review_date=next_review_date,
    )


class SessionSummaryQuotesTests(unittest.TestCase):
    def test_m10_present_on_recall_below_half(self):
        report = build_report([_record(i, 1) for i in range(4)])
        self.assertLess(report.recall_rate, 0.50)
        rendered = format_session_summary(report).render(Backend.PLAIN)
        self.assertIn("دو نکته", rendered)

    def test_m10_absent_on_strong_recall(self):
        report = build_report([_record(i, 4) for i in range(4)])
        rendered = format_session_summary(report).render(Backend.PLAIN)
        self.assertNotIn("دو نکته", rendered)

    def test_m01_appended_on_same_day_dues(self):
        today = "2026-09-07"
        records = [
            _record(1, 2, today),
            _record(2, 1, today),
            _record(3, 4, today),
        ]
        report = build_report(records)
        due = nudges.m01_due_today(records, today)
        note = nudges.render_m01(len(due), "واژه", 3)
        rendered = format_session_summary(report, m01_note=note).render(Backend.PLAIN)
        self.assertIn("برمی‌گردن", rendered)

    def test_default_render_unchanged_without_m01(self):
        report = build_report([_record(i, 3) for i in range(2)])
        plain = format_session_summary(report).render(Backend.PLAIN)
        self.assertNotIn("برمی‌گردن", plain)


if __name__ == "__main__":
    unittest.main()
