import unittest

from catalog import (
    DEFAULT_LEVEL,
    GOALS,
    LANGUAGES,
    LEVELS,
    goal_label,
    language_label,
    level_cefr,
    validate_catalog,
)
from prompts import daily_batch_system_prompt


class CatalogTests(unittest.TestCase):
    def test_catalog_metadata_is_internally_consistent(self):
        validate_catalog()
        self.assertEqual(set(LANGUAGES), {option.code for option in LANGUAGES.values()})
        self.assertEqual(set(GOALS), {option.code for option in GOALS.values()})
        self.assertEqual(set(LEVELS), {option.code for option in LEVELS.values()})

    def test_unknown_values_have_controlled_fallbacks(self):
        self.assertEqual(language_label("retired"), "retired")
        self.assertEqual(goal_label("retired"), "عمومی")
        self.assertEqual(level_cefr("retired"), "")

    def test_prompt_consumes_catalog_metadata(self):
        prompt = daily_batch_system_prompt("de", "toefl", "beginner", 2)
        self.assertIn(LANGUAGES["de"].name_fa, prompt)
        self.assertIn(GOALS["toefl"].name_fa, prompt)
        self.assertIn(LEVELS[DEFAULT_LEVEL].cefr, prompt)
        self.assertIn("Nominativ", prompt)


if __name__ == "__main__":
    unittest.main()
