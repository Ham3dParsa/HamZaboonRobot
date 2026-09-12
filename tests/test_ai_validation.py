import json
import unittest
from unittest.mock import patch

from services.ai import ai
from services.ai import card_validation
from services.ai import telemetry


class CardValidationAliasTests(unittest.TestCase):
    """REF5-T2: ai.* remain as re-export aliases of card_validation (dead-ref guard)."""

    def test_ai_reexports_are_card_validation_objects(self):
        self.assertIs(ai.validate_card, card_validation.validate_card)
        self.assertIs(ai.card_repair_fields, card_validation.card_repair_fields)
        self.assertIs(ai.validate_card_patch, card_validation.validate_card_patch)
        self.assertIs(ai.validate_batch, card_validation.validate_batch)
        self.assertIs(ai.CardValidationError, card_validation.CardValidationError)
        self.assertIs(ai.BatchValidationError, card_validation.BatchValidationError)
        self.assertIs(ai.normalize_phonetic, card_validation.normalize_phonetic)


def valid_card(word: str) -> dict:
    return {
        "word": word,
        "phonetic": "",
        "fa_meaning": "معنی",
        "fa_explanation": "توضیح",
        "synonyms": [],
        "antonyms": [],
        "examples": ["Example one.", "Example two."],
        "example_translations": ["مثال اول.", "مثال دوم."],
        "grammar_tip": "",
    }


