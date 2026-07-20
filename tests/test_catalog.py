import unittest

from config.catalog import (
    DEFAULT_LEVEL,
    GOALS,
    LANGUAGES,
    LEVELS,
    goal_label,
    language_label,
    level_cefr,
    validate_catalog,
)
from services.ai.prompts import daily_batch_system_prompt, grammar_tip_system_prompt


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
        self.assertIn("IPA", prompt)
        self.assertIn("Persian", prompt)

    def test_new_languages_are_available_through_the_catalog(self):
        self.assertEqual(LANGUAGES["tr"].name_fa, "ترکی استانبولی")
        self.assertEqual(LANGUAGES["he"].name_fa, "عبری")
        prompt = daily_batch_system_prompt("tr", "general", "beginner", 2)
        self.assertIn("ترکی استانبولی", prompt)

    def test_compact_batch_prompt_declares_alias_contract(self):
        prompt = daily_batch_system_prompt("en", "general", "beginner", 6, compact=True)
        self.assertIn('"w":', prompt)
        self.assertIn("فقط همین کلیدها", prompt)
        self.assertNotIn('"word":', prompt)
        self.assertIn("دقیقاً دو مثال", prompt)
        self.assertIn('"e":["جمله اول', prompt)
        self.assertIn('"t":["ترجمه فارسی جمله اول', prompt)

    def test_default_batch_prompt_declares_rich_card_contract(self):
        prompt = daily_batch_system_prompt("en", "general", "beginner", 6)
        self.assertIn('"examples": [', prompt)
        self.assertIn("جمله نمونه دوم", prompt)
        self.assertIn("1-3 مورد متفاوت", prompt)

    def test_grammar_prompt_can_avoid_recent_topics(self):
        prompt = grammar_tip_system_prompt(
            "en",
            "general",
            "beginner",
            avoid_topics=["Adjectives"],
        )
        self.assertIn("Adjectives", prompt)
        self.assertIn("تکرار نکن", prompt)


if __name__ == "__main__":
    unittest.main()
