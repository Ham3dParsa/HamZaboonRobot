import unittest

from config import (
    FREE_DAILY_CARD_LIMIT,
    FREE_DAILY_WORD_QUERY_LIMIT,
    GOLD_DAILY_WORD_QUERY_LIMIT,
    SILVER_DAILY_WORD_QUERY_LIMIT,
    daily_word_query_limit_for_plan,
    presentation_for_user,
)


class ConfigTests(unittest.TestCase):
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
