"""REF2-T2: formatting_jalali + formatting_cards leaves + formatting.py facade.

Proves the verbatim split preserves behavior (T1 precedent):
- ``services/utils/formatting.py`` defines no functions/classes itself; it
  re-exports the exact same objects from the two new leaves (no parallel
  fallback definitions; old defs gone same PR).
- Jalali leaf never imports the cards leaf (no cycle); cards imports jalali
  one-directionally for the shared date helpers only.
- Golden outputs are byte-identical through facade and leaf paths.
"""

import ast
import unittest
from pathlib import Path

from services.utils import formatting, formatting_cards, formatting_jalali

JALALI_NAMES = (
    "_to_jalali_str",
    "to_jalali_str",
    "_JALALI_MONTHS",
    "_JALALI_WEEKDAYS",
    "_weekday_name",
    "_parse_iso_to_app_tz",
    "parse_iso_to_app_tz",
    "jalali_day_label",
    "jalali_time_label",
    "reports_jalali_group_key",
    "_ISO_DAY_RE",
    "is_iso_day_key",
    "reports_day_sort_key",
    "_app_date",
    "_jalali_day_month",
    "_relative_next_review",
)

CARD_NAMES = (
    "SRS_PROMPT_TYPES",
    "format_review_badge",
    "days_since_review",
    "format_next_review_text",
    "CardPreparationError",
    "format_card_message",
    "format_card",
    "_phonetic_code_spans",
    "eligible_srs_prompt_types",
    "select_srs_prompt_type",
    "format_srs_front_stage",
    "format_srs_back_stage",
    "_saved_word_card",
    "phonetic_lines",
    "format_grammar_tip",
    "ASK_WORD_PROMPT",
    "_stage_for_record",
    "_stage_modifier",
    "_stage_counts",
    "_heat_label",
    "format_session_summary",
    "format_session_detail_page",
    "format_summary_legend",
)


class TestReexportSurface(unittest.TestCase):
    def test_jalali_names_reexport_same_objects(self):
        for name in JALALI_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(formatting, name),
                    getattr(formatting_jalali, name),
                    f"formatting.{name} must be the formatting_jalali object",
                )

    def test_card_names_reexport_same_objects(self):
        for name in CARD_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(formatting, name),
                    getattr(formatting_cards, name),
                    f"formatting.{name} must be the formatting_cards object",
                )

    def test_facade_defines_nothing(self):
        """Route-delete proof: the facade holds imports/aliases only."""
        tree = ast.parse(Path(formatting.__file__).read_text(encoding="utf-8"))
        defs = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        self.assertEqual(defs, [], f"facade must define nothing, found {defs}")

    def test_golden_outputs_identical_through_both_paths(self):
        iso = "2026-05-31T10:00:00+00:00"
        self.assertEqual(
            formatting.jalali_day_label(iso), formatting_jalali.jalali_day_label(iso)
        )
        self.assertEqual(
            formatting.jalali_time_label(iso), formatting_jalali.jalali_time_label(iso)
        )
        self.assertEqual(
            formatting.reports_jalali_group_key(iso),
            formatting_jalali.reports_jalali_group_key(iso),
        )
        self.assertEqual(
            formatting.format_review_badge(3, 2),
            formatting_cards.format_review_badge(3, 2),
        )
        self.assertEqual(
            formatting.format_next_review_text(90000),
            formatting_cards.format_next_review_text(90000),
        )
        card = {
            "word": "abandon",
            "fa_meaning": "رها کردن",
            "fa_explanation": "",
            "synonyms": ["leave"],
            "antonyms": [],
            "examples": [],
            "example_translations": [],
            "grammar_tip": "",
        }
        self.assertEqual(formatting.format_card(card), formatting_cards.format_card(card))

    def test_leaf_import_law(self):
        """Jalali: T1 leaf + config + stdlib only. Cards: + catalog/validation
        + one-directional jalali import. Neither duplicates to_persian_digits;
        jalali never imports cards (no cycle).

        Only top-level imports are checked: the verbatim bodies keep the
        deliberate function-local deferrals (``services.send_pretty``,
        ``services.session.summary``) that avoid live import cycles.
        """
        def top_imports(tree):
            mods = set()
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module)
            return mods

        jalali_tree = ast.parse(
            Path(formatting_jalali.__file__).read_text(encoding="utf-8")
        )
        jalali_modules = top_imports(jalali_tree)
        self.assertFalse(
            {m for m in jalali_modules if m.startswith("services.utils.formatting_cards")},
            "jalali leaf must never import the cards leaf",
        )
        for mod in jalali_modules:
            top = mod.split(".")[0]
            self.assertIn(
                top, ("config", "services"),
                f"jalali leaf imports unexpected top-level {mod}",
            )
            if top == "services":
                self.assertEqual(
                    mod,
                    "services.utils.formatting_escape",
                    f"jalali leaf must import only the T1 leaf, found {mod}",
                )
        cards_tree = ast.parse(
            Path(formatting_cards.__file__).read_text(encoding="utf-8")
        )
        cards_modules = top_imports(cards_tree)
        allowed = {
            "config.catalog",
            "services.utils.formatting_escape",
            "services.utils.formatting_jalali",
            "services.utils.validation",
        }
        for mod in cards_modules:
            if mod.split(".")[0] in ("config", "services") and mod not in allowed:
                self.fail(f"cards leaf imports unexpected module {mod}")


if __name__ == "__main__":
    unittest.main()
