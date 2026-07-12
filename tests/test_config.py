import unittest

from config import (
    FREE_DAILY_CARD_LIMIT,
    FREE_DAILY_WORD_QUERY_LIMIT,
    GOLD_DAILY_WORD_QUERY_LIMIT,
    SILVER_DAILY_WORD_QUERY_LIMIT,
    _parse_clock,
    daily_word_query_limit_for_plan,
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
        self.assertEqual(FREE_DAILY_CARD_LIMIT, 3)
        self.assertEqual(daily_word_query_limit_for_plan("free"), FREE_DAILY_WORD_QUERY_LIMIT)
        self.assertEqual(daily_word_query_limit_for_plan("silver"), SILVER_DAILY_WORD_QUERY_LIMIT)
        self.assertEqual(daily_word_query_limit_for_plan("gold"), GOLD_DAILY_WORD_QUERY_LIMIT)


if __name__ == "__main__":
    unittest.main()
