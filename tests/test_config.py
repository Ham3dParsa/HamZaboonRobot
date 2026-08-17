import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema

from config import (
    cards_per_session_for_plan,
    daily_card_count_for_plan,
    daily_word_query_limit_for_plan,
    max_sessions_for_plan,
    plan_display_name,
    presentation_for_user,
)
from config.catalog import (
    DISPLAY_TOGGLE_DEFAULTS,
    DISPLAY_TOGGLE_FIELDS,
    HIGH_VALUE_TOGGLES,
    LOW_VALUE_TOGGLES,
    validate_catalog,
)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def test_plans_have_expected_specs(self):
        expected = {
            "free": {"query": 2, "sessions": 2, "cards": 3},
            "bronze": {"query": 4, "sessions": 3, "cards": 3},
            "silver": {"query": 7, "sessions": 3, "cards": 5},
            "gold": {"query": 12, "sessions": 4, "cards": 7},
            "emerald": {"query": 20, "sessions": 5, "cards": 9},
        }
        for plan, spec in expected.items():
            with self.subTest(plan=plan):
                self.assertEqual(daily_word_query_limit_for_plan(plan), spec["query"])
                self.assertEqual(max_sessions_for_plan(plan), spec["sessions"])
                self.assertEqual(cards_per_session_for_plan(plan), spec["cards"])
                self.assertEqual(
                    daily_card_count_for_plan(plan),
                    spec["sessions"] * spec["cards"],
                )

    def test_plan_query_limits_are_explicit(self):
        self.assertEqual(daily_word_query_limit_for_plan("free"), 2)
        self.assertEqual(daily_word_query_limit_for_plan("silver"), 7)
        self.assertEqual(daily_word_query_limit_for_plan("gold"), 12)
        self.assertEqual(daily_word_query_limit_for_plan("emerald"), 20)

    def test_unknown_plan_falls_back_to_free(self):
        self.assertEqual(
            daily_word_query_limit_for_plan("unknown"),
            daily_word_query_limit_for_plan("free"),
        )
        self.assertEqual(
            max_sessions_for_plan("unknown"),
            max_sessions_for_plan("free"),
        )
        self.assertEqual(
            cards_per_session_for_plan("unknown"),
            cards_per_session_for_plan("free"),
        )

    def test_plan_display_names(self):
        self.assertEqual(plan_display_name("free"), "رایگان")
        self.assertEqual(plan_display_name("bronze"), "برنزی")
        self.assertEqual(plan_display_name("silver"), "نقره‌ای")
        self.assertEqual(plan_display_name("gold"), "طلایی")
        self.assertEqual(plan_display_name("emerald"), "زمردی")

    def test_presentation_preference_requires_premium_and_valid_values(self):
        self.assertEqual(presentation_for_user("silver", "brief"), "brief")
        self.assertEqual(presentation_for_user("gold", "detailed"), "detailed")
        self.assertEqual(presentation_for_user("free", "brief"), "detailed")
        self.assertEqual(presentation_for_user("silver", "unknown"), "detailed")
        self.assertEqual(presentation_for_user("silver", None), "detailed")


class DisplayToggleCatalogTests(unittest.TestCase):
    def test_toggle_fields_are_exhaustive_and_unique(self):
        self.assertEqual(
            set(DISPLAY_TOGGLE_FIELDS),
            {
                "explanation",
                "synonyms",
                "antonyms",
                "examples",
                "example_translations",
                "grammar_tip",
                "phonetic",
            },
        )
        self.assertEqual(len(DISPLAY_TOGGLE_FIELDS), len(set(DISPLAY_TOGGLE_FIELDS)))

    def test_high_and_low_value_toggles_partition_the_field_set(self):
        self.assertEqual(
            HIGH_VALUE_TOGGLES | LOW_VALUE_TOGGLES,
            set(DISPLAY_TOGGLE_FIELDS),
        )
        self.assertEqual(HIGH_VALUE_TOGGLES & LOW_VALUE_TOGGLES, set())

    def test_defaults_cover_all_fields_and_are_all_true(self):
        self.assertEqual(set(DISPLAY_TOGGLE_DEFAULTS), set(DISPLAY_TOGGLE_FIELDS))
        for field in DISPLAY_TOGGLE_FIELDS:
            self.assertTrue(DISPLAY_TOGGLE_DEFAULTS[field], field)

    def test_validate_catalog_passes_with_toggle_registry(self):
        validate_catalog()


if __name__ == "__main__":
    unittest.main()