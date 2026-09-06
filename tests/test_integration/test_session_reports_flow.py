"""Integration tests for persistent session reports + /reports reopen (R10).

Self-contained temp-DB harness mirroring
tests/test_integration/test_session_summary_flow.py.

Covers the locked contract (2026-08-20, rules R10-A..R10-G):
- R10-B: the completed report is persisted; reopening renders it again.
- R10-C: /reports lists recent reports; tapping one reopens the summary;
  detail pages are reachable; back returns to the list.
- R10-F: free users get the summary but NO detail button; Bronze+ get detail.
- R10-E: a foreign/expired report fails closed with an expired notice.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from handlers import study_handler
from handlers.study_handler import (
    _handle_reports_callback,
    advance_session,
    send_reports_list,
)
from services.utils.callback_notifications import CallbackNoticeIntent


class SessionReportsFlowTests(unittest.TestCase):
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

    def _add_word(self, word, stability=3.0):
        card = {
            "word": word, "fa_meaning": "م", "fa_explanation": "ت",
            "examples": [], "example_translations": [], "synonyms": [],
            "antonyms": [], "grammar_tip": "",
        }
        db.add_saved_word(1, word, "en", card)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE saved_words SET stability=? WHERE user_id=1 AND word=?",
                (stability, word),
            )
            return conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()["id"]

    def _add_review_event(self, word_id, created_at, activity_type, grade):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO review_events "
                "(word_id, user_id, revealed_before_answer, outcome, created_at,"
                " grade, activity_type) VALUES (?, ?, 0, ?, ?, ?, ?)",
                (word_id, 1, "correct", created_at, grade, activity_type),
            )

    def _complete_session(self, word_ids, plan, user_id=1):
        ctx = MagicMock()
        ctx.user_data = {"current_session": None}
        ctx.bot = MagicMock()
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.send_message = AsyncMock()
        # T4: completion summary ships via Backend.RICH (do_api_request).
        ctx.bot.do_api_request = AsyncMock(return_value={"message_id": 5})
        state = study_handler.SessionState(
            nodes=[], total_cards=len(word_ids), tier3_context={},
            study_msg_id=99, plan=plan, graded_word_ids=list(word_ids),
            before_stability={wid: 1.0 for wid in word_ids},
        )
        ctx.user_data["current_session"] = state
        u = self._update(user_id)
        asyncio.run(advance_session(u, ctx))
        return ctx

    def _update(self, user_id=1):
        u = MagicMock()
        u.effective_user.id = user_id
        u.effective_chat = MagicMock()
        u.effective_chat.id = user_id
        return u

    def _callback_update(self, user_id=1):
        u = self._update(user_id)
        q = MagicMock()
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        q.message.message_id = 5
        u.callback_query = q
        return u

    def _ctx(self):
        c = MagicMock()
        c.user_data = {}
        c.bot = MagicMock()
        c.bot.edit_message_text = AsyncMock()
        c.bot.send_message = AsyncMock()
        # T4: reopened summary/detail ship via Backend.RICH (do_api_request).
        c.bot.do_api_request = AsyncMock(return_value={"message_id": 5})
        return c

    def _rich_text(self, ctx):
        """Last Rich markdown payload sent through the mocked Bot API."""
        payload = ctx.bot.do_api_request.call_args.kwargs["api_kwargs"]
        return payload["rich_message"]["markdown"]

    def _rich_markup_data(self, ctx):
        """Callback-data set of the last Rich payload keyboard (dict form)."""
        payload = ctx.bot.do_api_request.call_args.kwargs["api_kwargs"]
        markup = payload.get("reply_markup")
        if not markup:
            return set()
        return {
            btn["callback_data"]
            for row in markup["inline_keyboard"]
            for btn in row
            if "callback_data" in btn
        }

    # ------------------------------------------------------------------
    # Persistence (R10-B)
    # ------------------------------------------------------------------

    def test_completion_persists_report_for_free_and_silver(self):
        w = self._add_word("alpha", stability=3.0)
        self._add_review_event(w, "2026-08-19T10:00:00Z", "srs_review", 3)
        self._complete_session([w], "free")
        self._complete_session([w], "silver")
        self.assertEqual(len(db.list_recent_reports(1)), 2)

    # ------------------------------------------------------------------
    # /reports list (R10-C)
    # ------------------------------------------------------------------

    def test_send_reports_list_lists_reports(self):
        w = self._add_word("alpha", stability=3.0)
        self._add_review_event(w, "2026-08-19T10:00:00Z", "srs_review", 3)
        self._complete_session([w], "silver")
        ctx = self._ctx()
        asyncio.run(send_reports_list(self._update(), ctx))
        text = ctx.bot.send_message.call_args.kwargs["text"]
        self.assertIn("گزارش‌های جلسات اخیر", text)
        # New jalali grouped format: day label + count "نشست" with Persian handling
        # (replaces old numbered-list "\. " — ensure no double-escape).
        self.assertIn("نشست", text)
        self.assertNotIn("\\\\", text)
        markup = ctx.bot.send_message.call_args.kwargs.get("reply_markup")
        data = {btn.callback_data for row in markup.inline_keyboard for btn in row}
        self.assertTrue(any(d.startswith("reports:detail:") for d in data))

    def test_send_reports_list_empty_state(self):
        ctx = self._ctx()
        asyncio.run(send_reports_list(self._update(), ctx))
        text = ctx.bot.send_message.call_args.kwargs["text"]
        self.assertIn("گزارشی موجود نیست", text)

    # ------------------------------------------------------------------
    # Reopen + gating (R10-F)
    # ------------------------------------------------------------------

    def test_reopen_summary_for_silver_has_detail_button(self):
        w = self._add_word("alpha", stability=3.0)
        self._add_review_event(w, "2026-08-19T10:00:00Z", "srs_review", 3)
        self._complete_session([w], "silver")
        db.set_plan(1, "silver")
        report_id = db.list_recent_reports(1)[0].report_id
        u = self._callback_update()
        ctx = self._ctx()
        with patch.object(study_handler, "notify_callback", new_callable=AsyncMock):
            asyncio.run(_handle_reports_callback(u, ctx, f"detail:{report_id}:0"))
        text = self._rich_text(ctx)
        self.assertIn("گزارش نشست مطالعه", text)
        data = self._rich_markup_data(ctx)
        self.assertIn(f"reports:detail:{report_id}:1", data)  # جزئیات button

    def test_reopen_summary_for_free_has_no_detail_button(self):
        w = self._add_word("alpha", stability=3.0)
        self._add_review_event(w, "2026-08-19T10:00:00Z", "srs_review", 3)
        self._complete_session([w], "free")  # plan stays 'free'
        report_id = db.list_recent_reports(1)[0].report_id
        u = self._callback_update()
        ctx = self._ctx()
        with patch.object(study_handler, "notify_callback", new_callable=AsyncMock):
            asyncio.run(_handle_reports_callback(u, ctx, f"detail:{report_id}:1"))
        text = self._rich_text(ctx)
        self.assertIn("گزارش نشست مطالعه", text)
        data = self._rich_markup_data(ctx)
        # Free user forced to summary overview: no detail page, no جزئیات button.
        self.assertNotIn(f"reports:detail:{report_id}:1", data)

    def test_detail_page_navigation_and_back(self):
        ids = []
        for i in range(9):
            w = self._add_word(f"w{i}", stability=3.0)
            self._add_review_event(w, "2026-08-19T10:00:00Z", "srs_review", 3)
            ids.append(w)
        self._complete_session(ids, "silver")
        db.set_plan(1, "silver")
        report_id = db.list_recent_reports(1)[0].report_id
        u = self._callback_update()
        ctx = self._ctx()
        with patch.object(study_handler, "notify_callback", new_callable=AsyncMock):
            # detail page 1 (view 1 -> pages index 0)
            asyncio.run(_handle_reports_callback(u, ctx, f"detail:{report_id}:1"))
            text = self._rich_text(ctx)
            self.assertIn("صفحه ۱ از ۲", text)
            self.assertIn("w0", text)
            # detail page 2 (view 2 -> pages index 1)
            asyncio.run(_handle_reports_callback(u, ctx, f"detail:{report_id}:2"))
            text = self._rich_text(ctx)
            self.assertIn("صفحه ۲ از ۲", text)
            self.assertIn("w8", text)
            # back to summary (view 0)
            asyncio.run(_handle_reports_callback(u, ctx, f"detail:{report_id}:0"))
            text = self._rich_text(ctx)
            self.assertIn("گزارش نشست مطالعه", text)
            # back to the list (raw MDV2 path — query edit, unchanged)
            asyncio.run(_handle_reports_callback(u, ctx, "back"))
            text = u.callback_query.edit_message_text.call_args.args[0]
            self.assertIn("گزارش‌های جلسات اخیر", text)

    def test_foreign_or_expired_report_fails_closed(self):
        w = self._add_word("alpha", stability=3.0)
        self._add_review_event(w, "2026-08-19T10:00:00Z", "srs_review", 3)
        self._complete_session([w], "silver")
        report_id = db.list_recent_reports(1)[0].report_id
        # A different user (2) cannot open user 1's report.
        u = self._callback_update(user_id=2)
        ctx = self._ctx()
        with patch.object(
            study_handler, "notify_callback", new_callable=AsyncMock
        ) as notify:
            asyncio.run(_handle_reports_callback(u, ctx, f"detail:{report_id}:0"))
        notify.assert_called_once()
        self.assertEqual(
            notify.call_args.kwargs["intent"], CallbackNoticeIntent.IMPORTANT_ERROR
        )
        self.assertIn("منقضی", notify.call_args.args[1])
        u.callback_query.edit_message_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()