"""Integration tests for the post-study-session summary report (R1-R7).

Self-contained temp-DB harness mirroring
tests/test_integration/test_study_session_grade_restart.py.

Covers the locked contract:
- R4: bronze+ (session_summary feature) gets the compact report + detail
  button; free keeps the minimal completion message.
- R6: the owner (is_owner) sees the admin variant (before->after stability,
  interval, next date, difficulty, grade).
- R1: the detail button renders a paged word list; back returns to summary.
- R7: the report is ephemeral in user_data; a stale button (data gone) fails
  gracefully with an expired notice instead of crashing.
- _gather_word_records assembles correct per-word records (activity type,
  grade, prior review date, before/after stability) from saved_words +
  review_events.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest

from services import db, send_pretty
from services.db import schema as db_schema
from handlers import study_handler
from handlers.study_handler import (
    SessionState,
    _gather_word_records,
    _handle_session_summary_callback,
    _to_app_tz_date,
    advance_session,
)
from services.session import SessionNode
from services.session.summary import WordReviewRecord, build_report
from services.utils.callback_notifications import CallbackNoticeIntent
from services.utils.formatting import format_session_detail_page
from services.send_pretty import Backend


class SessionSummaryFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new
        db_schema.DB_PATH = new
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _add_word(self, word, stability=1.0, difficulty=5.0,
                  last_review_at=None, next_review_at=None):
        card = {
            "word": word, "fa_meaning": "م", "fa_explanation": "ت",
            "examples": [], "example_translations": [], "synonyms": [],
            "antonyms": [], "grammar_tip": "",
        }
        db.add_saved_word(1, word, "en", card)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE saved_words SET stability=?, difficulty=?, "
                "last_review_at=?, next_review_at=? WHERE user_id=1 AND word=?",
                (stability, difficulty, last_review_at, next_review_at, word),
            )
            return conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()["id"]

    def _add_review_event(self, word_id, created_at, activity_type,
                          grade, outcome="correct"):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO review_events "
                "(word_id, user_id, revealed_before_answer, outcome, created_at,"
                " grade, activity_type) VALUES (?, ?, 0, ?, ?, ?, ?)",
                (word_id, 1, outcome, created_at, grade, activity_type),
            )

    def _update(self, user_id=1):
        u = MagicMock()
        u.effective_user.id = user_id
        u.effective_chat = MagicMock()
        u.effective_chat.id = user_id
        return u

    def _ctx(self):
        c = MagicMock()
        c.user_data = {}
        c.bot = MagicMock()
        c.bot.edit_message_text = AsyncMock()
        c.bot.send_message = AsyncMock()
        return c

    # ------------------------------------------------------------------
    # _gather_word_records
    # ------------------------------------------------------------------

    def test_gather_word_records_populates_fields(self):
        w = self._add_word(
            "alpha", stability=4.0, difficulty=3.2,
            last_review_at="2026-08-10T10:00:00Z",
            next_review_at="2026-08-20T10:00:00Z",
        )
        self._add_review_event(w, "2026-08-10T10:00:00Z", "srs_review", 3)
        self._add_review_event(w, "2026-08-19T10:00:00Z", "srs_review", 4)
        state = SessionState(
            nodes=[], total_cards=1, tier3_context={}, study_msg_id=None,
            plan="silver", graded_word_ids=[w],
            before_stability={w: 2.0},
        )
        records = _gather_word_records(state, 1)
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r.word_id, w)
        self.assertEqual(r.word, "alpha")
        self.assertEqual(r.activity_type, "srs_review")
        self.assertEqual(r.stability_before, 2.0)   # from snapshot
        self.assertEqual(r.stability_after, 4.0)    # from saved_words
        self.assertEqual(r.grade, 4)                # newest event
        self.assertEqual(r.prior_review_date, "2026-08-10")  # second-newest
        self.assertEqual(r.interval_days, 10.0)
        self.assertEqual(r.next_review_date, "2026-08-20")
        self.assertEqual(r.difficulty, 3.2)

    def test_gather_word_records_missing_events_fallback(self):
        # No review_events at all -> activity_type falls back to srs_review,
        # grade/prior_date/interval stay None without crashing.
        w = self._add_word("beta", stability=1.5)
        state = SessionState(
            nodes=[], total_cards=1, tier3_context={}, study_msg_id=None,
            plan="silver", graded_word_ids=[w], before_stability={},
        )
        records = _gather_word_records(state, 1)
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r.activity_type, "srs_review")
        self.assertIsNone(r.grade)
        self.assertIsNone(r.prior_review_date)
        self.assertEqual(r.stability_after, 1.5)

    def test_gather_word_records_empty_session(self):
        state = SessionState(
            nodes=[], total_cards=0, tier3_context={}, study_msg_id=None,
            plan="silver", graded_word_ids=[], before_stability={},
        )
        self.assertEqual(_gather_word_records(state, 1), [])

    def test_to_app_tz_date_uses_app_timezone(self):
        # A UTC timestamp near local midnight must map to the app-tz day, not the
        # raw UTC day (Kilo date-boundary finding). 22:30Z in Asia/Tehran (UTC+3:30)
        # is 02:00 the next local day.
        self.assertEqual(_to_app_tz_date("2026-08-19T22:30:00Z"), "2026-08-20")
        self.assertEqual(_to_app_tz_date("2026-08-20T10:00:00Z"), "2026-08-20")
        self.assertIsNone(_to_app_tz_date(None))
        self.assertIsNone(_to_app_tz_date("not-a-date"))

    # ------------------------------------------------------------------
    # Completion render (R4 / R6)
    # ------------------------------------------------------------------

    def _completing_state(self, word_ids, plan, before_stability=None):
        return SessionState(
            nodes=[], total_cards=len(word_ids), tier3_context={},
            study_msg_id=99, plan=plan, graded_word_ids=list(word_ids),
            before_stability=before_stability or {},
        )

    def test_completion_renders_summary_for_bronze_plus(self):
        w = self._add_word("alpha", stability=3.0)
        self._add_review_event(w, "2026-08-19T10:00:00Z", "first_exposure", 3)
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._completing_state(
            [w], "silver", before_stability={w: 0.0},
        )
        asyncio.run(advance_session(self._update(), ctx))
        text = ctx.bot.edit_message_text.call_args.kwargs["text"]
        self.assertIn("گزارش نشست مطالعه", text)
        self.assertIn("واژه تازه یاد گرفتی", text)
        # Detail button present on the summary.
        self.assertIsNotNone(ctx.bot.edit_message_text.call_args.kwargs.get("reply_markup"))
        # Ephemeral report stashed for the detail callbacks (R7).
        self.assertIn("session_summary", ctx.user_data)

    def test_completion_renders_minimal_for_free(self):
        w = self._add_word("alpha", stability=3.0)
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._completing_state([w], "free")
        asyncio.run(advance_session(self._update(), ctx))
        text = ctx.bot.edit_message_text.call_args.kwargs["text"]
        self.assertIn("جلسه مطالعه تموم شد", text)
        self.assertNotIn("گزارش نشست مطالعه", text)
        self.assertNotIn("session_summary", ctx.user_data)
        self.assertIsNone(ctx.bot.edit_message_text.call_args.kwargs.get("reply_markup"))

    def test_completion_admin_variant_for_owner(self):
        w = self._add_word("alpha", stability=3.0)
        self._add_review_event(w, "2026-08-19T10:00:00Z", "srs_review", 4)
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._completing_state(
            [w], "silver", before_stability={w: 1.0},
        )
        with patch.object(study_handler, "is_owner", return_value=True):
            asyncio.run(advance_session(self._update(), ctx))
        text = ctx.bot.edit_message_text.call_args.kwargs["text"]
        self.assertIn("میانگین تغییر پایداری", text)  # admin-only line

    def test_completion_owner_on_free_plan_still_gets_admin_report(self):
        # Owner always gets the report (admin variant) regardless of plan.
        w = self._add_word("alpha", stability=3.0)
        self._add_review_event(w, "2026-08-19T10:00:00Z", "srs_review", 4)
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._completing_state(
            [w], "free", before_stability={w: 1.0},
        )
        with patch.object(study_handler, "is_owner", return_value=True):
            asyncio.run(advance_session(self._update(), ctx))
        text = ctx.bot.edit_message_text.call_args.kwargs["text"]
        self.assertIn("گزارش نشست مطالعه", text)
        self.assertIn("میانگین تغییر پایداری", text)
        self.assertIn("session_summary", ctx.user_data)

    def test_completion_empty_report_no_detail_button(self):
        # A zero-total report renders the summary but NO detail button, so the
        # empty "صفحه ۱ از ۰" page can never be reached.
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._completing_state([], "silver")
        asyncio.run(advance_session(self._update(), ctx))
        text = ctx.bot.edit_message_text.call_args.kwargs["text"]
        self.assertIn("گزارش نشست مطالعه", text)
        self.assertIsNone(ctx.bot.edit_message_text.call_args.kwargs.get("reply_markup"))
        self.assertIn("session_summary", ctx.user_data)

    def test_completion_summary_failure_falls_back_to_minimal(self):
        w = self._add_word("alpha", stability=3.0)
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._completing_state([w], "silver")
        with patch.object(study_handler, "_gather_word_records", side_effect=RuntimeError):
            asyncio.run(advance_session(self._update(), ctx))
        text = ctx.bot.edit_message_text.call_args.kwargs["text"]
        self.assertIn("جلسه مطالعه تموم شد", text)

    # ------------------------------------------------------------------
    # Detail pagination callback (R1 / R7)
    # ------------------------------------------------------------------

    def _stash(self, word_ids, is_admin=False, before=None):
        words = [self._add_word(f"word{i}", stability=2.0) for i in word_ids]
        report = build_report([
            _gather_word_records(
                SessionState(
                    nodes=[], total_cards=1, tier3_context={}, study_msg_id=None,
                    plan="silver", graded_word_ids=[w],
                    before_stability={w: before or 1.0},
                ),
                1,
            )[0]
            for w in words
        ])
        return report

    def test_detail_callback_renders_paged_list_and_back(self):
        report = self._stash([0, 1, 2, 3, 4, 5, 6, 7, 8])  # 9 words -> 2 pages
        ctx = self._ctx()
        nonce = "n1"
        ctx.user_data["session_summary"] = {
            "report": report, "is_admin": False, "nonce": nonce,
        }

        q = MagicMock()
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        q.message.message_id = 5
        u = self._update()
        u.callback_query = q
        with patch.object(study_handler, "notify_callback", new_callable=AsyncMock):
            # page 1 (index 0)
            asyncio.run(_handle_session_summary_callback(u, ctx, f"detail:{nonce}"))
            text = q.edit_message_text.call_args.args[0]
            self.assertIn("واژه‌ها — صفحه ۱ از ۲", text)
            self.assertIn("word0", text)
            # page 2 (index 1)
            asyncio.run(_handle_session_summary_callback(u, ctx, f"page:1:{nonce}"))
            text = q.edit_message_text.call_args.args[0]
            self.assertIn("واژه‌ها — صفحه ۲ از ۲", text)
            self.assertIn("word8", text)
            self.assertNotIn("word0", text)
            # back to summary (payload NOT popped; detail stays live)
            asyncio.run(_handle_session_summary_callback(u, ctx, f"back:{nonce}"))
            text = q.edit_message_text.call_args.args[0]
            self.assertIn("گزارش نشست مطالعه", text)
            # after back the payload remains, so detail still works
            asyncio.run(_handle_session_summary_callback(u, ctx, f"detail:{nonce}"))
            text = q.edit_message_text.call_args.args[0]
            self.assertIn("واژه‌ها — صفحه ۱ از ۲", text)

    def test_detail_callback_admin_variant(self):
        report = self._stash([0])
        ctx = self._ctx()
        nonce = "n2"
        ctx.user_data["session_summary"] = {
            "report": report, "is_admin": True, "nonce": nonce,
        }
        q = MagicMock()
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        q.message.message_id = 5
        u = self._update()
        u.callback_query = q
        with patch.object(study_handler, "notify_callback", new_callable=AsyncMock):
            asyncio.run(_handle_session_summary_callback(u, ctx, f"detail:{nonce}"))
        text = q.edit_message_text.call_args.args[0]
        # Admin-only diagnostics grouped and marked — raw numbers appear only here
        self.assertIn("سختی", text)
        self.assertIn("Δ", text)  # before->after stability delta (admin-only)
        self.assertIn("(فقط ادمین:", text)

    def test_stale_nonce_rejected_gracefully(self):
        # A button from an OLDER report (mismatched nonce) is rejected with an
        # expired notice, never renders the current report.
        report = self._stash([0])
        ctx = self._ctx()
        ctx.user_data["session_summary"] = {
            "report": report, "is_admin": False, "nonce": "current",
        }
        q = MagicMock()
        q.answer = AsyncMock()
        q.message.message_id = 5
        u = self._update()
        u.callback_query = q
        with patch.object(study_handler, "notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(_handle_session_summary_callback(u, ctx, "detail:OLD_NONCE"))
        notify.assert_called_once()
        self.assertEqual(
            notify.call_args.kwargs["intent"], CallbackNoticeIntent.IMPORTANT_ERROR
        )
        self.assertIn("منقضی", notify.call_args.args[1])
        ctx.bot.edit_message_text.assert_not_awaited()

    def test_stale_callback_graceful(self):
        # No report in user_data (e.g. after restart) -> expired notice, no crash.
        ctx = self._ctx()
        q = MagicMock()
        q.answer = AsyncMock()
        q.message.message_id = 5
        u = self._update()
        u.callback_query = q
        with patch.object(study_handler, "notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(_handle_session_summary_callback(u, ctx, "detail:xyz"))
        notify.assert_called_once()
        self.assertEqual(
            notify.call_args.kwargs["intent"], CallbackNoticeIntent.IMPORTANT_ERROR
        )
        self.assertIn("منقضی", notify.call_args.args[1])
        ctx.bot.edit_message_text.assert_not_awaited()


    def test_detail_page_renders_with_single_escape(self):
        # Regression (double-escape crash): the word hyphen is escaped exactly
        # once. Dates no longer render as raw ISO in the learner view (Jalali
        # relative dates), so the double-backslash signature can only surface on
        # the word itself; the admin Δ uses Persian digits too. Assert single
        # escaping and no double-backslash anywhere.
        rec = WordReviewRecord(
            word_id=1, word="well-being", activity_type="first_exposure",
            stability_before=5.0, stability_after=3.8,
            prior_review_date="2026-08-10", interval_days=4.0,
            next_review_date="2026-08-20", difficulty=3.2, grade=3,
        )
        rendered = format_session_detail_page(
            [rec], 0, 1, is_admin=True
        ).render(Backend.MDV2)
        # Single-escaped dash in the word 'well-being' -> 'well\-being'.
        self.assertIn("well\\-being", rendered)
        # No double-backslash escape anywhere (the crash signature).
        self.assertNotIn("\\\\-", rendered)
        # The admin Δ delta is still present.
        self.assertIn("Δ", rendered)

    def test_not_modified_callback_acks_exactly_once(self):
        # Regression (reviewer finding): say() answers the callback on "message
        # is not modified"; the handler must NOT answer again (which would be a
        # double answer_callback_query).
        report = self._stash([0])
        ctx = self._ctx()
        nonce = "n3"
        ctx.user_data["session_summary"] = {
            "report": report, "is_admin": False, "nonce": nonce,
        }
        q = MagicMock()
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )
        q.message.message_id = 5
        u = self._update()
        u.callback_query = q
        with patch.object(
            study_handler, "notify_callback", new_callable=AsyncMock
        ) as handler_notify, patch.object(
            send_pretty, "notify_callback", new_callable=AsyncMock
        ) as say_notify:
            asyncio.run(_handle_session_summary_callback(u, ctx, f"detail:{nonce}"))
        say_notify.assert_called_once()
        handler_notify.assert_not_awaited()

    def test_legend_flow_opens_and_back_returns_to_page(self):
        # R8: legend button on every detail page; it edits in place to the legend
        # and its back button returns to the exact page it was opened from.
        report = self._stash([0, 1, 2, 3, 4, 5, 6, 7, 8])  # 9 words -> 2 pages
        ctx = self._ctx()
        nonce = "n4"
        ctx.user_data["session_summary"] = {
            "report": report, "is_admin": False, "nonce": nonce,
        }
        q = MagicMock()
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        q.message.message_id = 5
        u = self._update()
        u.callback_query = q
        with patch.object(study_handler, "notify_callback", new_callable=AsyncMock):
            # open page 2
            asyncio.run(_handle_session_summary_callback(u, ctx, f"page:1:{nonce}"))
            text = q.edit_message_text.call_args.args[0]
            self.assertIn("صفحه ۲ از ۲", text)
            # open the legend from page 2 -> legend content replaces the message
            asyncio.run(_handle_session_summary_callback(u, ctx, f"legend:1:{nonce}"))
            text = q.edit_message_text.call_args.args[0]
            self.assertIn("راهنمای نمادها", text)
            self.assertNotIn("صفحه ۲ از ۲", text)
            # back (via the page route) returns to the exact page 2
            asyncio.run(_handle_session_summary_callback(u, ctx, f"page:1:{nonce}"))
            text = q.edit_message_text.call_args.args[0]
            self.assertIn("صفحه ۲ از ۲", text)

    def test_legend_button_on_every_detail_page(self):
        # R8: the legend button is emitted on every page of the detail keyboard.
        from config.keyboards import session_summary_detail_keyboard

        for page, total in ((0, 2), (1, 2)):
            kb = session_summary_detail_keyboard(page, total, "nonce")
            data = {btn.callback_data for row in kb.inline_keyboard for btn in row}
            self.assertIn(f"session:summary:legend:{page}:nonce", data)

if __name__ == "__main__":
    unittest.main()