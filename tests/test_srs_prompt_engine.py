"""Phase-1 tests for the SRS staged-reveal prompt engine (#338, R1-R11).

Covers the pure prompt-engine surface: prompt-type eligibility and selection
(R11), randomized selection determinism (R4 randomization), front-stage
rendering for all five prompt types (standard / fill_blank / meaning /
synonym / direct_translate), the back-stage full card gated by the
display-toggles (R7), the fill_blank blanking + hint priority (R3), the
synonym draw from the combined visible set (R2), the dynamic language name
(R1), and the badge helpers (R5).
"""

from __future__ import annotations

import random
import unittest

from config.catalog import DISPLAY_TOGGLE_DEFAULTS, language_label
from services.utils import formatting as fmt


ALL_TOGGLES_ON = dict(DISPLAY_TOGGLE_DEFAULTS)


def _card(**overrides) -> dict:
    card = {
        "word": "read",
        "phonetic": {"ipa": "riːd"},
        "fa_meaning": "خواندن",
        "fa_explanation": "برای خواندن متن استفاده می‌شود.",
        "synonyms": ["peruse", "study"],
        "antonyms": ["write"],
        "examples": ["I read books every day.", "She reads the news."],
        "example_translations": ["من هر روز کتاب می‌خوانم.", "او اخبار را می‌خواند."],
        "grammar_tip": "Read در گذشته هم read است.",
    }
    card.update(overrides)
    return card


class PromptTypeEligibilityTests(unittest.TestCase):
    """R11 data-availability pre-filter plus toggle gating (R7/R9)."""

    def test_bare_word_card_falls_back_to_standard(self):
        card = {"word": "hello"}
        self.assertEqual(
            fmt.eligible_srs_prompt_types(card, ALL_TOGGLES_ON),
            ["standard"],
        )
        rng = random.Random(1)
        self.assertEqual(fmt.select_srs_prompt_type(card, ALL_TOGGLES_ON, rng), "standard")

    def test_meaning_and_direct_translate_need_fa_meaning(self):
        card = _card()
        eligible = fmt.eligible_srs_prompt_types(card, ALL_TOGGLES_ON)
        self.assertIn("meaning", eligible)
        self.assertIn("direct_translate", eligible)
        no_meaning = _card(fa_meaning="")
        self.assertNotIn("meaning", fmt.eligible_srs_prompt_types(no_meaning, ALL_TOGGLES_ON))
        self.assertNotIn("direct_translate", fmt.eligible_srs_prompt_types(no_meaning, ALL_TOGGLES_ON))

    def test_fill_blank_requires_examples_toggle_and_exact_word(self):
        card = _card()
        self.assertIn("fill_blank", fmt.eligible_srs_prompt_types(card, ALL_TOGGLES_ON))
        off = dict(ALL_TOGGLES_ON)
        off["examples"] = False
        self.assertNotIn("fill_blank", fmt.eligible_srs_prompt_types(card, off))
        no_exact = _card(examples=["I read books every day."])
        self.assertIn("fill_blank", fmt.eligible_srs_prompt_types(no_exact, ALL_TOGGLES_ON))

    def test_fill_blank_exact_word_match_is_word_boundary(self):
        card = _card(examples=["The reading list is long."])
        self.assertNotIn("fill_blank", fmt.eligible_srs_prompt_types(card, ALL_TOGGLES_ON))

    def test_synonym_requires_visible_combined_set(self):
        card = _card()
        self.assertIn("synonym", fmt.eligible_srs_prompt_types(card, ALL_TOGGLES_ON))

        synonyms_off = dict(ALL_TOGGLES_ON)
        synonyms_off["synonyms"] = False
        eligible = fmt.eligible_srs_prompt_types(card, synonyms_off)
        self.assertIn("synonym", eligible)  # antonyms still visible

        both_off = dict(synonyms_off)
        both_off["antonyms"] = False
        self.assertNotIn("synonym", fmt.eligible_srs_prompt_types(card, both_off))

        no_items = _card(synonyms=[], antonyms=[])
        self.assertNotIn("synonym", fmt.eligible_srs_prompt_types(no_items, ALL_TOGGLES_ON))

    def test_pool_never_empty_for_complete_card(self):
        eligible = fmt.eligible_srs_prompt_types(_card(), ALL_TOGGLES_ON)
        self.assertGreaterEqual(len(eligible), 1)

    def test_selection_always_returns_eligible_type(self):
        card = _card()
        eligible = set(fmt.eligible_srs_prompt_types(card, ALL_TOGGLES_ON))
        for seed in range(30):
            rng = random.Random(seed)
            self.assertIn(fmt.select_srs_prompt_type(card, ALL_TOGGLES_ON, rng), eligible)

    def test_selection_deterministic_with_seeded_rng(self):
        card = _card()
        first = fmt.select_srs_prompt_type(card, ALL_TOGGLES_ON, random.Random(7))
        second = fmt.select_srs_prompt_type(card, ALL_TOGGLES_ON, random.Random(7))
        self.assertEqual(first, second)


