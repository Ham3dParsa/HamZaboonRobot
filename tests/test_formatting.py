import datetime
import random
import unittest

from services.send_pretty import Backend
from services.session.summary import WordReviewRecord, build_report
from services.utils.formatting import (
    escape_mdv2,
    escape_mdv2_code,
    format_grammar_tip,
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

    def _render_rich(self, records, **kw):
        return format_session_detail_page(records, 0, 1, **kw).render(Backend.RICH)

    def _lines(self, records, **kw):
        return [l for l in self._render(records, **kw).split("\n")]

    def test_new_card_row_in_table(self):
        # T4: 3-col table (واژه|وضعیت|مرور); PLAIN degrades cells with ' | '.
        # وضعیت is the S/D stage icon + display-only modifier (locked r7):
        # default rec S=3.0 → 👀 familiar, D=2.1 → (آسان).
        rendered = self._render([self._rec()], today=self.TODAY)
        self.assertIn("### 📋 واژه‌ها — صفحه ۱ از ۱", rendered)
        self.assertIn("well-being", rendered)
        self.assertIn("👀 (آسان)", rendered)
        # next_review +3 days -> «۳ روز دیگه»
        self.assertIn("📅 ۳ روز دیگه", rendered)

    def test_new_card_rich_table_markers(self):
        rendered = self._render_rich([self._rec()], today=self.TODAY)
        self.assertIn("### 📋 واژه‌ها", rendered)
        self.assertIn("| واژه | وضعیت | مرور |", rendered)
        self.assertIn("| --- | --- | --- |", rendered)

    def test_review_card_prior_in_review_cell(self):
        rendered = self._render(
            [self._rec(activity="srs_review", prior_review_date="2026-08-18")],
            today=self.TODAY,
        )
        # Same S/D as the default rec → 👀 familiar + (آسان) modifier.
        self.assertIn("👀 (آسان)", rendered)
        # مرور cell carries both 📅 next and ⏰ prior (2026-08-18 -> ۲۷ مرداد)
        self.assertIn("⏰ ۲۷ مرداد", rendered)
        self.assertIn("📅", rendered)

    def test_empty_page_renders_empty_group_row(self):
        rendered = self._render([], today=self.TODAY)
        self.assertIn("هنوز واژه‌ای نیست", rendered)

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

    def test_stage_modifier_labels(self):
        # Locked r7: display-only modifier — D<=2.5 → (آسان), D>=6 → (سخت).
        from services.utils.formatting import _stage_modifier
        self.assertEqual(_stage_modifier(2.5), "آسان")
        self.assertEqual(_stage_modifier(2.0), "آسان")
        self.assertEqual(_stage_modifier(6.0), "سخت")
        self.assertIsNone(_stage_modifier(4.0))
        self.assertIsNone(_stage_modifier(None))
        for d, label in [(2.0, "(آسان)"), (6.0, "(سخت)")]:
            rendered = self._render([self._rec(difficulty=d)], today=self.TODAY)
            self.assertIn(label, rendered)
        rendered = self._render([self._rec(difficulty=4.0)], today=self.TODAY)
        self.assertNotIn("(آسان)", rendered)
        self.assertNotIn("(سخت)", rendered)

    def test_no_raw_numbers_in_learner_view(self):
        rendered = self._render([self._rec()], today=self.TODAY)
        self.assertNotIn("پایداری ۳", rendered)
        self.assertNotIn("سختی ۲٫۱", rendered)

    def test_admin_same_as_user(self):
        # T4: is_admin stays for signature compat but renders identically
        # (diagnostic block retired; dedicated telemetry deferred).
        admin = self._render([self._rec()], is_admin=True, today=self.TODAY)
        user = self._render([self._rec()], is_admin=False, today=self.TODAY)
        self.assertEqual(admin, user)
        self.assertNotIn("فقط ادمین", admin)
        self.assertNotIn("Δ", admin)

    def test_learner_has_no_admin_extra(self):
        rendered = self._render([self._rec()], today=self.TODAY)
        self.assertNotIn("فقط ادمین", rendered)

    def test_single_escape_word_hyphen(self):
        # Regression (double-escape crash): hyphen escaped exactly once.
        rendered = self._render_rich([self._rec(word="well-being")], today=self.TODAY)
        self.assertIn("well\\-being", rendered)
        self.assertNotIn("well\\\\-being", rendered)

    def test_legend_content(self):
        # T4: (نماد|معنا) table, 8 showcase-gallery rows.
        rendered = format_summary_legend().render(Backend.PLAIN)
        self.assertIn("📖 گام‌های تثبیت در حافظه", rendered)
        self.assertIn("نماد | معنا", rendered)
        for token in ("🌱", "پیش‌آموزش", "👀", "آشنا", "📚", "آموخته شده",
                      "🧠", "پایداری", "(آسان)", "(سخت)", "📅", "بعدی",
                      "⏰", "قبلی"):
            self.assertIn(token, rendered)

    def test_legend_rich_table_markers(self):
        rendered = format_summary_legend().render(Backend.RICH)
        self.assertIn("### 📖 گام‌های تثبیت در حافظه", rendered)
        self.assertIn("| نماد | معنا |", rendered)
        self.assertIn("| --- | --- |", rendered)

    def test_legend_no_math(self):
        # r5: legend text without S/D numbers (no familiar-icon scope here).
        rendered = format_summary_legend().render(Backend.PLAIN)
        self.assertNotIn("🔍", rendered)
        for digit in "۰۱۲۳۴۵۶۷۸۹":
            self.assertNotIn(digit, rendered)
        self.assertNotIn("۶ و بیشتر", rendered)
        self.assertNotIn("کمتر از", rendered)

    def test_summary_ordering_and_stats(self):
        report = build_report(
            [self._rec(), self._rec(activity="srs_review", grade=4)]
        )
        rendered = format_session_summary(report, rng=random.Random(0)).render(Backend.PLAIN)
        self.assertIn("📊 گزارش نشست مطالعه", rendered)
        # tier block sits above the stats table (quote degrades to text)
        self.assertIn("⚡️ پیشرفت کلی این نشست:", rendered)
        # 2-col stats table rows
        self.assertIn("یادآوری", rendered)
        # rate = (1.0 + 1.0)/2 = 1.0 -> 100%; avg after = 3.0 -> ~۳ روز
        self.assertIn("🎯 ۱۰۰٪", rendered)
        self.assertIn("~۳ روز", rendered)
        self.assertIn("کارت", rendered)
        self.assertIn("۱ تازه · ۱ مرور", rendered)
        # 4-col 🌱👀📚🧠 counts mini-table
        for token in ("🌱", "👀", "📚", "🧠"):
            self.assertIn(token, rendered)

    def test_summary_rich_table_markers(self):
        report = build_report(
            [self._rec(), self._rec(activity="srs_review", grade=4)]
        )
        rendered = format_session_summary(report, rng=random.Random(0)).render(Backend.RICH)
        self.assertIn("### 📊 گزارش نشست مطالعه", rendered)
        self.assertIn("> ", rendered)  # motivational quote block
        self.assertIn("| --- | --- |", rendered)
        self.assertIn("| 🌱 | 👀 | 📚 | 🧠 |", rendered)

    def test_summary_hides_zero_counts(self):
        report = build_report([self._rec(activity="srs_review")])
        rendered = format_session_summary(report, rng=random.Random(0)).render(Backend.PLAIN)
        # T4: کارت row always renders; the zero side shows ۰.
        self.assertIn("۰ تازه · ۱ مرور", rendered)

    def test_summary_no_motivation_when_no_grades(self):
        report = build_report([self._rec(grade=None)])
        rendered = format_session_summary(report, rng=random.Random(0)).render(Backend.PLAIN)
        self.assertNotIn("پیشرفت کلی این نشست", rendered)
        self.assertNotIn("نرخ یادآوری", rendered)

    def test_summary_without_heat_renders_as_before(self):
        report = build_report(
            [self._rec(), self._rec(activity="srs_review", grade=4)]
        )
        rendered = format_session_summary(report, rng=random.Random(0)).render(Backend.PLAIN)
        self.assertNotIn("وضعیت امروز", rendered)

    def test_summary_heat_line_labels(self):
        from services.utils.formatting import _heat_label
        self.assertEqual(_heat_label(1, 5), ("🔥", "یک‌آتیشه"))
        self.assertEqual(_heat_label(2, 5), ("🔥🔥", "دوآتیشه"))
        self.assertEqual(_heat_label(5, 5), ("🔥🔥🔥", "سه‌آتیشه"))
        report = build_report([self._rec(activity="srs_review", grade=4)])
        rendered = format_session_summary(
            report, rng=random.Random(0), heat_used=2, heat_total=5
        ).render(Backend.PLAIN)
        # T4: heat lives in the امتیاز row of the stats table.
        self.assertIn("امتیاز", rendered)
        self.assertIn("🔥🔥 دوآتیشه", rendered)
        self.assertIn("۲ از ۵ نشست", rendered)

    def test_summary_admin_same_as_user(self):
        # T4: is_admin stays for signature compat but renders identically.
        report = build_report(
            [self._rec(), self._rec(activity="srs_review", grade=4)]
        )
        admin = format_session_summary(
            report, is_admin=True, rng=random.Random(0)).render(Backend.PLAIN)
        user = format_session_summary(
            report, is_admin=False, rng=random.Random(0)).render(Backend.PLAIN)
        self.assertEqual(admin, user)

    def test_review_badge_backward_compat_and_ordinal(self):
        from services.utils.formatting import format_review_badge
        self.assertEqual(
            format_review_badge(3), "⏰ آخرین مرور: ۳ روز پیش"
        )
        self.assertIn("اولین دیدار", format_review_badge(3, 0))
        self.assertIn("مرور ۳ام", format_review_badge(3, 3))
        self.assertEqual(format_review_badge(None, 0), "اولین دیدار")

    def test_stage_counts_use_sd_buckets(self):
        # Locked r7: buckets from S/D, never grade/activity.
        from services.utils.formatting import _stage_counts
        recs = [
            self._rec(activity="first_exposure", grade=4, stability_after=0.5,
                      difficulty=2.0),  # regression: high grade + low S → 🌱
            self._rec(activity="srs_review", grade=4, stability_after=25.0,
                      difficulty=2.0),  # regression: grade 4 + S=25 D=2 → 🧠
            self._rec(activity="srs_review", grade=1, stability_after=5.0,
                      difficulty=3.0),  # 👀 familiar
            self._rec(activity="srs_review", grade=2, stability_after=10.0,
                      difficulty=3.0),  # 📚 learned
            self._rec(activity="srs_review", grade=3, stability_after=None,
                      difficulty=None),  # missing S → 🌱
        ]
        self.assertEqual(_stage_counts(recs), (2, 1, 1, 1))
        report = build_report(recs)
        rendered = format_session_summary(report, rng=random.Random(0)).render(Backend.PLAIN)
        self.assertIn("۲", rendered)  # 🌱 learning count
        self.assertIn("۱", rendered)

    def test_stage_difficulty_gates(self):
        from services.utils.formatting import _stage_counts
        recs = [
            self._rec(activity="srs_review", stability_after=30.0,
                      difficulty=6.8),  # D>=6.5 forces 🌱
            self._rec(activity="srs_review", stability_after=30.0,
                      difficulty=6.2),  # 6.0<=D<6.5 caps stable → 👀
            self._rec(activity="srs_review", stability_after=30.0,
                      difficulty=5.0),  # stable needs D<4 → 📚
            self._rec(activity="srs_review", stability_after=30.0,
                      difficulty=2.0),  # D<4 keeps 🧠
        ]
        self.assertEqual(_stage_counts(recs), (1, 1, 1, 1))

    def test_detail_status_icon_follows_sd(self):
        # Per-word وضعیت uses the same S/D helper (single source).
        rendered = self._render(
            [self._rec(activity="first_exposure", grade=4, stability_after=0.5,
                       difficulty=2.0)],
            today=self.TODAY,
        )
        self.assertIn("🌱", rendered)
        self.assertNotIn("🧠", rendered)
        rendered = self._render(
            [self._rec(activity="srs_review", grade=4, stability_after=25.0,
                       difficulty=2.0)],
            today=self.TODAY,
        )
        self.assertIn("🧠 (آسان)", rendered)


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


class TestFormatGrammarTip(unittest.TestCase):
    """R6/F6 render choke: every dynamic field is escaped exactly once by the
    send_pretty renderer — a missed escape becomes structurally impossible."""

    def _tip(self, **over):
        data = {
            "title": "ماضی استمراری",
            "explanation": "داشتن + فعل ماضی",
            "example": "داشتم میرفتم.",
        }
        data.update(over)
        return format_grammar_tip(data, usage_text="📊 استفاده امروز: ۳/۱۰")

    def test_returns_message(self):
        from services.send_pretty import Message
        self.assertIsInstance(self._tip(), Message)

    def test_mdv2_escapes_each_dynamic_value(self):
        msg = format_grammar_tip(
            {"title": "a*b", "explanation": "x_y", "example": "c`d"},
            usage_text="u!v",
        )
        rendered = msg.render(Backend.MDV2)
        self.assertNotIn("a*b", rendered)
        self.assertIn("a\\*b", rendered)
        self.assertNotIn("x_y", rendered)
        self.assertIn("x\\_y", rendered)
        self.assertIn("`c\\`d`", rendered)
        self.assertNotIn("u!v", rendered)
        self.assertIn("u\\!v", rendered)

    def test_mdv2_structure_preserved(self):
        rendered = self._tip().render(Backend.MDV2)
        self.assertEqual(
            rendered,
            "✍️ *ماضی استمراری*\n\nداشتن \\+ فعل ماضی\n\n`داشتم میرفتم.`\n\n📊 استفاده امروز: ۳/۱۰",
        )

    def test_plain_backend_strips_markup(self):
        rendered = self._tip().render(Backend.PLAIN)
        self.assertEqual(
            rendered,
            "✍️ ماضی استمراری\n\nداشتن + فعل ماضی\n\nداشتم میرفتم.\n\n📊 استفاده امروز: ۳/۱۰",
        )

    def test_grammar_special_chars_never_break_markdown(self):
        rendered = format_grammar_tip(
            {"title": "ضربدر (×) و [پرانتز]", "explanation": "نقطه."},
            usage_text="قیمت ۱۰۰%!",
        ).render(Backend.MDV2)
        self.assertNotIn("(×)", rendered)
        self.assertIn(r"\(×\)", rendered)
        self.assertNotIn("۱۰۰%!", rendered)
        self.assertIn("۱۰۰%\\!", rendered)

    def test_null_fields_render_empty_not_literal_none(self):
        rendered = format_grammar_tip(
            {"title": None, "explanation": None, "example": None},
            usage_text="📊 استفاده امروز: ۳/۱۰",
        ).render(Backend.MDV2)
        self.assertNotIn("None", rendered)
        self.assertEqual(
            rendered,
            "✍️ **\n\n\n\n``\n\n📊 استفاده امروز: ۳/۱۰",
        )
