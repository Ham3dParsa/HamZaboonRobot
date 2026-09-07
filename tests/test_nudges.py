"""Unit tests for services/nudges.py (issue #467, dims 1/5/6)."""

from __future__ import annotations

import datetime
import unittest

from config import APP_TZ
from services import nudges
from services.session.summary import WordReviewRecord, build_report
from services.utils.formatting import to_persian_digits


def _at(hour: int, minute: int) -> datetime.datetime:
    return datetime.datetime(2026, 9, 7, hour, minute, tzinfo=APP_TZ)


class QuietHoursTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertFalse(nudges.is_quiet_hours(_at(22, 59)))
        self.assertTrue(nudges.is_quiet_hours(_at(23, 0)))
        self.assertTrue(nudges.is_quiet_hours(_at(7, 59)))
        self.assertFalse(nudges.is_quiet_hours(_at(8, 0)))

    def test_windows(self):
        self.assertEqual(nudges.window_for(_at(9, 0)), "morning")
        self.assertEqual(nudges.window_for(_at(13, 0)), "noon")
        self.assertEqual(nudges.window_for(_at(20, 0)), "evening")
        self.assertEqual(nudges.window_for(_at(0, 30)), "night")


class SilenceTests(unittest.TestCase):
    def test_active_session_silences(self):
        self.assertTrue(nudges.evaluate_silence(1, {"remaining": 3}, True, 5, True))

    def test_exhausted_budget_silences(self):
        self.assertTrue(nudges.evaluate_silence(1, {"remaining": 0}, False, 5, True))
        self.assertTrue(nudges.evaluate_silence(1, 0, False, 5, True))

    def test_nothing_to_study_silences(self):
        self.assertTrue(nudges.evaluate_silence(1, {"remaining": 2}, False, 0, False))

    def test_due_or_new_cards_allow(self):
        self.assertFalse(nudges.evaluate_silence(1, {"remaining": 2}, False, 4, False))
        self.assertFalse(nudges.evaluate_silence(1, {"remaining": 2}, False, 0, True))


class PriorityTests(unittest.TestCase):
    def test_hierarchy(self):
        self.assertEqual(nudges.select_nudge(m03=True, m06=True), "M03")
        self.assertEqual(nudges.select_nudge(m06=True, m08=True), "M06")
        self.assertEqual(nudges.select_nudge(m08=True, m05=True), "M08")
        self.assertEqual(nudges.select_nudge(m05=True, m09=True), "M05")
        self.assertEqual(nudges.select_nudge(m09=True, m04=True), "M09")
        self.assertEqual(nudges.select_nudge(m04=True), "M04")
        self.assertIsNone(nudges.select_nudge())

    def test_m04_promotion_jumps_to_priority_2(self):
        self.assertTrue(nudges.should_promote_m04(3, True, "noon"))
        self.assertFalse(nudges.should_promote_m04(2, True, "noon"))
        self.assertFalse(nudges.should_promote_m04(5, False, "noon"))
        self.assertFalse(nudges.should_promote_m04(5, True, "morning"))
        self.assertEqual(
            nudges.select_nudge(m06=True, m04=True, m04_promoted=True), "M04"
        )

    def test_m02_defers_in_quiet_only(self):
        self.assertTrue(nudges.should_defer_m02(_at(0, 5)))
        self.assertFalse(nudges.should_defer_m02(_at(9, 0)))

    def test_caps(self):
        self.assertTrue(nudges.can_send(0, 0))
        self.assertTrue(nudges.can_send(0, 1))
        self.assertFalse(nudges.can_send(1, 0))
        self.assertFalse(nudges.can_send(0, 2))
        self.assertIn("1", nudges.nudge_counter_key(1, "2026-09-07"))


class SlotTests(unittest.TestCase):
    def test_raw_slots_persian_digits_no_preescape(self):
        text = nudges.render_m01(3, "واژه*تست_", 5)
        self.assertIn(to_persian_digits(3), text)
        self.assertIn(to_persian_digits(5), text)
        # Raw: dynamic value verbatim, escaping happens once at send site.
        self.assertIn("واژه*تست_", text)
        self.assertNotIn("\\", text)
        self.assertNotIn("3", text.replace("۳", ""))

    def test_render_m06_static(self):
        self.assertEqual(nudges.render_m06(), nudges.NUDGE_TEMPLATES["M06"])

    def test_hours_rounding(self):
        now = datetime.datetime(2026, 9, 7, 10, 0, tzinfo=datetime.timezone.utc)
        nxt = now + datetime.timedelta(minutes=100)
        self.assertEqual(nudges.hours_between(now, nxt), 2)
        past = now - datetime.timedelta(hours=5)
        self.assertEqual(nudges.hours_between(now, past), 1)

    def test_persian_law(self):
        self.assertNotIn("M10", nudges.NUDGE_TEMPLATES)
        for mid, template in nudges.NUDGE_TEMPLATES.items():
            self.assertNotIn("·", template, mid)
            self.assertNotIn("—", template, mid)
            self.assertNotIn("|", template, mid)

    def test_m10_aliases_pick_motivation(self):
        from services.session.summary import pick_motivation

        records = [
            WordReviewRecord(word_id=i, word=f"w{i}", activity_type="srs_review", grade=1)
            for i in range(4)
        ]
        report = build_report(records)
        self.assertLess(report.recall_rate, 0.50)
        self.assertEqual(nudges.m10_for_report(report), pick_motivation(report))

    def test_m01_due_today_filters(self):
        today = "2026-09-07"
        records = [
            WordReviewRecord(word_id=1, word="a", activity_type="srs_review",
                             grade=2, next_review_date=today),
            WordReviewRecord(word_id=2, word="b", activity_type="srs_review",
                             grade=3, next_review_date=today),
            WordReviewRecord(word_id=3, word="c", activity_type="srs_review",
                             grade=1, next_review_date="2026-09-08"),
        ]
        due = nudges.m01_due_today(records, today)
        self.assertEqual([r.word_id for r in due], [1])


if __name__ == "__main__":
    unittest.main()
