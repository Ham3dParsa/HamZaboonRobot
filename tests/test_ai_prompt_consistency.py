"""F4/R4 — cross-output compact-schema consistency for card prompt builders.

The audit required that the same compact card schema be emitted identically
across the card generators. The admin custom-test path builds its system prompt
via ``daily_batch_system_prompt`` (``handlers/admin_ai.py``), so the relevant
living builders are ``daily_card_system_prompt``, ``daily_batch_system_prompt``
(note: ``daily_card`` is deprecated and slated for extraction), and
``custom_word_system_prompt``. All three must embed the single-sourced
``_card_schema`` — no inline divergence.
"""

import unittest

from config.catalog import example_language_label, language_label
from services.ai import prompts


class CardPromptCompactConsistencyTests(unittest.TestCase):
    def test_card_builders_embed_single_sourced_compact_schema(self):
        lang, goal, level = "en", "general", "beginner"
        lang_fa = language_label(lang)

        builders = {
            "daily_card": (
                prompts.daily_card_system_prompt(lang, goal, level=level, compact=True),
                example_language_label(lang),
            ),
            "daily_batch": (
                prompts.daily_batch_system_prompt(lang, goal, level, 3, compact=True),
                example_language_label(lang),
            ),
            "custom_word": (
                prompts.custom_word_system_prompt(lang, level=level, compact=True),
                lang_fa,
            ),
        }

        schemas = {}
        for name, (prompt, example_lang) in builders.items():
            schema = prompts._card_schema(lang_fa, example_lang, compact=True)
            self.assertIn(
                schema, prompt,
                f"{name} does not embed the canonical compact card schema",
            )
            schemas[name] = schema

        # Both "card" builders construct example sentences in the example
        # language, so their compact schema block must be byte-identical.
        self.assertEqual(schemas["daily_card"], schemas["daily_batch"])
