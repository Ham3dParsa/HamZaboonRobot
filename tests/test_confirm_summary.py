"""Unit tests for the preset save-preview helper (phase 01).

Covers ``services/utils/confirm_summary.py``: 2-field diff renders both
tables with old+new, dirty-count line uses Persian digits, notes appended,
and the empty-diffs path pins the "no change" line.
"""

import unittest

from services.send_pretty import Backend, Message
from services.utils.confirm_summary import (
    EMPTY_CONFIRM_TEXT,
    FieldDiff,
    build_confirm_message,
    render_diffs,
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


class TestRenderDiffs(unittest.TestCase):
    """T5 (D2+D4): one block shape, two callers — numbered on/off pinned."""

    def test_empty_diffs_returns_no_lines(self):
        self.assertEqual(render_diffs([]), [])
        self.assertEqual(render_diffs([], numbered=True), [])

    def test_single_diff_returns_two_lines_menu_shape(self):
        diffs = [FieldDiff(label="مدل", old="a", new="b")]
        lines = render_diffs(diffs)
        self.assertEqual(len(lines), 2)
        msg = Message()
        for line in lines:
            msg.add_line(*line)
        rich = msg.render(Backend.RICH)
        self.assertIn("مدل", rich)
        self.assertIn("`a`", rich)
        self.assertIn("`b`", rich)
        self.assertIn("| وضعیت | مقدار |", rich)
        # Unnumbered menu shape: no Persian-digit label prefix.
        self.assertNotIn(f"{to_persian_digits(1)}\\.", rich)

    def test_n_diffs_preserve_order(self):
        diffs = [
            FieldDiff(label="مدل", old="a", new="b"),
            FieldDiff(label="دما", old="c", new="d"),
            FieldDiff(label="سقف", old="e", new="f"),
        ]
        lines = render_diffs(diffs)
        self.assertEqual(len(lines), 2 * len(diffs))
        msg = Message()
        for line in lines:
            msg.add_line(*line)
        rich = msg.render(Backend.RICH)
        self.assertLess(rich.index("مدل"), rich.index("دما"))
        self.assertLess(rich.index("دما"), rich.index("سقف"))
        self.assertEqual(rich.count("| --- | --- |"), 3)

    def test_numbered_prefixes_persian_digits(self):
        diffs = [
            FieldDiff(label="مدل", old="a", new="b"),
            FieldDiff(label="دما", old="c", new="d"),
        ]
        lines = render_diffs(diffs, numbered=True)
        self.assertEqual(len(lines), 4)
        msg = Message()
        for line in lines:
            msg.add_line(*line)
        rich = msg.render(Backend.RICH)
        # "." is Rich-escaped in the rendered output.
        self.assertIn(f"{to_persian_digits(1)}\\.", rich)
        self.assertIn(f"{to_persian_digits(2)}\\.", rich)
        self.assertIn("`a`", rich)
        self.assertIn("`d`", rich)

    def test_numbered_confirm_matches_manual_numbering_byte_identical(self):
        """numbered=True reproduces the old caller-side label rewrite exactly."""
        diffs = [
            FieldDiff(label="مدل", old="gpt-4o-mini", new="gpt-4o"),
            FieldDiff(label="دما", old="0.7", new="0.9"),
        ]
        via_flag = build_confirm_message("⚠️ تأیید ذخیره —", "«P»", diffs, numbered=True).render(Backend.RICH)
        manual = [
            FieldDiff(label=f"{to_persian_digits(i + 1)}. {d.label}", old=d.old, new=d.new)
            for i, d in enumerate(diffs)
        ]
        via_manual = build_confirm_message("⚠️ تأیید ذخیره —", "«P»", manual).render(Backend.RICH)
        self.assertEqual(via_flag, via_manual)

    def test_build_confirm_default_stays_unnumbered(self):
        diffs = [FieldDiff(label="مدل", old="a", new="b")]
        rich = build_confirm_message("عنوان", "موضوع", diffs).render(Backend.RICH)
        self.assertIn("مدل", rich)
        # No numbered-label prefix (dirty-count line still uses Persian digits).
        self.assertNotIn(f"{to_persian_digits(1)}\\.", rich)


if __name__ == "__main__":
    unittest.main()
