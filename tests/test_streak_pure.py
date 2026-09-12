"""REF6-T1 red-first: pure streak date math owns same-day/yesterday/gap rules."""
import unittest


class NextStreakTests(unittest.TestCase):
    def test_same_day_is_idempotent(self):
        from services.streak import next_streak
        self.assertEqual(next_streak(5, "2026-08-10", "2026-08-10"), 5)

    def test_consecutive_day_increments(self):
        from services.streak import next_streak
        self.assertEqual(next_streak(5, "2026-08-09", "2026-08-10"), 6)

    def test_gap_resets_to_one(self):
        from services.streak import next_streak
        self.assertEqual(next_streak(6, "2026-08-08", "2026-08-10"), 1)

    def test_first_touch_starts_at_one(self):
        from services.streak import next_streak
        self.assertEqual(next_streak(0, None, "2026-08-10"), 1)

    def test_yesterday_derives_from_explicit_today(self):
        from services.streak import next_streak
        # yesterday must derive from resolved today, not the real clock
        self.assertEqual(next_streak(5, "2026-08-09", "2026-08-10"), 6)
        self.assertEqual(next_streak(5, "2026-08-08", "2026-08-10"), 1)

    def test_invalid_today_propagates(self):
        from services.streak import next_streak
        with self.assertRaises(ValueError):
            next_streak(5, "2026-08-09", "not-a-date")


if __name__ == "__main__":
    unittest.main()
