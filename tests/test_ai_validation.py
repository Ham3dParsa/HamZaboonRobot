import unittest
from unittest.mock import patch

import ai


def valid_card(word: str) -> dict:
    return {
        "word": word,
        "phonetic": "",
        "fa_meaning": "معنی",
        "fa_explanation": "توضیح",
        "synonyms": [],
        "antonyms": [],
        "examples": ["Example."],
        "example_translations": ["مثال."],
        "grammar_tip": "",
    }


class BatchValidationTests(unittest.TestCase):
    def test_diagnostics_explain_an_empty_batch(self):
        diagnostics: dict[str, int] = {}
        rejection_reasons: dict[str, int] = {}

        cards = ai.validate_batch(
            [{"word": "missing required fields"}],
            expected_count=1,
            diagnostics=diagnostics,
            rejection_reasons=rejection_reasons,
        )

        self.assertEqual(cards, [])
        self.assertEqual(
            diagnostics,
            {
                "received": 1,
                "accepted": 0,
                "validation_rejected": 1,
                "duplicates": 0,
            },
        )
        self.assertEqual(
            rejection_reasons,
            {"Card field 'examples' must be a list of strings": 1},
        )

    def test_ask_batch_raises_when_validation_accepts_no_cards(self):
        with (
            patch.object(ai, "_request_json", return_value=[valid_card("hello")]),
            patch.object(ai, "_log_llm_request"),
            patch.object(ai, "_model", return_value="test-model"),
        ):
            with self.assertRaises(ai.BatchValidationError) as context:
                ai.ask_batch(
                    "prompt",
                    expected_count=1,
                    used_words=["hello"],
                )

        self.assertIn("No valid cards", str(context.exception))
        self.assertEqual(context.exception.diagnostics["duplicates"], 1)

    def test_valid_cards_are_counted(self):
        diagnostics: dict[str, int] = {}

        cards = ai.validate_batch(
            [valid_card("hello"), valid_card("world")],
            expected_count=2,
            diagnostics=diagnostics,
        )

        self.assertEqual([card["word"] for card in cards], ["hello", "world"])
        self.assertEqual(diagnostics["accepted"], 2)


if __name__ == "__main__":
    unittest.main()