class FrontStageRenderingTests(unittest.TestCase):
    def test_standard_front_stage_rendering(self):
        text = fmt.format_srs_front_stage(
            _card(),
            "standard",
            toggles=ALL_TOGGLES_ON,
            phonetic_lines=["`riːd`"],
            badge=fmt.format_review_badge(2),
            footer="پیشرفت ۱ از ۵",
        )
        self.assertIn("*read*", text)
        self.assertIn("`riːd`", text)
        self.assertIn("⏰ آخرین مرور: ۲ روز پیش", text)
        self.assertIn("🧠 از حافظه‌ات استفاده کن", text)
        self.assertIn("👇 دکمه‌ی «نمایش پاسخ» را بزن", text)
        self.assertIn("پیشرفت ۱ از ۵", text)
        self.assertNotIn("خواندن", text)
        self.assertNotIn("I read books", text)
        self.assertNotIn("نکته‌ی گرامری", text)

    def test_hidden_front_stages_use_placeholder_header_and_hide_word(self):
        for prompt_type in ("fill_blank", "meaning", "synonym", "direct_translate"):
            with self.subTest(prompt_type=prompt_type):
                text = fmt.format_srs_front_stage(
                    _card(),
                    prompt_type,
                    toggles=ALL_TOGGLES_ON,
                    lang="en",
                )
                self.assertIn("? ? ?", text)
                self.assertNotIn("*read*", text)

    def test_fill_blank_blanks_exact_word_in_example(self):
        text = fmt.format_srs_front_stage(
            _card(),
            "fill_blank",
            toggles=ALL_TOGGLES_ON,
            rng=random.Random(1),
        )
        self.assertIn("I ? ? ? books every day", text)
        self.assertIn("🧠 واژه جا افتاده در این جمله را به یاد بیاور:", text)

    def test_fill_blank_hint_priority_synonym(self):
        text = fmt.format_srs_front_stage(
            _card(),
            "fill_blank",
            toggles=ALL_TOGGLES_ON,
            rng=random.Random(1),
        )
        self.assertIn("💡 راهنما: مترادف", text)

    def test_fill_blank_hint_priority_antonym(self):
        synonyms_off = dict(ALL_TOGGLES_ON)
        synonyms_off["synonyms"] = False
        text = fmt.format_srs_front_stage(
            _card(),
            "fill_blank",
            toggles=synonyms_off,
            rng=random.Random(1),
        )
        self.assertIn("💡 راهنما: متضاد write", text)

    def test_fill_blank_hint_priority_meaning_fallback(self):
        both_off = dict(ALL_TOGGLES_ON)
        both_off["synonyms"] = False
        both_off["antonyms"] = False
        text = fmt.format_srs_front_stage(
            _card(),
            "fill_blank",
            toggles=both_off,
            rng=random.Random(1),
        )
        self.assertIn("💡 راهنما: به معنای «خواندن»", text)

    def test_fill_blank_hint_blanks_answer_word(self):
        """A hint that itself contains the answer word must never leak it
        (owner bug report 2026-08-15) — the word is blanked like an example."""
        card = _card(synonyms=["read"], antonyms=[])
        text = fmt.format_srs_front_stage(
            card,
            "fill_blank",
            toggles=ALL_TOGGLES_ON,
            rng=random.Random(1),
        )
        self.assertIn("💡 راهنما: مترادف ? ? ?", text)
        self.assertNotIn("مترادف read", text)

    def test_meaning_prompt_shows_meaning_and_explanation_hint(self):
        text = fmt.format_srs_front_stage(
            _card(),
            "meaning",
            toggles=ALL_TOGGLES_ON,
        )
        self.assertIn("🧠 چه واژه‌ای به معنای «خواندن» است؟", text)
        self.assertIn("راهنما: برای خواندن متن استفاده می‌شود\\.", text)

    def test_meaning_prompt_hint_hidden_when_explanation_off(self):
        off = dict(ALL_TOGGLES_ON)
        off["explanation"] = False
        text = fmt.format_srs_front_stage(_card(), "meaning", toggles=off)
        self.assertIn("چه واژه‌ای به معنای «خواندن» است؟", text)
        self.assertNotIn("راهنما:", text)

    def test_meaning_prompt_blanks_answer_word_in_explanation_hint(self):
        """The meaning hint is the explanation; if the answer word appears
        inside it, the word is blanked so the front stage never leaks it
        (owner bug report 2026-08-15)."""
        card = _card(fa_explanation="read به معنی مطالعه کردن است.")
        text = fmt.format_srs_front_stage(card, "meaning", toggles=ALL_TOGGLES_ON)
        self.assertIn("راهنما: ? ? ? به معنی مطالعه کردن است\\.", text)
        self.assertNotIn("read", text)

    def test_meaning_prompt_hint_blanks_every_occurrence_of_answer_word(self):
        card = _card(fa_explanation="read و read هر دو به مطالعه اشاره دارند.")
        text = fmt.format_srs_front_stage(card, "meaning", toggles=ALL_TOGGLES_ON)
        self.assertIn("? ? ? و ? ? ? هر دو", text)
        self.assertNotIn("read", text)

    def test_direct_translate_uses_dynamic_language_name(self):
        text_de = fmt.format_srs_front_stage(_card(), "direct_translate", toggles=ALL_TOGGLES_ON, lang="de")
        self.assertEqual(language_label("de"), "آلمانی")
        self.assertIn("🧠 معادل آلمانی «خواندن» را به یاد بیاور\\.", text_de)
        text_en = fmt.format_srs_front_stage(_card(), "direct_translate", toggles=ALL_TOGGLES_ON, lang="en")
        self.assertIn("🧠 معادل انگلیسی «خواندن» را به یاد بیاور\\.", text_en)

    def test_synonym_prompt_both_categories_sentence(self):
        card = _card(synonyms=["hi"], antonyms=["bye"])
        text = fmt.format_srs_front_stage(
            card,
            "synonym",
            toggles=ALL_TOGGLES_ON,
            rng=random.Random(3),
        )
        self.assertIn("چه واژه‌ای مترادف‌های «hi» و متضادهای «bye» دارد؟", text)

    def test_synonym_prompt_only_antonyms_when_synonyms_off(self):
        synonyms_off = dict(ALL_TOGGLES_ON)
        synonyms_off["synonyms"] = False
        card = _card(synonyms=["hi"], antonyms=["bye"])
        text = fmt.format_srs_front_stage(
            card,
            "synonym",
            toggles=synonyms_off,
            rng=random.Random(3),
        )
        self.assertIn("چه واژه‌ای متضادهای «bye» دارد؟", text)
        self.assertNotIn("مترادف", text)

    def test_synonym_prompt_draws_2_to_3_items(self):
        card = _card(
            synonyms=["one", "two", "three", "four"],
            antonyms=["a", "b", "c", "d"],
        )
        for seed in range(10):
            text = fmt.format_srs_front_stage(
                card,
                "synonym",
                toggles=ALL_TOGGLES_ON,
                rng=random.Random(seed),
            )
            instruct_line = next(
                line for line in text.splitlines() if line.startswith("🧠")
            )
            drawn = instruct_line.count("«")
            self.assertIn(drawn, (2, 3))

    def test_all_front_stages_include_sub_instruction_and_footer(self):
        footer = "کارت ۳ از ۵"
        for prompt_type in ("standard", "fill_blank", "meaning", "synonym", "direct_translate"):
            with self.subTest(prompt_type=prompt_type):
                text = fmt.format_srs_front_stage(
                    _card(),
                    prompt_type,
                    toggles=ALL_TOGGLES_ON,
                    lang="en",
                    footer=footer,
                )
                self.assertIn("👇 دکمه‌ی «نمایش پاسخ» را بزن", text)
                self.assertIn(footer, text)

    def test_front_stage_escapes_dynamic_values(self):
        card = _card(word="*star*", fa_meaning="معنی *ستاره*")
        text_standard = fmt.format_srs_front_stage(
            card, "standard", toggles=ALL_TOGGLES_ON
        )
        self.assertIn(r"\*star\*", text_standard)
        text_meaning = fmt.format_srs_front_stage(card, "meaning", toggles=ALL_TOGGLES_ON)
        self.assertIn(r"\*ستاره\*", text_meaning)


