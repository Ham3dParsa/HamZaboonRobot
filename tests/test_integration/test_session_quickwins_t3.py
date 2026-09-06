"""T3 quick-wins integration: live-card review ordinal (B).

Covers the handler badge path end-to-end on a temp DB:
prior COUNT(*) == 0 → «اولین دیدار»; 2 priors → «مرور ۳ام»
(N = prior + 1, the upcoming grading counts as next).
"""

from __future__ import annotations

import datetime
import os
import tempfile
import unittest

from services import db
from services.db import schema as db_schema
from services.send_pretty import Backend
from services.session import SessionNode
from services.session.summary import WordReviewRecord, build_report
from services.utils.formatting import (
    format_session_detail_page,
    format_session_summary,
    format_summary_legend,
)
from handlers.study_handler import (
    SessionState,
    _build_card_text_and_keyboard,
    _review_badge_for_card,
)


def _add_word(uid: int, word: str) -> int:
    db.add_saved_word(uid, word, "en", {"word": word, "fa_meaning": "م"})
    past = (db_schema._utc_now() - datetime.timedelta(days=2)).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE saved_words SET first_exposure_done=1, last_review_at=? "
            "WHERE id=(SELECT id FROM saved_words WHERE user_id=? AND word=?)",
            (past, uid, word),
        )
    with db.get_conn() as conn:
        return conn.execute(
            "SELECT id FROM saved_words WHERE user_id=? AND word=?",
            (uid, word),
        ).fetchone()["id"]


def _add_event(uid: int, word_id: int) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO review_events "
            "(word_id, user_id, grade, activity_type, outcome, created_at) "
            "VALUES (?, ?, 3, 'srs_review', 'recalled', ?)",
            (word_id, uid, db_schema._utc_now().isoformat()),
        )


class ReviewCountBadgeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new
        db_schema.DB_PATH = new
        db.init_db()
        db.create_user_if_needed(1, "learner")

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def test_first_view_shows_first_meeting(self):
        wid = _add_word(1, "newword")
        row = db.get_saved_word(wid, 1)
        self.assertEqual(db.count_review_events_for_card(1, wid), 0)
        badge = _review_badge_for_card(1, wid, row)
        self.assertIn("اولین دیدار", badge)

    def test_two_priors_render_third_review_ordinal(self):
        wid = _add_word(1, "oldword")
        _add_event(1, wid)
        _add_event(1, wid)
        self.assertEqual(db.count_review_events_for_card(1, wid), 2)
        row = db.get_saved_word(wid, 1)
        badge = _review_badge_for_card(1, wid, row)
        self.assertIn("مرور ۳ام", badge)
        node = SessionNode(
            activity_type="srs_review",
            source_tier=1,
            card_data={"word": "oldword"},
            source_id=wid,
        )
        state = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=None, plan="free",
        )
        text, _kb = _build_card_text_and_keyboard(node, state, 1, {})
        self.assertIn("مرور ۳ام", text)


class RichReportSmokeTests(unittest.TestCase):
    """T4: end-of-session report renders Rich tables (Backend.RICH)."""

    def _rec(self):
        return WordReviewRecord(
            word_id=1, word="alpha", activity_type="srs_review",
            stability_before=1.0, stability_after=3.0, grade=3,
            next_review_date="2026-08-25", difficulty=2.0,
        )

    def test_summary_rich_tables(self):
        import random

        report = build_report([self._rec()])
        rendered = format_session_summary(
            report, rng=random.Random(0), heat_used=2, heat_total=5,
        ).render(Backend.RICH)
        self.assertIn("### 📊 گزارش نشست مطالعه", rendered)
        self.assertIn("| یادآوری |", rendered)
        self.assertIn("| 🌱 | 👀 | 📚 | 🧠 |", rendered)
        self.assertIn("دوآتیشه", rendered)

    def test_detail_rich_table(self):
        rendered = format_session_detail_page(
            [self._rec()], 0, 1).render(Backend.RICH)
        self.assertIn("| واژه | وضعیت | مرور |", rendered)
        self.assertIn("alpha", rendered)
        self.assertIn("📅", rendered)

    def test_legend_rich_table(self):
        rendered = format_summary_legend().render(Backend.RICH)
        self.assertIn("| نماد | معنا |", rendered)
        self.assertIn("پیش‌آموزش", rendered)


class StageCountsSDTests(unittest.TestCase):
    """Locked r7: 🌱👀📚🧠 buckets from S/D, never grade/activity."""

    def _rec(self, s, d, activity="srs_review", grade=3):
        return WordReviewRecord(
            word_id=1, word="w", activity_type=activity,
            stability_before=1.0, stability_after=s, grade=grade,
            next_review_date="2026-08-25", difficulty=d,
        )

    def test_first_exposure_high_grade_low_stability_is_learning(self):
        from services.utils.formatting import _stage_counts
        self.assertEqual(
            _stage_counts([self._rec(0.5, 2.0, "first_exposure", 4)]),
            (1, 0, 0, 0),
        )

    def test_high_stability_low_difficulty_is_stable(self):
        from services.utils.formatting import _stage_counts
        self.assertEqual(
            _stage_counts([self._rec(25.0, 2.0, "srs_review", 4)]),
            (0, 0, 0, 1),
        )

    def test_sd_thresholds_and_difficulty_gates(self):
        from services.utils.formatting import _stage_counts
        recs = [
            self._rec(1.0, 3.0),    # S<2.5 → 🌱
            self._rec(5.0, 3.0),    # S<7 → 👀
            self._rec(10.0, 3.0),   # S<21 → 📚
            self._rec(25.0, 2.0),   # S>=21 + D<4 → 🧠
            self._rec(25.0, 5.0),   # stable needs D<4 → 📚
            self._rec(30.0, 6.2),   # 6.0<=D<6.5 caps → 👀
            self._rec(30.0, 6.8),   # D>=6.5 forces 🌱
            self._rec(None, None),  # missing S → 🌱
        ]
        self.assertEqual(_stage_counts(recs), (3, 2, 2, 1))

    def test_summary_counts_match_stage_helper(self):
        import random

        report = build_report([self._rec(0.5, 2.0, "first_exposure", 4),
                               self._rec(25.0, 2.0, "srs_review", 4)])
        rendered = format_session_summary(
            report, rng=random.Random(0),
        ).render(Backend.PLAIN)
        self.assertIn("🌱", rendered)
        self.assertIn("🧠", rendered)
