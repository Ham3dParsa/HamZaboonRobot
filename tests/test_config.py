import unittest

from config import (
    FREE_DAILY_CARD_LIMIT,
    FREE_DAILY_WORD_QUERY_LIMIT,
    GOLD_DAILY_WORD_QUERY_LIMIT,
    SILVER_DAILY_WORD_QUERY_LIMIT,
    _parse_clock,
    daily_word_query_limit_for_plan,
    presentation_for_user,
)


class ConfigTests(unittest.TestCase):
    def test_clock_parser_returns_minutes(self):
        self.assertEqual(_parse_clock("08:00", "00:00"), 480)
        self.assertEqual(_parse_clock("21:30", "00:00"), 1290)

    def test_clock_parser_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            _parse_clock("25:00", "00:00")
        with self.assertRaises(ValueError):
            _parse_clock("nine", "00:00")

    def test_plan_query_limits_are_explicit(self):
        self.assertGreater(FREE_DAILY_CARD_LIMIT, 0)
        self.assertEqual(daily_word_query_limit_for_plan("free"), FREE_DAILY_WORD_QUERY_LIMIT)
        self.assertEqual(daily_word_query_limit_for_plan("silver"), SILVER_DAILY_WORD_QUERY_LIMIT)
        self.assertEqual(daily_word_query_limit_for_plan("gold"), GOLD_DAILY_WORD_QUERY_LIMIT)

    def test_presentation_preference_requires_premium_and_valid_values(self):
        self.assertEqual(presentation_for_user("silver", "brief"), "brief")
        self.assertEqual(presentation_for_user("gold", "detailed"), "detailed")
        self.assertEqual(presentation_for_user("free", "brief"), "detailed")
        self.assertEqual(presentation_for_user("silver", "unknown"), "detailed")
        self.assertEqual(presentation_for_user("silver", None), "detailed")


if __name__ == "__main__":
    unittest.main()
