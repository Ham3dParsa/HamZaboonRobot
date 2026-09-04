"""Unit tests for the preset save-preview helper (phase 01).

Covers ``services/utils/confirm_summary.py``: 2-field diff renders both
tables with old+new, dirty-count line uses Persian digits, notes appended,
and the empty-diffs path pins the "no change" line.
"""

import unittest

from services.send_pretty import Backend
from services.utils.confirm_summary import (
    EMPTY_CONFIRM_TEXT,
    FieldDiff,
    build_confirm_message,
)
from services.utils.formatting import to_persian_digits


class TestBuildConfirmMessage(unittest.TestCase):
    def test_two_field_diff_renders_both_tables_with_old_and_new(self):
        diffs = [
            FieldDiff(label="مدل", old="gpt-4o-mini", new="gpt-4o"),
            FieldDiff(label="دما", old="0.7", new="0.9"),
        ]
        msg = build_confirm_message("پیش‌نمایش ذخیره", "پیش‌فرض A", diffs)
        rich = msg.render(Backend.RICH)
        # Both tables present with old+new values as code cells.
        self.assertIn("مدل", rich)
        self.assertIn("دما", rich)
        self.assertIn("`gpt-4o-mini`", rich)
        self.assertIn("`gpt-4o`", rich)
        self.assertIn("`0.7`", rich)
        self.assertIn("`0.9`", rich)
        self.assertIn("قبلی", rich)
        self.assertIn("جدید", rich)
        # Pipe-table markup (header + alignment + body rows per table).
        self.assertIn("| وضعیت | مقدار |", rich)
        self.assertEqual(rich.count("| --- | --- |"), 2)
        # Input order preserved (caller's WIZARD_FIELDS order).
        self.assertLess(rich.index("مدل"), rich.index("دما"))

    def test_dirty_count_uses_persian_digits(self):
        diffs = [
            FieldDiff(label="مدل", old="a", new="b"),
            FieldDiff(label="دما", old="c", new="d"),
        ]
        rich = build_confirm_message("عنوان", "موضوع", diffs).render(Backend.RICH)
        self.assertIn(f"{to_persian_digits(2)} مورد تغییر کرده است", rich)

    def test_notes_appended_as_plain_lines(self):
        diffs = [FieldDiff(label="مدل", old="a", new="b")]
        notes = ("کلید جدید از دور بعد اعمال می‌شود",)
        rich = build_confirm_message("عنوان", "موضوع", diffs, notes=notes).render(
            Backend.RICH
        )
        self.assertIn("کلید جدید از دور بعد اعمال می‌شود", rich)

    def test_empty_diffs_pins_no_change_line(self):
        rich = build_confirm_message("عنوان", "موضوع", []).render(Backend.RICH)
        self.assertIn(EMPTY_CONFIRM_TEXT, rich)
        self.assertIn("تغییری برای ذخیره وجود ندارد", rich)
        # No tables rendered for the empty path.
        self.assertNotIn("|", rich)


if __name__ == "__main__":
    unittest.main()
