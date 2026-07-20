import unittest
from services.utils.formatting import escape_mdv2, escape_mdv2_code


PERSIAN_ENGLISH_MIXED = (
    "Hello *world* _test_ [link](url) with فارسی"
)

ALL_SPECIAL_CHARS = r"_*[]()~`>#+-=|{}.!"

EMPTY_STR = ""

ONLY_SPECIAL = "*_[]()~`>#+-=|{}."

PERSIAN_WITH_SPECIAL = (
    "سلام *دنیا* _آزمون_ [لینک](url) و ~تیلد~ و `کد`"
)

NUMBERS_MIXED = "قیمت ۱۲۳,۴۵۶ تومان، ۸۹% تخفیف! (فقط امروز)"


class TestMarkdownV2Escaping(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(escape_mdv2(""), "")

    def test_plain_persian_unchanged(self):
        text = "سلام دنیا"
        self.assertEqual(escape_mdv2(text), text)

    def test_all_special_chars_escaped(self):
        result = escape_mdv2(ALL_SPECIAL_CHARS)
        for ch in ALL_SPECIAL_CHARS:
            self.assertIn(f"\\{ch}", result)

    def test_persian_english_mixed(self):
        result = escape_mdv2(PERSIAN_ENGLISH_MIXED)
        self.assertNotIn("*world*", result)
        self.assertIn(r"\*world\*", result)
        self.assertNotIn("_test_", result)
        self.assertIn(r"\_test\_", result)

    def test_only_special_chars(self):
        result = escape_mdv2(ONLY_SPECIAL)
        for ch in ONLY_SPECIAL:
            self.assertIn(f"\\{ch}", result)

    def test_persian_with_special(self):
        result = escape_mdv2(PERSIAN_WITH_SPECIAL)
        self.assertNotIn("*دنیا*", result)
        self.assertIn(r"\*دنیا\*", result)
        self.assertNotIn("_آزمون_", result)
        self.assertIn(r"\_آزمون\_", result)

    def test_numbers_and_punctuation(self):
        result = escape_mdv2(NUMBERS_MIXED)
        self.assertNotIn("تخفیف!", result)
        self.assertIn(r"تخفیف\!", result)
        self.assertNotIn("(فقط امروز)", result)
        self.assertIn(r"\(فقط امروز\)", result)

    def test_escape_mdv2_code_backtick(self):
        result = escape_mdv2_code("text with `backtick` and \\backslash")
        self.assertIn(r"\`", result)
        self.assertIn(r"\\", result)

    def test_escape_mdv2_code_empty(self):
        self.assertEqual(escape_mdv2_code(""), "")

    def test_escape_mdv2_code_no_special(self):
        text = "plain text بدون کاراکتر خاص"
        self.assertEqual(escape_mdv2_code(text), text)