class BatchValidationTests(unittest.TestCase):
    def test_compact_card_aliases_validate_to_the_persisted_contract(self):
        compact = {
            "w": "hello",
            "ph": "",
            "m": "سلام",
            "x": "توضیح",
            "s": [],
            "a": [],
            "e": ["Hello one.", "Hello two."],
            "t": ["سلام اول.", "سلام دوم."],
            "g": "",
        }

        self.assertEqual(ai.validate_card(compact)["word"], "hello")
        self.assertIn("example_translations", ai.validate_card(compact))

    def test_card_validation_requires_exactly_two_paired_examples(self):
        card = valid_card("hello")
        card["examples"] = ["Example."]
        card["example_translations"] = ["مثال."]
        with self.assertRaisesRegex(ai.CardValidationError, "exactly two"):
            ai.validate_card(card)

        card = valid_card("hello")
        card["example_translations"] = ["مثال اول."]
        with self.assertRaisesRegex(ai.CardValidationError, "exactly two"):
            ai.validate_card(card)

    def test_populated_synonym_and_antonym_lists_need_distinct_items(self):
        # Single item is now valid (no minimum count requirement)
        card = valid_card("hello")
        card["synonyms"] = ["hi"]
        self.assertEqual(ai.validate_card(card)["synonyms"], ["hi"])

        # But duplicates (case-insensitive) should still fail
        card = valid_card("hello")
        card["antonyms"] = ["bye", " BYE "]
        with self.assertRaisesRegex(ai.CardValidationError, "antonyms"):
            ai.validate_card(card)

    def test_empty_optional_synonym_and_antonym_lists_remain_valid(self):
        card = valid_card("hello")
        self.assertEqual(ai.validate_card(card)["word"], "hello")

    def test_card_repair_fields_are_minimal_and_pair_aware(self):
        card = valid_card("hello")
        card["example_translations"] = ["مثال اول."]
        self.assertEqual(
            ai.card_repair_fields(card),
            ["examples", "example_translations"],
        )

        # Phonetic dict with empty ipa should be flagged for repair
        card = valid_card("hello")
        card["phonetic"] = {"ipa": ""}
        self.assertEqual(ai.card_repair_fields(card), ["phonetic"])

    def test_legacy_phonetic_values_are_marked_for_repair(self):
        card = valid_card("hello")
        card["phonetic"] = "کومپلِکسیِرت"
        self.assertEqual(ai.card_repair_fields(card), ["phonetic"])

    def test_card_repair_patch_rejects_extra_or_duplicate_fields(self):
        with self.assertRaisesRegex(ai.CardValidationError, "exactly"):
            ai.validate_card_patch(
                {"examples": ["One.", "Two."]},
                ["examples", "example_translations"],
            )
        with self.assertRaises(ai.CardValidationError):
            ai.validate_card_patch(
                {"word": "hello", "extra": "no"},
                ["word"],
            )

    def test_six_compact_cards_validate_without_changing_batch_shape(self):
        cards = ai.validate_batch(
            [
                {
                    "w": f"word-{index}",
                    "m": "معنی",
                    "x": "توضیح",
                    "e": [f"Example {index} one.", f"Example {index} two."],
                    "t": [f"مثال {index} اول.", f"مثال {index} دوم."],
                }
                for index in range(6)
            ],
            expected_count=6,
        )

        self.assertEqual(len(cards), 6)
        self.assertEqual([card["word"] for card in cards], [f"word-{i}" for i in range(6)])

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
                "duplicates_against_avoid": 0,
                "duplicates_within_batch": 0,
                "avoid_words": 0,
            },
        )
        self.assertEqual(
            rejection_reasons,
            {"Card field 'examples' must be a list of strings": 1},
        )

    def test_ask_batch_raises_when_validation_accepts_no_cards(self):
        with (
            patch.object(ai, "_request_json", return_value=[valid_card("hello")]),
            patch.object(telemetry, "_log_llm_request"),
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

    def test_diagnostics_distinguish_avoid_list_and_batch_duplicates(self):
        diagnostics: dict[str, int] = {}

        cards = ai.validate_batch(
            [valid_card("known"), valid_card("new"), valid_card("new")],
            expected_count=3,
            used_words=["known"],
            diagnostics=diagnostics,
        )

        self.assertEqual([card["word"] for card in cards], ["new"])
        self.assertEqual(diagnostics["duplicates_against_avoid"], 1)
        self.assertEqual(diagnostics["duplicates_within_batch"], 1)
        self.assertEqual(diagnostics["duplicates"], 2)
        self.assertEqual(diagnostics["avoid_words"], 1)

    def test_valid_cards_are_counted(self):
        diagnostics: dict[str, int] = {}

        cards = ai.validate_batch(
            [valid_card("hello"), valid_card("world")],
            expected_count=2,
            diagnostics=diagnostics,
        )

        self.assertEqual([card["word"] for card in cards], ["hello", "world"])
        self.assertEqual(diagnostics["accepted"], 2)


class JsonCodecTests(unittest.TestCase):
    """REF5-T1: _extract_json cases against the canonical json_codec leaf."""

    def test_unfenced_object(self):
        from services.ai import json_codec

        self.assertEqual(
            json_codec._extract_json('{"word": "hello"}'), {"word": "hello"}
        )

    def test_fenced_json_block(self):
        from services.ai import json_codec

        self.assertEqual(
            json_codec._extract_json('```json\n{"word": "hello"}\n```'),
            {"word": "hello"},
        )

    def test_leading_prose_before_json(self):
        from services.ai import json_codec

        self.assertEqual(
            json_codec._extract_json('Here is your card: {"word": "hello"}'),
            {"word": "hello"},
        )

    def test_trailing_prose_after_json(self):
        from services.ai import json_codec

        self.assertEqual(
            json_codec._extract_json('{"word": "hello"} hope this helps'),
            {"word": "hello"},
        )

    def test_double_json_returns_first_value(self):
        from services.ai import json_codec

        self.assertEqual(
            json_codec._extract_json('{"a": 1} {"b": 2}'), {"a": 1}
        )

    def test_no_json_value_raises(self):
        from services.ai import json_codec

        with self.assertRaisesRegex(json.JSONDecodeError, "No JSON value found"):
            json_codec._extract_json("just some words without structure")

    def test_ai_alias_routes_to_codec(self):
        from services.ai import json_codec

        self.assertIs(ai._extract_json, json_codec._extract_json)
        sample = '```json\n{"word": "hello"}\n```'
        self.assertEqual(
            ai._extract_json(sample), json_codec._extract_json(sample)
        )


if __name__ == "__main__":
    unittest.main()
