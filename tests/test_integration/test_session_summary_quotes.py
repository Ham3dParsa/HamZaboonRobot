"""Integration: end-of-session quotes — M10 on weak recall, M01 on same-day dues."""

from __future__ import annotations

import unittest

from services import nudges
from services.send_pretty import Backend, Message, plain, quote
from services.session.summary import WordReviewRecord, build_report
from services.utils.formatting import escape_mdv2, format_session_summary


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

    def test_m01_mdv2_escaped_exactly_once(self):
        # Same span path as format_session_summary(m01_note=...):
        # quote(plain(note)) on the MDV2 backend (full summary uses a
        # Heading span, which MDV2 does not support).
        note = nudges.render_m01(2, "واژه*تست_", 3)
        msg = Message()
        msg.add_line(quote(plain(note)))
        rendered = msg.render(Backend.MDV2)
        self.assertIn("برمی‌گردن", rendered)
        self.assertIn(escape_mdv2("واژه*تست_"), rendered)
        self.assertNotIn("\\\\", rendered)

    def test_default_render_unchanged_without_m01(self):
        report = build_report([_record(i, 3) for i in range(2)])
        plain = format_session_summary(report).render(Backend.PLAIN)
        self.assertNotIn("برمی‌گردن", plain)

    def test_empty_m01_note_leaves_render_unchanged(self):
        import random

        report = build_report([_record(i, 3) for i in range(2)])
        without = format_session_summary(report, rng=random.Random(7)).render(Backend.PLAIN)
        with_empty = format_session_summary(
            report, rng=random.Random(7), m01_note=""
        ).render(Backend.PLAIN)
        self.assertEqual(with_empty, without)


if __name__ == "__main__":
    unittest.main()