class BackStageRenderingTests(unittest.TestCase):
    def test_back_stage_full_detail_when_all_toggles_on(self):
        text = fmt.format_srs_back_stage(
            _card(),
            toggles=ALL_TOGGLES_ON,
            phonetic_lines=["`riːd`"],
            footer="پیشرفت ۲ از ۵",
        )
        self.assertIn("*read*", text)
        self.assertIn("`riːd`", text)
        self.assertIn("✤ *خواندن*", text)
        self.assertIn("برای خواندن متن استفاده می‌شود\\.", text)
        self.assertIn("🟢 *مترادف:* peruse، study", text)
        self.assertIn("🔴 *متضاد:* write", text)
        self.assertIn("📝 *مثال‌ها \\+ ترجمه:*", text)
        self.assertIn("✦ I read books every day", text)
        self.assertIn("||من هر روز کتاب می‌خوانم\\.||", text)
        self.assertIn("✍️ *نکته‌ی گرامری:*", text)
        self.assertIn("🧠 با دکمه‌های توصیفی زیر یادآوری خود را ثبت کنید\\.", text)
        self.assertIn("پیشرفت ۲ از ۵", text)

    def test_back_stage_rejects_badge_parameter(self):
        """The review badge lives on the pre-reveal front stage only (owner
        bug report 2026-08-15); the back stage has no badge support."""
        with self.assertRaises(TypeError):
            fmt.format_srs_back_stage(
                _card(), toggles=ALL_TOGGLES_ON, badge="⏰ آخرین مرور"
            )

    def test_back_stage_sections_gated_by_toggles(self):
        off_syns = dict(ALL_TOGGLES_ON)
        off_syns["synonyms"] = False
        off_syns["examples"] = False
        off_syns["grammar_tip"] = False
        text = fmt.format_srs_back_stage(_card(), toggles=off_syns)
        self.assertIn("*read*", text)
        self.assertIn("✤ *خواندن*", text)
        self.assertNotIn("مترادف", text)
        self.assertNotIn("مثال‌ها", text)
        self.assertNotIn("نکته‌ی گرامری", text)

    def test_back_stage_example_translations_gated(self):
        translations_off = dict(ALL_TOGGLES_ON)
        translations_off["example_translations"] = False
        text = fmt.format_srs_back_stage(_card(), toggles=translations_off)
        self.assertIn("📝 *مثال‌ها:*", text)
        self.assertNotIn("ترجمه", text)
        self.assertNotIn("من هر روز کتاب می‌خوانم.", text)

    def test_back_stage_escapes_dynamic_values(self):
        card = _card(fa_meaning="خواندن *کتاب*")
        text = fmt.format_srs_back_stage(card, toggles=ALL_TOGGLES_ON)
        self.assertIn(r"\*کتاب\*", text)


class BadgeHelperTests(unittest.TestCase):
    def test_review_badge_uses_persian_digits(self):
        self.assertEqual(fmt.format_review_badge(3), "⏰ آخرین مرور: ۳ روز پیش")
        self.assertEqual(fmt.format_review_badge(12), "⏰ آخرین مرور: ۱۲ روز پیش")

    def test_new_card_badge_constant(self):
        self.assertEqual(fmt.NEW_CARD_BADGE, "کارت جدید ✨")


if __name__ == "__main__":
    unittest.main()