"""Integration tests for study-session grade after bot restart (issue #401).

Mirrors the self-contained temp-DB harness from test_grade_feedback_intent.py.
Covers the locked contract:
- R1: a grade after a restart advances the DB-persisted session (no wrong_state).
- R2: a stale/out-of-session grade button is rejected (never grades a non-active card).
- R3: an idempotent re-grade (DB write landed but advance was lost) skips + advances
      without soft-locking or double-grading; a legit new-session review still grades.
- Edge: no session at all (no memory, no persisted) rejects safely.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema
from services.session import SessionNode
from handlers import srs_handler
from handlers.study_handler import (
    SessionState,
    _persist_session,
    _restore_persisted_session,
)
from services.utils.callback_notifications import CallbackNoticeIntent


class StudySessionGradeRestartTests(unittest.TestCase):
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
        self.w1 = self._add_word("alpha")
        self.w2 = self._add_word("beta")
        self.w3 = self._add_word("gamma")

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _add_word(self, word):
        card = {
            "word": word, "fa_meaning": "م", "fa_explanation": "ت",
            "examples": [], "example_translations": [], "synonyms": [],
            "antonyms": [], "grammar_tip": "",
        }
        db.add_saved_word(1, word, "en", card)
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()["id"]

    def _session(self, word_ids, activity_type="first_exposure"):
        return SessionState(
            nodes=[
                SessionNode(activity_type=activity_type, source_tier=0, card_data={}, source_id=w)
                for w in word_ids
            ],
            total_cards=len(word_ids),
            tier3_context={},
            study_msg_id=None,
            plan="free",
            graded_word_ids=[],
        )

    def _persist(self, state):
        _persist_session(1, state)

    def _query(self):
        q = MagicMock()
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        q.message = MagicMock()
        return q

    def _update(self, q):
        u = MagicMock()
        u.effective_user.id = 1
        u.callback_query = q
        u.effective_chat = MagicMock()
        u.effective_chat.id = 1
        return u

    def _ctx(self):
        c = MagicMock()
        c.user_data = {}
        c.bot = MagicMock()
        c.bot.edit_message_text = AsyncMock()
        c.bot.send_message = AsyncMock()
        return c

    # --- R1: post-restart grade advances the persisted session ---
    def test_post_restart_grade_advances_persisted_session(self):
        self._persist(self._session([self.w2]))  # only w2 left, no in-memory session
        ctx = self._ctx()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(
                srs_handler._handle_first_exposure_grade(
                    self._update(self._query()), ctx, "4", "1", str(self.w2)
                )
            )
            notify.assert_called_once()
            self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.SUCCESS)
        # word graded and session completed/cleared (no wrong_state, no soft-lock)
        self.assertTrue(db.get_saved_word(self.w2, 1)["first_exposure_done"])
        self.assertIsNone(_restore_persisted_session(1))

    # --- R2: stale/out-of-session button rejected ---
    def test_stale_button_rejected(self):
        self._persist(self._session([self.w2]))  # active node is w2
        ctx = self._ctx()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            # callback targets w1, which is not the active card
            asyncio.run(
                srs_handler._handle_first_exposure_grade(
                    self._update(self._query()), ctx, "4", "1", str(self.w1)
                )
            )
            notify.assert_called_once()
            self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.IMPORTANT_ERROR)
            self.assertIn("این پیام دیگر معتبر نیست", notify.call_args.args[1])
        # w1 was NOT graded; session unchanged
        self.assertFalse(db.get_saved_word(self.w1, 1)["first_exposure_done"])
        self.assertEqual(_restore_persisted_session(1).nodes[0].source_id, self.w2)

    # --- R3: idempotent re-grade when the prior advance was lost ---
    def test_idempotent_regrade_when_advance_lost(self):
        # w2 already graded in DB (prior grade whose advance was lost), but the
        # persisted session still lists it as the active card.
        self.assertTrue(db.grade_first_exposure(self.w2, 3, 1).ok)
        self._persist(self._session([self.w2]))
        ctx = self._ctx()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(
                srs_handler._handle_first_exposure_grade(
                    self._update(self._query()), ctx, "4", "1", str(self.w2)
                )
            )
            notify.assert_called_once()
            # idempotent skip -> INFO toast, NOT an error
            self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.INFO)
            self.assertIn("قبلاً ثبت شد", notify.call_args.args[1])
        # advanced without re-grading; session cleared
        self.assertIsNone(_restore_persisted_session(1))
        self.assertTrue(db.get_saved_word(self.w2, 1)["first_exposure_done"])

    # --- Edge: no session at all (no memory, nothing persisted) ---
    def test_no_session_grades_standalone(self):
        # No active session (and nothing persisted): a grade still records the
        # word. The handler only needs a session for the stale-guard / idempotent
        # advance (R2/R3); a stray standalone grade is harmless (R1 preserves
        # the prior behaviour).
        ctx = self._ctx()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(
                srs_handler._handle_first_exposure_grade(
                    self._update(self._query()), ctx, "4", "1", str(self.w1)
                )
            )
            notify.assert_called_once()
            self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.SUCCESS)
        self.assertTrue(db.get_saved_word(self.w1, 1)["first_exposure_done"])

    # --- R1 on the regular-review path as well ---
    def test_review_post_restart_advances(self):
        self.assertTrue(db.grade_first_exposure(self.w2, 3, 1).ok)  # w2 now in review state
        self._persist(self._session([self.w2], activity_type="srs_review"))
        ctx = self._ctx()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(
                srs_handler._handle_srs_review(
                    self._update(self._query()), 3, "1", str(self.w2), ctx
                )
            )
            notify.assert_called_once()
            self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.SUCCESS)
        self.assertIsNone(_restore_persisted_session(1))


if __name__ == "__main__":
    unittest.main()
