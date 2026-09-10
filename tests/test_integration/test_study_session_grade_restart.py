"""Integration tests for study-session grading after a bot restart (issue #401).

Mirrors the self-contained temp-DB harness from
tests/test_integration/test_study_session_restart_flow.py.

Covers the locked contract:
- R1: a grade after a restart advances the DB-persisted same-day session (no
  wrong_state, no soft-lock) — on both the first-exposure and review paths.
- R2: a stale/out-of-session grade button is rejected (never grades a non-active
  card), and the guard also checks the node's activity_type (an old
  first-exposure card whose word resurfaced as a review node cannot be graded
  through the stale button).
- R3: idempotent re-grade is driven by the durable, session-scoped
  `graded_word_ids` — a card already graded in this session (its DB write
  landed but its advance was lost, or a genuine double tap) is skipped WITHOUT a
  second FSRS write (no corruption) and without soft-locking. A card that
  legitimately reappears in a *new* session still grades normally.
- A genuine `wrong_state` (word never exposed) stays an actionable error.
- Edge: a grade with no session at all (no memory, nothing persisted) still
  records the word standalone.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import TimedOut

from services import db
from services.db import schema as db_schema
from services.session import SessionNode
from handlers import srs_handler
from handlers.study_handler import (
    SessionState,
    _persist_session,
    _restore_persisted_session,
    _state_from_json,
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

    def _session(self, word_ids, activity_type="first_exposure", graded_word_ids=None, plan="free"):
        # T2 day-boundary (619/622): same-day harness states carry today's
        # stamp; a missing/empty date now means stale and is discarded.
        from handlers.study_handler import _app_day_str
        return SessionState(
            nodes=[
                SessionNode(activity_type=activity_type, source_tier=0, card_data={}, source_id=w)
                for w in word_ids
            ],
            total_cards=len(word_ids),
            tier3_context={},
            study_msg_id=None,
            plan=plan,
            graded_word_ids=list(graded_word_ids or []),
            session_date=_app_day_str(),
        )

    def _persist(self, state):
        _persist_session(1, state)

    def _review_events(self, word_id=None):
        with db.get_conn() as conn:
            if word_id is None:
                return conn.execute("SELECT COUNT(*) FROM review_events").fetchone()[0]
            return conn.execute(
                "SELECT COUNT(*) FROM review_events WHERE word_id=? AND user_id=1",
                (word_id,),
            ).fetchone()[0]

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
        # T4: completion summary ships via Backend.RICH (do_api_request).
        c.bot.do_api_request = AsyncMock(return_value={"message_id": 5})
        return c

    def _rich_text(self, ctx):
        """Last Rich markdown payload sent through the mocked Bot API."""
        payload = ctx.bot.do_api_request.call_args.kwargs["api_kwargs"]
        return payload["rich_message"]["markdown"]

    # --- R1: post-restart grade advances the persisted session (FE path) ---
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

    # --- R2: stale/out-of-session button rejected (FE path) ---
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

    # --- R2 on the review path (previously uncovered) ---
    def test_review_path_stale_button_rejected(self):
        self._persist(self._session([self.w2], activity_type="srs_review"))
        ctx = self._ctx()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            # callback targets w1, not the active review card
            asyncio.run(
                srs_handler._handle_srs_review(
                    self._update(self._query()), 3, "1", str(self.w1), ctx
                )
            )
            notify.assert_called_once()
            self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.IMPORTANT_ERROR)
            self.assertIn("این پیام دیگر معتبر نیست", notify.call_args.args[1])
        self.assertFalse(db.get_saved_word(self.w1, 1)["first_exposure_done"])
        self.assertEqual(_restore_persisted_session(1).nodes[0].source_id, self.w2)

    # --- R2 hole (activity_type): an old FE card whose word resurfaced as the
    #     active review node must not be gradeable through the stale FE button ---
    def test_stale_fe_button_over_active_review_node_rejected(self):
        self.assertTrue(db.grade_first_exposure(self.w2, 3, 1).ok)  # w2 now reviewable
        self._persist(self._session([self.w2], activity_type="srs_review", graded_word_ids=[]))
        ctx = self._ctx()
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            # tapping the OLD first-exposure card for w2, which is now the active
            # review node of a newer session
            asyncio.run(
                srs_handler._handle_first_exposure_grade(
                    self._update(self._query()), ctx, "4", "1", str(self.w2)
                )
            )
            notify.assert_called_once()
            self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.IMPORTANT_ERROR)
            self.assertIn("این پیام دیگر معتبر نیست", notify.call_args.args[1])
        # w2 NOT re-graded as FE; its review state is intact; session unchanged
        row = db.get_saved_word(self.w2, 1)
        self.assertEqual(row["first_exposure_done"], 1)  # unchanged from earlier grade
        self.assertEqual(_restore_persisted_session(1).nodes[0].source_id, self.w2)

    # --- R3: idempotent re-grade when the prior advance was lost (no FSRS
    #     corruption). Proves it by snapshotting scheduling fields + telemetry
    #     before and after the duplicate press. ---
    def test_idempotent_regrade_when_advance_lost(self):
        # Session in memory with w2 active, nothing graded yet. The first grade
        # commits to the DB, appends graded_word_ids, and persists — but its
        # advance_session is lost (simulated). w2 is still the active card.
        ctx1 = self._ctx()
        ctx1.user_data["current_session"] = self._session([self.w2], graded_word_ids=[])
        with patch.object(srs_handler, "advance_session", new_callable=AsyncMock):
            asyncio.run(
                srs_handler._handle_first_exposure_grade(
                    self._update(self._query()), ctx1, "4", "1", str(self.w2)
                )
            )
        # Snapshot scheduling + telemetry BEFORE the duplicate press.
        before = db.get_saved_word(self.w2, 1)
        st_before, diff_before, nxt_before = (
            before["stability"], before["difficulty"], before["next_review_at"],
        )
        events_before = self._review_events(self.w2)
        # Restart: fresh ctx (no in-memory session) -> restored from DB with
        # graded_word_ids=[w2] -> idempotent skip, NOT a second grade.
        ctx2 = self._ctx()
        with patch("services.db.words.touch_streak_in_txn", wraps=db.touch_streak_in_txn) as touch:
            with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
                asyncio.run(
                    srs_handler._handle_first_exposure_grade(
                        self._update(self._query()), ctx2, "4", "1", str(self.w2)
                    )
                )
                notify.assert_called_once()
                self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.INFO)
                self.assertIn("قبلاً ثبت شد", notify.call_args.args[1])
        # No double grade: scheduling fields and telemetry are unchanged.
        after = db.get_saved_word(self.w2, 1)
        self.assertEqual(after["stability"], st_before)
        self.assertEqual(after["difficulty"], diff_before)
        self.assertEqual(after["next_review_at"], nxt_before)
        self.assertEqual(self._review_events(self.w2), events_before)
        touch.assert_not_called()
        # Idempotent skip advanced; the single-card session completed + cleared.
        self.assertIsNone(_restore_persisted_session(1))

    # --- R3 also holds on the review path ---
    def test_idempotent_regrade_review_path(self):
        self.assertTrue(db.grade_first_exposure(self.w2, 3, 1).ok)
        ctx1 = self._ctx()
        ctx1.user_data["current_session"] = self._session(
            [self.w2], activity_type="srs_review", graded_word_ids=[]
        )
        with patch.object(srs_handler, "advance_session", new_callable=AsyncMock):
            asyncio.run(
                srs_handler._handle_srs_review(
                    self._update(self._query()), 3, "1", str(self.w2), ctx1
                )
            )
        events_before = self._review_events(self.w2)
        ctx2 = self._ctx()
        with patch("services.db.words.touch_streak_in_txn", wraps=db.touch_streak_in_txn) as touch:
            with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
                asyncio.run(
                    srs_handler._handle_srs_review(
                        self._update(self._query()), 3, "1", str(self.w2), ctx2
                    )
                )
                self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.INFO)
        self.assertEqual(self._review_events(self.w2), events_before)
        touch.assert_not_called()

    # --- A genuine wrong_state (word never exposed) stays an error, never an
    #     idempotent skip. Pins the behaviour so it cannot regress silently. ---
    def test_review_wrong_state_with_active_session_rejected(self):
        # Active review node whose word was never exposed -> genuine wrong_state.
        self._persist(self._session([self.w2], activity_type="srs_review"))
        ctx = self._ctx()
        with patch("services.db.words.touch_streak_in_txn", wraps=db.touch_streak_in_txn) as touch:
            with patch.object(srs_handler, "advance_session", new_callable=AsyncMock) as advance:
                with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
                    asyncio.run(
                        srs_handler._handle_srs_review(
                            self._update(self._query()), 3, "1", str(self.w2), ctx
                        )
                    )
                    self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.IMPORTANT_ERROR)
                    self.assertIn("وضعیت مرور نیست", notify.call_args.args[1])
        touch.assert_not_called()
        advance.assert_not_called()
        self.assertEqual(db.get_saved_word(self.w2, 1)["first_exposure_done"], 0)
        self.assertEqual(self._review_events(self.w2), 0)

    # --- Edge: no session at all (no memory, nothing persisted) still grades
    #     the word standalone. The handler only needs a session for the
    #     stale-guard / idempotent advance (R2/R3). ---
    def test_no_session_grades_standalone(self):
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

    # --- Legacy/partial rows never crash the grade handler (Kilo @95) ---
    def test_restore_graded_word_ids_missing_key_is_empty(self):
        state = _state_from_json(
            '{"nodes": [], "total_cards": 1, "tier3_context": {}, '
            '"study_msg_id": null, "plan": "free"}'
        )
        self.assertEqual(state.graded_word_ids, [])

    def test_restore_graded_word_ids_null_is_empty(self):
        state = _state_from_json(
            '{"nodes": [], "total_cards": 1, "tier3_context": {}, '
            '"study_msg_id": null, "plan": "free", "graded_word_ids": null}'
        )
        self.assertEqual(state.graded_word_ids, [])

    def test_round_trip_graded_word_ids(self):
        state = self._session([self.w1, self.w2], graded_word_ids=[self.w1])
        self._persist(state)
        restored = _restore_persisted_session(1)
        self.assertEqual(restored.graded_word_ids, [self.w1])

    # ------------------------------------------------------------------
    # Bug: last card graded + completion/report edit times out (weak
    # network) -> the session was cleared before the edit, so a re-tap
    # re-graded the card forever and the report never appeared.
    # ------------------------------------------------------------------

    def test_last_card_completion_edit_timeout_no_regrade_and_report_on_retry(self):
        # Single-card gold session. The grade commits, then the completion
        # report edit times out. The session must survive, the card must NOT be
        # re-graded on a re-tap, and the re-tap must finish the session + show
        # the report.
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._session(
            [self.w2], activity_type="first_exposure", graded_word_ids=[], plan="gold"
        )
        # T4: the completion report edit ships via do_api_request (RICH).
        ctx.bot.do_api_request.side_effect = [TimedOut("boom")] * 3
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock):
            asyncio.run(
                srs_handler._handle_first_exposure_grade(
                    self._update(self._query()), ctx, "4", "1", str(self.w2)
                )
            )
        # The session survived the failed completion edit (no premature clear).
        restored = _restore_persisted_session(1)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.nodes[0].source_id, self.w2)
        self.assertIn(self.w2, restored.graded_word_ids)
        self.assertEqual(ctx.user_data["current_session"], restored)

        # Snapshot scheduling + telemetry BEFORE the re-tap.
        before = db.get_saved_word(self.w2, 1)
        st_b, diff_b, nxt_b = (
            before["stability"], before["difficulty"], before["next_review_at"],
        )
        events_before = self._review_events(self.w2)

        # Re-tap: must NOT re-grade; must drive the session to completion and
        # render the report.
        ctx.bot.do_api_request.side_effect = None
        with patch("services.db.words.touch_streak_in_txn", wraps=db.touch_streak_in_txn) as touch:
            with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
                asyncio.run(
                    srs_handler._handle_first_exposure_grade(
                        self._update(self._query()), ctx, "4", "1", str(self.w2)
                    )
                )
                notify.assert_called_once()
                self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.INFO)
                self.assertIn("قبلاً ثبت شد", notify.call_args.args[1])
        after = db.get_saved_word(self.w2, 1)
        self.assertEqual(after["stability"], st_b)
        self.assertEqual(after["difficulty"], diff_b)
        self.assertEqual(after["next_review_at"], nxt_b)
        self.assertEqual(self._review_events(self.w2), events_before)
        touch.assert_not_called()
        # Session finished; the report edit happened and the report is stored.
        self.assertIsNone(_restore_persisted_session(1))
        self.assertNotIn("current_session", ctx.user_data)
        report_text = self._rich_text(ctx)
        self.assertIn("گزارش", report_text)
        self.assertTrue(ctx.user_data.get("session_summary"))

    def test_review_path_last_card_completion_timeout_no_regrade(self):
        # Same stuck-completion scenario on the regular-review path.
        self.assertTrue(db.grade_first_exposure(self.w2, 3, 1).ok)
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._session(
            [self.w2], activity_type="srs_review", graded_word_ids=[], plan="gold"
        )
        # T4: the completion report edit ships via do_api_request (RICH).
        ctx.bot.do_api_request.side_effect = [TimedOut("boom")] * 3
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock):
            asyncio.run(
                srs_handler._handle_srs_review(
                    self._update(self._query()), 3, "1", str(self.w2), ctx
                )
            )
        self.assertIsNotNone(_restore_persisted_session(1))
        before = db.get_saved_word(self.w2, 1)
        st_b, diff_b, nxt_b = (
            before["stability"], before["difficulty"], before["next_review_at"],
        )
        events_before = self._review_events(self.w2)
        ctx.bot.do_api_request.side_effect = None
        with patch("services.db.words.touch_streak_in_txn", wraps=db.touch_streak_in_txn) as touch:
            with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
                asyncio.run(
                    srs_handler._handle_srs_review(
                        self._update(self._query()), 3, "1", str(self.w2), ctx
                    )
                )
                self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.INFO)
        after = db.get_saved_word(self.w2, 1)
        self.assertEqual(after["stability"], st_b)
        self.assertEqual(after["difficulty"], diff_b)
        self.assertEqual(after["next_review_at"], nxt_b)
        self.assertEqual(self._review_events(self.w2), events_before)
        touch.assert_not_called()
        self.assertIsNone(_restore_persisted_session(1))

    # ------------------------------------------------------------------
    # Bug: a mid-session advance edit times out -> the node had already been
    # popped, so the visible card was stale and a re-tap re-graded it.
    # ------------------------------------------------------------------

    def test_mid_session_advance_timeout_rolls_back_no_regrade(self):
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._session(
            [self.w2, self.w3], activity_type="first_exposure", graded_word_ids=[]
        )
        ctx.bot.edit_message_text.side_effect = [TimedOut, TimedOut, TimedOut]
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock):
            asyncio.run(
                srs_handler._handle_first_exposure_grade(
                    self._update(self._query()), ctx, "4", "1", str(self.w2)
                )
            )
        # The failed advance rolled the node back: w2 is still the active card.
        state = ctx.user_data["current_session"]
        self.assertEqual(len(state.nodes), 2)
        self.assertEqual(state.nodes[0].source_id, self.w2)
        events_before = self._review_events(self.w2)
        # Re-tap: no re-grade; the retry advances to the next card.
        ctx.bot.edit_message_text.side_effect = None
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
            asyncio.run(
                srs_handler._handle_first_exposure_grade(
                    self._update(self._query()), ctx, "4", "1", str(self.w2)
                )
            )
            self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.INFO)
        self.assertEqual(self._review_events(self.w2), events_before)
        state = ctx.user_data["current_session"]
        self.assertEqual(len(state.nodes), 1)
        self.assertEqual(state.nodes[0].source_id, self.w3)

    # ------------------------------------------------------------------
    # Bug: no session at all (memory + persisted gone) + a tappable graded
    # card -> the durable ledger must block the re-grade.
    # ------------------------------------------------------------------

    def test_no_session_regrade_blocked_by_durable_ledger(self):
        self.assertTrue(db.grade_first_exposure(self.w1, 3, 1).ok)
        self.assertTrue(db.is_word_graded(1, self.w1, "first_exposure"))
        before = db.get_saved_word(self.w1, 1)
        st_b, diff_b, nxt_b = (
            before["stability"], before["difficulty"], before["next_review_at"],
        )
        events_before = self._review_events(self.w1)
        ctx = self._ctx()
        with patch("services.db.words.touch_streak_in_txn", wraps=db.touch_streak_in_txn) as touch:
            with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
                asyncio.run(
                    srs_handler._handle_first_exposure_grade(
                        self._update(self._query()), ctx, "4", "1", str(self.w1)
                    )
                )
                notify.assert_called_once()
                self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.INFO)
                self.assertIn("قبلاً ثبت شد", notify.call_args.args[1])
        after = db.get_saved_word(self.w1, 1)
        self.assertEqual(after["stability"], st_b)
        self.assertEqual(after["difficulty"], diff_b)
        self.assertEqual(after["next_review_at"], nxt_b)
        self.assertEqual(self._review_events(self.w1), events_before)
        touch.assert_not_called()

    def test_no_session_regrade_blocked_on_review_path(self):
        self.assertTrue(db.grade_first_exposure(self.w1, 3, 1).ok)
        self.assertTrue(db.grade_word_review(self.w1, 3, 1).ok)
        self.assertTrue(db.is_word_graded(1, self.w1, "srs_review"))
        events_before = self._review_events(self.w1)
        ctx = self._ctx()
        with patch("services.db.words.touch_streak_in_txn", wraps=db.touch_streak_in_txn) as touch:
            with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock) as notify:
                asyncio.run(
                    srs_handler._handle_srs_review(
                        self._update(self._query()), 3, "1", str(self.w1), ctx
                    )
                )
                self.assertEqual(notify.call_args.kwargs["intent"], CallbackNoticeIntent.INFO)
        self.assertEqual(self._review_events(self.w1), events_before)
        touch.assert_not_called()

    # ------------------------------------------------------------------
    # The ledger is session-scoped: building a NEW session resets it, so a
    # word can legitimately be graded again in a new session (e.g. an "Again"
    # card that comes due the same day).
    # ------------------------------------------------------------------

    def test_fresh_session_clears_ledger_reenables_regrade(self):
        self.assertTrue(db.grade_first_exposure(self.w1, 3, 1).ok)
        self.assertTrue(db.is_word_graded(1, self.w1, "first_exposure"))
        db.clear_session_grades(1)
        self.assertFalse(db.is_word_graded(1, self.w1, "first_exposure"))
        # After the ledger is cleared (new session), the word resurfacing as a
        # review card can legitimately be graded again without being blocked by
        # its earlier first-exposure entry.
        self.assertTrue(db.grade_word_review(self.w1, 3, 1).ok)
        self.assertTrue(db.is_word_graded(1, self.w1, "srs_review"))

    def test_double_tap_never_double_grades(self):
        # Two re-taps of the same already-graded card: still no double grade
        # (durable ledger + in-session graded_word_ids both consulted).
        self.assertTrue(db.grade_first_exposure(self.w2, 3, 1).ok)
        ctx = self._ctx()
        ctx.user_data["current_session"] = self._session(
            [self.w2], activity_type="srs_review", graded_word_ids=[self.w2], plan="gold"
        )
        # T4: the completion report edit ships via do_api_request (RICH).
        ctx.bot.do_api_request.side_effect = [TimedOut("boom")] * 3
        with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock):
            # First re-tap: skip + advance retry (completion edit fails again).
            asyncio.run(
                srs_handler._handle_srs_review(
                    self._update(self._query()), 3, "1", str(self.w2), ctx
                )
            )
        # Second re-tap: skip + advance retry now succeeds and completes.
        ctx.bot.do_api_request.side_effect = None
        with patch("services.db.words.touch_streak_in_txn", wraps=db.touch_streak_in_txn) as touch:
            with patch("handlers.srs_handler.notify_callback", new_callable=AsyncMock):
                asyncio.run(
                    srs_handler._handle_srs_review(
                        self._update(self._query()), 3, "1", str(self.w2), ctx
                    )
                )
                touch.assert_not_called()
        # The double-tap never triggered a new grade: no review event was added
        # (the card was already graded before the re-taps) and the session still
        # self-heals to completion.
        self.assertEqual(self._review_events(self.w2), 0)
        self.assertIsNone(_restore_persisted_session(1))


if __name__ == "__main__":
    unittest.main()
