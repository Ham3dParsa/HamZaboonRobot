import datetime
import random
import unittest

from services.send_pretty import Backend
from services.session.summary import WordReviewRecord, build_report
from services.utils.formatting import (
    escape_mdv2,
    escape_mdv2_code,
    format_next_review_text,
    format_session_detail_page,
    format_session_summary,
    format_summary_legend,
    html_escape,
    phonetic_lines,
)


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


class TestHtmlEscape(unittest.TestCase):
    """html_escape must escape the standard HTML reserved characters."""

    def test_ampersand(self):
        self.assertEqual(html_escape("a&b"), "a&amp;b")

    def test_less_than(self):
        self.assertEqual(html_escape("a<b"), "a&lt;b")

    def test_greater_than(self):
        self.assertEqual(html_escape("a>b"), "a&gt;b")

    def test_double_quote(self):
        self.assertEqual(html_escape('a"b'), "a&quot;b")

    def test_single_quote(self):
        self.assertEqual(html_escape("a'b"), "a&#x27;b")

    def test_multiple_special(self):
        self.assertEqual(html_escape("<a href='x'>"), "&lt;a href=&#x27;x&#x27;&gt;")

    def test_persian_text_unchanged(self):
        text = "سلام دنیا"
        self.assertEqual(html_escape(text), text)

    def test_url_with_query_string(self):
        url = "https://api.example.com/v1?key=123&fmt=json"
        self.assertEqual(html_escape(url), "https://api.example.com/v1?key=123&amp;fmt=json")

    def test_none_is_empty(self):
        self.assertEqual(html_escape(None), "")

    def test_falsy_non_strings_are_stringified(self):
        self.assertEqual(html_escape(0), "0")
        self.assertEqual(html_escape(False), "False")


class TestNextReviewText(unittest.TestCase):
    """format_next_review_text renders the locked Persian relative-time copy."""

    def test_sub_day_hours(self):
        # 5h interval -> "حدود ۵ ساعت دیگر"
        self.assertEqual(
            format_next_review_text(5 * 3600),
            "ثبت شد؛ مرور بعدی: حدود ۵ ساعت دیگر.",
        )

    def test_one_day_rounded_is_farda(self):
        # 24h exactly -> "فردا"
        self.assertEqual(
            format_next_review_text(24 * 3600),
            "ثبت شد؛ مرور بعدی: فردا.",
        )

    def test_multi_day_rounds_days(self):
        # 3 days -> "۳ روز دیگر"
        self.assertEqual(
            format_next_review_text(3 * 24 * 3600),
            "ثبت شد؛ مرور بعدی: ۳ روز دیگر.",
        )

    def test_sub_hour_floor_at_one_hour(self):
        # 30 minutes -> floor to "حدود ۱ ساعت دیگر" (never 0)
        self.assertEqual(
            format_next_review_text(1800),
            "ثبت شد؛ مرور بعدی: حدود ۱ ساعت دیگر.",
        )

    def test_none_falls_back_to_generic_copy(self):
        self.assertEqual(
            format_next_review_text(None),
            "ثبت شد؛ مرور بعدی زمان‌بندی شد.",
        )

    def test_zero_interval_generic_copy(self):
        self.assertEqual(
            format_next_review_text(0),
            "ثبت شد؛ مرور بعدی زمان‌بندی شد.",
        )

    def test_just_below_24h_uses_hours_form(self):
        # 23.7h is still a sub-24h interval -> hours form (boundary fix).
        self.assertEqual(
            format_next_review_text(int(23.7 * 3600)),
            "ثبت شد؛ مرور بعدی: حدود ۲۴ ساعت دیگر.",
        )

    def test_exactly_24h_is_farda(self):
        self.assertEqual(
            format_next_review_text(24 * 3600),
            "ثبت شد؛ مرور بعدی: فردا.",
        )


class TestSessionSummaryRendering(unittest.TestCase):
    TODAY = datetime.date(2026, 8, 22)  # Jalali 1405/5/31 (31 مرداد)

    def _rec(
        self,
        word="well-being",
        activity="first_exposure",
        difficulty=2.1,
        grade=3,
        stability_after=3.0,
        stability_before=1.0,
        interval_days=3.0,
        next_review_date="2026-08-25",
        prior_review_date=None,
    ):
        return WordReviewRecord(
            word_id=1,
            word=word,
            activity_type=activity,
            stability_before=stability_before,
            stability_after=stability_after,
            prior_review_date=prior_review_date,
            grade=grade,
            interval_days=interval_days,
            next_review_date=next_review_date,
            difficulty=difficulty,
        )

    def _render(self, records, **kw):
        return format_session_detail_page(records, 0, 1, **kw).render(Backend.PLAIN)

    def _render_md(self, records, **kw):
        return format_session_detail_page(records, 0, 1, **kw).render(Backend.MDV2)

    def _lines(self, records, **kw):
        return [l for l in self._render(records, **kw).split("\n")]

    def test_new_card_two_lines(self):
        lines = self._lines([self._rec()], today=self.TODAY)
        self.assertIn("📋 واژه‌ها — صفحه ۱ از ۱", lines)
        self.assertIn("well-being  ✨ جدید", lines)
        # next_review +3 days -> «۳ روز دیگه»
        self.assertIn("🟢 راحت · 📅 ۳ روز دیگه · امتیاز ۳", lines)

    def test_review_card_gets_third_line(self):
        lines = self._lines(
            [self._rec(activity="srs_review", prior_review_date="2026-08-18")],
            today=self.TODAY,
        )
        self.assertIn("well-being  🔁 مرور", lines)
        # prior 2026-08-18 -> ۲۷ مرداد
        self.assertIn("آخرین مرور: ۲۷ مرداد · امتیاز ۳", lines)

    def test_relative_date_table(self):
        cases = {
            "2026-08-22": "امروز",
            "2026-08-23": "فردا",
            "2026-08-24": "پس‌فردا",
            "2026-08-25": "۳ روز دیگه",
            "2026-08-28": "۶ روز دیگه",
            "2026-08-29": "۷ شهریور",
        }
        for iso, expected in cases.items():
            rendered = self._render([self._rec(next_review_date=iso)], today=self.TODAY)
            self.assertIn("📅 " + expected, rendered)

    def test_difficulty_labels(self):
        for d, label in [
            (6.0, "🔴 سخت"),
            (5.9, "🟡 متوسط"),
            (3.0, "🟡 متوسط"),
            (2.9, "🟢 راحت"),
        ]:
            rendered = self._render([self._rec(difficulty=d)], today=self.TODAY)
            self.assertIn(label, rendered)

    def test_no_raw_numbers_in_learner_view(self):
        rendered = self._render([self._rec()], today=self.TODAY)
        self.assertNotIn("پایداری ۳", rendered)
        self.assertNotIn("سختی ۲٫۱", rendered)

    def test_admin_extra_grouped_and_marked(self):
        rendered = self._render([self._rec()], is_admin=True, today=self.TODAY)
        self.assertIn("(فقط ادمین:", rendered)
        self.assertIn("سختی", rendered)
        self.assertIn("فاصله", rendered)
        self.assertIn("Δ", rendered)

    def test_learner_has_no_admin_extra(self):
        rendered = self._render([self._rec()], today=self.TODAY)
        self.assertNotIn("فقط ادمین", rendered)

    def test_single_escape_word_hyphen(self):
        # Regression (double-escape crash): hyphen escaped exactly once.
        rendered = self._render_md([self._rec(word="well-being")], today=self.TODAY)
        self.assertIn("well\\-being", rendered)
        self.assertNotIn("well\\\\-being", rendered)

    def test_legend_content(self):
        rendered = format_summary_legend().render(Backend.PLAIN)
        self.assertIn("📖 راهنمای نمادها", rendered)
        self.assertIn("✨ جدید  ·  🔁 مرور", rendered)
        self.assertIn("🔴 بالا", rendered)
        self.assertIn("📅 مرور بعدی", rendered)
        # stability-color rows retired with the raw-number removal (R2/R8)
        self.assertNotIn("🔵", rendered)

    def test_summary_ordering_and_stats(self):
        report = build_report(
            [self._rec(), self._rec(activity="srs_review", grade=4)]
        )
        rendered = format_session_summary(report, rng=random.Random(0)).render(Backend.PLAIN)
        self.assertIn("📊 گزارش نشست مطالعه", rendered)
        # tier block sits above the counts
        self.assertIn("⚡️ پیشرفت کلی این نشست:", rendered)
        self.assertIn("✨ ۱ واژه تازه یاد گرفتی", rendered)
        self.assertIn("🔁 ۱ واژه مرور کردی", rendered)
        # rate = (1.0 + 1.0)/2 = 1.0 -> 100%; avg after = 3.0 -> ~۳ روز
        self.assertIn("🎯 نرخ یادآوری: ۱۰۰٪", rendered)
        self.assertIn("میانگین پایداری: ~۳ روز", rendered)

    def test_summary_hides_zero_counts(self):
        report = build_report([self._rec(activity="srs_review")])
        rendered = format_session_summary(report, rng=random.Random(0)).render(Backend.PLAIN)
        self.assertNotIn("واژه تازه یاد گرفتی", rendered)
        self.assertIn("🔁 ۱ واژه مرور کردی", rendered)

    def test_summary_no_motivation_when_no_grades(self):
        report = build_report([self._rec(grade=None)])
        rendered = format_session_summary(report, rng=random.Random(0)).render(Backend.PLAIN)
        self.assertNotIn("پیشرفت کلی این نشست", rendered)
        self.assertNotIn("نرخ یادآوری", rendered)


class TestPhoneticLines(unittest.TestCase):
    """BUG-4 catching test: the phonetic-line helper is a public member of
    services/utils/formatting.py (no private-underscore import anywhere)."""

    def test_is_public_importable(self):
        self.assertTrue(callable(phonetic_lines))

    def test_dict_ipa_renders_code_line(self):
        self.assertEqual(phonetic_lines({"ipa": "hɛ.loʊ"}), ["`hɛ.loʊ`"])

    def test_json_string_ipa_renders_code_line(self):
        self.assertEqual(phonetic_lines('{"ipa": "hɛ.loʊ"}'), ["`hɛ.loʊ`"])

    def test_plain_string_falls_back_to_raw_code_line(self):
        self.assertEqual(phonetic_lines("hɛ.loʊ"), ["`hɛ.loʊ`"])

    def test_backtick_ipa_is_escaped(self):
        self.assertEqual(phonetic_lines({"ipa": "a`b"}), ["`a\\`b`"])

    def test_empty_value_returns_no_lines(self):
        self.assertEqual(phonetic_lines(""), [])
        self.assertEqual(phonetic_lines(None), [])
        self.assertEqual(phonetic_lines({}), [])
