"""Integration flow — cross-day stale study-session discard (issues 619/622, T2).

Locked contract R3/R4: all three resume paths (``handle_study_start``,
``_get_active_study_session_memory``, ``advance_session``) are gated by the single
``is_stale`` helper; a stale session is popped from memory and its persisted
row + grade ledger cleared via ONE worker-call invalidate, silently, before
quota — then a fresh session is built (quota consumed normally). Stale state
is never re-persisted.

Harness: per-test temp-DB isolation, mocked bot, AI never touched
(``build_session_list`` is patched; grading is local FSRS). No token cost.
"""

from __future__ import annotations

import datetime
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


def _today() -> str:
    from handlers.study_handler import _app_day_str

    return _app_day_str()


def _yesterday() -> str:
    return (
        datetime.date.fromisoformat(_today()) - datetime.timedelta(days=1)
    ).isoformat()


class StaleSessionDayBoundaryFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import bot
        from services import scheduling

        self._offline = patch.object(bot, "_telegram_offline", False)
        self._offline.start()
        self.addCleanup(self._offline.stop)
        scheduling._clear_rate_buckets()

        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.addCleanup(self._restore_db_path)
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")

    def _restore_db_path(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema

    # -- helpers ---------------------------------------------------------
    def _card(self, word):
        return {
            "word": word,
            "phonetic": "/w/",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "synonyms": ["hi"],
            "antonyms": ["bye"],
            "examples": [f"{word} there!"],
            "example_translations": ["سلام!"],
            "grammar_tip": "نکته",
        }

    def _seed_word(self, word, expose=False):
        db.add_saved_word(1, word, "en", self._card(word))
        with db.get_conn() as conn:
            word_id = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()["id"]
        if expose:
            self.assertTrue(db.grade_first_exposure(word_id, 3, 1).ok)
        return word_id

    def _node(self, activity, word_id):
        from services.session import SessionNode

        return SessionNode(
            activity_type=activity, source_tier=1,
            card_data={"word": "w"}, source_id=word_id,
            activity_meta={"user_id": 1}, grade_policy_ref=activity,
        )

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        ctx.bot.do_api_request = AsyncMock(return_value={"message_id": 5})
        return ctx

    def _study_update(self):
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 100
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        return update

    def _grade_update(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 100
        update.callback_query = query
        return update

    def _sessions_used(self):
        from services.scheduling import _session_key

        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (_session_key(1),),
            ).fetchone()
        return int(row["value"]) if row else 0

    def _review_events(self, word_id):
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM review_events WHERE word_id=? AND user_id=1",
                (word_id,),
            ).fetchone()[0]

    def _backdate_memory_and_row(self, ctx):
        """Simulate overnight: memory + persisted row both carry yesterday."""
        from handlers.study_handler import _state_to_json

        stale = ctx.user_data["current_session"]
        stale.session_date = _yesterday()
        db.save_study_session(1, _yesterday(), _state_to_json(stale))
        return stale

    # -- (a) stale memory discarded on next-day start with fresh build ----
    async def test_a_stale_memory_discarded_next_day_fresh_build(self):
        from handlers.study_handler import handle_study_start

        w1 = self._seed_word("hello", expose=True)
        w2 = self._seed_word("world", expose=True)
        node1 = self._node("srs_review", w1)
        node2 = self._node("srs_review", w2)

        with patch(
            "handlers.study_handler.build_session_list",
            return_value=([node1, node2], {"user_id": 1, "remaining_slots": 0}),
        ):
            ctx = self._context()
            await handle_study_start(self._study_update(), ctx)
        self.assertEqual(ctx.user_data["current_session"].session_date, _today())

        self._backdate_memory_and_row(ctx)

        fresh = self._node("srs_review", w2)
        with (
            patch(
                "handlers.study_handler.build_session_list",
                return_value=([fresh], {"user_id": 1, "remaining_slots": 0}),
            ) as mock_build,
            patch(
                "handlers.study_handler.notify_callback", new_callable=AsyncMock
            ) as notify,
        ):
            await handle_study_start(self._study_update(), ctx)
            mock_build.assert_called_once()
            # Silent: no resume toast on the stale-discard path.
            notify.assert_not_awaited()

        state = ctx.user_data["current_session"]
        self.assertEqual(state.session_date, _today())
        self.assertEqual([n.source_id for n in state.nodes], [w2])
        row = db.load_study_session(1)
        self.assertIsNotNone(row)
        self.assertEqual(row[0], _today())

    # -- (b) ledger cleared so the same word is re-gradeable -------------
    async def test_b_ledger_cleared_same_word_regradeable(self):
        from handlers import srs_handler
        from handlers.study_handler import handle_study_start

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch(
            "handlers.study_handler.build_session_list",
            return_value=([node1], {"user_id": 1, "remaining_slots": 0}),
        ):
            ctx = self._context()
            await handle_study_start(self._study_update(), ctx)

        # Yesterday's grade left a ledger entry; backdate to make it stale.
        db.mark_word_graded(1, w1, "srs_review")
        self.assertTrue(db.is_word_graded(1, w1, "srs_review"))
        self._backdate_memory_and_row(ctx)

        fresh = self._node("srs_review", w1)
        with patch(
            "handlers.study_handler.build_session_list",
            return_value=([fresh], {"user_id": 1, "remaining_slots": 0}),
        ):
            await handle_study_start(self._study_update(), ctx)

        # The stale invalidate cleared the ledger, so w1 can be graded again
        # in the new session (no "قبلاً ثبت شد" block).
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))
        with patch(
            "handlers.srs_handler.notify_callback", new_callable=AsyncMock
        ) as notify:
            await srs_handler._handle_srs_review(
                self._grade_update(), 3, "1", str(w1), ctx
            )
            from services.utils.callback_notifications import CallbackNoticeIntent

            self.assertEqual(
                notify.call_args.kwargs["intent"], CallbackNoticeIntent.SUCCESS
            )
        self.assertEqual(self._review_events(w1), 1)

    # -- (c) quota: consumed after discard, not on same-day resume --------
    async def test_c_quota_consumed_after_discard_not_on_resume(self):
        from handlers.study_handler import handle_study_start

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch(
            "handlers.study_handler.build_session_list",
            return_value=([node1], {"user_id": 1, "remaining_slots": 0}),
        ):
            ctx = self._context()
            await handle_study_start(self._study_update(), ctx)
        self.assertEqual(self._sessions_used(), 1)

        # Same-day resume: no fresh build, no extra slot.
        with patch(
            "handlers.study_handler.build_session_list"
        ) as mock_build:
            await handle_study_start(self._study_update(), ctx)
            mock_build.assert_not_called()
        self.assertEqual(self._sessions_used(), 1)

        # Next-day stale: fresh build consumes a slot.
        self._backdate_memory_and_row(ctx)
        fresh = self._node("srs_review", w1)
        with patch(
            "handlers.study_handler.build_session_list",
            return_value=([fresh], {"user_id": 1, "remaining_slots": 0}),
        ):
            await handle_study_start(self._study_update(), ctx)
        self.assertEqual(self._sessions_used(), 2)

    # -- (d) unreviewed cards re-exposed in the new session ----------------
    async def test_d_unreviewed_cards_reexposed_in_new_session(self):
        from handlers.study_handler import handle_study_start

        w1 = self._seed_word("hello", expose=True)
        w2 = self._seed_word("world", expose=True)
        stale_nodes = [self._node("srs_review", w1), self._node("srs_review", w2)]

        with patch(
            "handlers.study_handler.build_session_list",
            return_value=(stale_nodes, {"user_id": 1, "remaining_slots": 0}),
        ):
            ctx = self._context()
            await handle_study_start(self._study_update(), ctx)

        # Nothing graded yesterday; backdate the whole session.
        self._backdate_memory_and_row(ctx)
        self.assertEqual(self._review_events(w1), 0)
        self.assertEqual(self._review_events(w2), 0)

        # The engine re-exposes the unreviewed w1 in the fresh session.
        fresh = [self._node("srs_review", w1)]
        with patch(
            "handlers.study_handler.build_session_list",
            return_value=(fresh, {"user_id": 1, "remaining_slots": 0}),
        ):
            await handle_study_start(self._study_update(), ctx)

        state = ctx.user_data["current_session"]
        self.assertEqual([n.source_id for n in state.nodes], [w1])
        self.assertNotIn(w1, state.graded_word_ids)
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))

    # -- (e) direct grade tap on a stale card does not grade yesterday -----
    async def test_e_direct_grade_tap_on_stale_card_does_not_grade(self):
        from handlers import srs_handler
        from handlers.study_handler import handle_study_start
        from services.utils.callback_notifications import CallbackNoticeIntent

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch(
            "handlers.study_handler.build_session_list",
            return_value=([node1], {"user_id": 1, "remaining_slots": 0}),
        ):
            ctx = self._context()
            await handle_study_start(self._study_update(), ctx)

        self._backdate_memory_and_row(ctx)
        db.mark_word_graded(1, w1, "srs_review")
        # Reset setup-start sends so the asserts below only see the tap.
        ctx.bot.send_message.reset_mock()
        ctx.bot.edit_message_text.reset_mock()

        with patch(
            "handlers.srs_handler.notify_callback", new_callable=AsyncMock
        ) as notify:
            await srs_handler._handle_srs_review(
                self._grade_update(), 3, "1", str(w1), ctx
            )
            notify.assert_called_once()
            self.assertEqual(
                notify.call_args.kwargs["intent"],
                CallbackNoticeIntent.IMPORTANT_ERROR,
            )
            self.assertIn("این پیام دیگر معتبر نیست", notify.call_args.args[1])

        # Yesterday was never graded: no FSRS write, session gone, row +
        # ledger cleared, nothing rendered.
        self.assertEqual(self._review_events(w1), 0)
        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))
        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()

    # -- (F1) row-today + inner-yesterday, empty memory: get_active None --
    # Memory-only contract: the sync gate performs no DB I/O (row left deferred).
    async def test_f1_row_today_inner_yesterday_get_active_none(self):
        from handlers.study_handler import (
            SessionState,
            _state_to_json,
            _get_active_study_session_memory,
        )

        w1 = self._seed_word("hello", expose=True)
        node = self._node("srs_review", w1)
        stale_inner = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=123, plan="free", graded_word_ids=[],
            session_date=_yesterday(),
        )
        # Row date looks current but the inner stamp is yesterday.
        db.save_study_session(1, _today(), _state_to_json(stale_inner))

        ctx = self._context()
        self.assertNotIn("current_session", ctx.user_data)
        result = _get_active_study_session_memory(1, ctx)
        self.assertIsNone(result)
        # No stash, no render, no re-persist of the stale state.
        self.assertNotIn("current_session", ctx.user_data)
        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()
        # Deferred cleanup: the row is left for start/advance to invalidate.
        row = db.load_study_session(1)
        self.assertIsNotNone(row)
        self.assertEqual(row[0], _today())
        # Nothing was graded.
        self.assertEqual(self._review_events(w1), 0)
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))

    # -- (async-a) seam memory-hit fresh: returned as-is, no DB writes -----
    async def test_async_a_memory_hit_fresh_returned_as_is_no_db_writes(self):
        from handlers.study_handler import SessionState, get_active_session_async

        w1 = self._seed_word("hello", expose=True)
        node = self._node("srs_review", w1)
        fresh = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=123, plan="free", graded_word_ids=[],
            session_date=_today(),
        )
        ctx = self._context()
        ctx.user_data["current_session"] = fresh
        with patch(
            "services.db.invalidate_stale_study_session",
            wraps=db.invalidate_stale_study_session,
        ) as mock_inv:
            result = await get_active_session_async(1, ctx)
            mock_inv.assert_not_called()
        self.assertIs(result, fresh)
        self.assertIs(ctx.user_data["current_session"], fresh)
        # No DB writes: the memory hit created no persisted row.
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))

    # -- (async-b) seam memory-miss stale row: None + immediate clear ------
    async def test_async_b_memory_miss_stale_row_returns_none_clears_row_and_ledger(self):
        from handlers.study_handler import (
            SessionState,
            _state_to_json,
            get_active_session_async,
        )

        # Same row-today/inner-yesterday shape as (F1): unlike the sync
        # gate's deferred behavior, the async seam invalidates immediately.
        w1 = self._seed_word("hello", expose=True)
        node = self._node("srs_review", w1)
        stale_inner = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=123, plan="free", graded_word_ids=[],
            session_date=_yesterday(),
        )
        db.save_study_session(1, _today(), _state_to_json(stale_inner))
        db.mark_word_graded(1, w1, "srs_review")
        self.assertTrue(db.is_word_graded(1, w1, "srs_review"))

        ctx = self._context()  # memory absent (restart-over-day)
        self.assertNotIn("current_session", ctx.user_data)
        result = await get_active_session_async(1, ctx)
        self.assertIsNone(result)
        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))
        self.assertEqual(self._review_events(w1), 0)

    # -- (async-c) seam memory-miss no row: None, sessionless path open ----
    async def test_async_c_memory_miss_no_row_returns_none_allows_sessionless_path(self):
        from handlers.study_handler import get_active_session_async

        w1 = self._seed_word("hello", expose=True)
        ctx = self._context()
        self.assertIsNone(db.load_study_session(1))
        result = await get_active_session_async(1, ctx)
        self.assertIsNone(result)
        # Seam itself raises nothing, sends no notice, stashes nothing —
        # the caller may proceed down the legitimate sessionless path.
        self.assertNotIn("current_session", ctx.user_data)
        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))

    # -- (F2) memory-absent + row-stale + ledger: tap not already-graded --
    async def test_f2_row_stale_ledger_tap_not_already_graded(self):
        from handlers import srs_handler
        from handlers.study_handler import SessionState, _state_to_json

        # Unexposed word: a real grade attempt fails with wrong_state, so a
        # successful FSRS write can never re-mark the ledger mid-test.
        w1 = self._seed_word("hello", expose=False)
        node = self._node("srs_review", w1)
        stale = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=123, plan="free", graded_word_ids=[],
            session_date=_yesterday(),
        )
        db.save_study_session(1, _yesterday(), _state_to_json(stale))
        db.mark_word_graded(1, w1, "srs_review")
        self.assertTrue(db.is_word_graded(1, w1, "srs_review"))

        ctx = self._context()  # memory absent (restart-over-day)
        self.assertNotIn("current_session", ctx.user_data)
        with patch(
            "handlers.srs_handler.notify_callback", new_callable=AsyncMock
        ) as notify:
            await srs_handler._handle_srs_review(
                self._grade_update(), 3, "1", str(w1), ctx
            )
            notify.assert_awaited()
            texts = [c.args[1] for c in notify.await_args_list]
            self.assertNotIn("قبلاً ثبت شد", texts)

        # The stale restore cleared the row and the ledger; the failed grade
        # never re-marked it and wrote no review event.
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))
        self.assertEqual(self._review_events(w1), 0)


    # -- (g) W3: exposed word, memory empty, row-date yesterday + ledger:
    #      tap answers stale, NO sessionless grade lands -------------------
    async def test_g_persisted_stale_row_tap_exposed_word_no_sessionless_grade(self):
        from handlers import srs_handler
        from handlers.study_handler import SessionState, _state_to_json
        from services.utils.callback_notifications import CallbackNoticeIntent

        # EXPOSED word: a sessionless grade attempt would SUCCEED (unlike the
        # unexposed word in (f2)), so zero review events proves the guard —
        # not the DB constraint — blocked the grade.
        w1 = self._seed_word("hello", expose=True)
        node = self._node("srs_review", w1)
        stale = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=123, plan="free", graded_word_ids=[],
            session_date=_yesterday(),
        )
        db.save_study_session(1, _yesterday(), _state_to_json(stale))
        db.mark_word_graded(1, w1, "srs_review")
        self.assertTrue(db.is_word_graded(1, w1, "srs_review"))

        ctx = self._context()  # memory absent (restart-over-day)
        self.assertNotIn("current_session", ctx.user_data)
        with patch(
            "handlers.srs_handler.notify_callback", new_callable=AsyncMock
        ) as notify:
            await srs_handler._handle_srs_review(
                self._grade_update(), 3, "1", str(w1), ctx
            )
            notify.assert_called_once()
            self.assertIn("این پیام دیگر معتبر نیست", notify.call_args.args[1])
            self.assertEqual(
                notify.call_args.kwargs["intent"],
                CallbackNoticeIntent.IMPORTANT_ERROR,
            )

        # No grade landed, session gone, row + ledger cleared, nothing rendered.
        self.assertEqual(self._review_events(w1), 0)
        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))
        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()

    # -- (g2) row-today + inner-yesterday, empty memory, exposed word:
    #      tap answers stale, NO sessionless grade lands --------------------
    async def test_g2_row_today_inner_yesterday_exposed_word_stale_no_grade(self):
        from handlers import srs_handler
        from handlers.study_handler import SessionState, _state_to_json
        from services.utils.callback_notifications import CallbackNoticeIntent

        # Same as (g) but the row date looks current while the inner stamp is
        # yesterday: the row date alone must not mark the tap as legitimate.
        # No ledger entry: without the inner-date check the tap falls through
        # to a sessionless grade on yesterday's exposed card (the reviewer
        # scenario). The guard must answer stale and grade nothing.
        w1 = self._seed_word("hello", expose=True)
        node = self._node("srs_review", w1)
        stale_inner = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=123, plan="free", graded_word_ids=[],
            session_date=_yesterday(),
        )
        db.save_study_session(1, _today(), _state_to_json(stale_inner))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))

        ctx = self._context()  # memory absent (restart-over-day)
        self.assertNotIn("current_session", ctx.user_data)
        with patch(
            "handlers.srs_handler.notify_callback", new_callable=AsyncMock
        ) as notify:
            await srs_handler._handle_srs_review(
                self._grade_update(), 3, "1", str(w1), ctx
            )
            notify.assert_called_once()
            self.assertIn("این پیام دیگر معتبر نیست", notify.call_args.args[1])
            self.assertEqual(
                notify.call_args.kwargs["intent"],
                CallbackNoticeIntent.IMPORTANT_ERROR,
            )

        # No grade landed, session gone, row + ledger cleared, nothing rendered.
        self.assertEqual(self._review_events(w1), 0)
        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))
        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()

    # -- (h) W7: advance with stale memory pops + invalidates, no render ----
    async def test_h_advance_memory_stale_pops_invalidates_with_notice(self):
        from handlers.study_handler import advance_session, handle_study_start
        from services.utils.callback_notifications import CallbackNoticeIntent

        w1 = self._seed_word("hello", expose=True)
        node1 = self._node("srs_review", w1)

        with patch(
            "handlers.study_handler.build_session_list",
            return_value=([node1], {"user_id": 1, "remaining_slots": 0}),
        ):
            ctx = self._context()
            await handle_study_start(self._study_update(), ctx)

        self._backdate_memory_and_row(ctx)
        db.mark_word_graded(1, w1, "srs_review")
        ctx.bot.send_message.reset_mock()
        ctx.bot.edit_message_text.reset_mock()

        with patch(
            "handlers.study_handler.notify_callback", new_callable=AsyncMock
        ) as notify:
            await advance_session(self._grade_update(), ctx)
            notify.assert_called_once()
            self.assertIn("این پیام دیگر معتبر نیست", notify.call_args.args[1])
            self.assertEqual(
                notify.call_args.kwargs["intent"],
                CallbackNoticeIntent.IMPORTANT_ERROR,
            )

        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))
        self.assertEqual(self._review_events(w1), 0)
        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()

    # -- (i) W7: advance with row-today/inner-yesterday invalidates + stops --
    async def test_i_advance_persisted_stale_inner_stops_with_notice(self):
        from handlers.study_handler import (
            SessionState,
            _state_to_json,
            advance_session,
        )
        from services.utils.callback_notifications import CallbackNoticeIntent

        w1 = self._seed_word("hello", expose=True)
        node = self._node("srs_review", w1)
        stale_inner = SessionState(
            nodes=[node], total_cards=1, tier3_context={},
            study_msg_id=123, plan="free", graded_word_ids=[],
            session_date=_yesterday(),
        )
        # Row date looks current but the inner stamp is yesterday.
        db.save_study_session(1, _today(), _state_to_json(stale_inner))
        db.mark_word_graded(1, w1, "srs_review")

        ctx = self._context()  # memory absent
        with patch(
            "handlers.study_handler.notify_callback", new_callable=AsyncMock
        ) as notify:
            await advance_session(self._grade_update(), ctx)
            notify.assert_called_once()
            self.assertIn("این پیام دیگر معتبر نیست", notify.call_args.args[1])
            self.assertEqual(
                notify.call_args.kwargs["intent"],
                CallbackNoticeIntent.IMPORTANT_ERROR,
            )

        self.assertNotIn("current_session", ctx.user_data)
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, w1, "srs_review"))
        self.assertEqual(self._review_events(w1), 0)
        ctx.bot.send_message.assert_not_awaited()
        ctx.bot.edit_message_text.assert_not_awaited()


class InvalidateHelperTests(unittest.TestCase):
    """The combined invalidate helper clears BOTH tables (T2 R4)."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.addCleanup(self._restore)
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()

    def _restore(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema

    def test_invalidate_clears_row_and_ledger(self):
        db.save_study_session(1, "2000-01-01", '{"nodes": []}')
        db.mark_word_graded(1, 7, "srs_review")
        self.assertIsNotNone(db.load_study_session(1))
        self.assertTrue(db.is_word_graded(1, 7, "srs_review"))
        db.invalidate_stale_study_session(1)
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, 7, "srs_review"))


class IsStaleTests(unittest.TestCase):
    def test_none_missing_mismatch_stale_match_fresh(self):
        from handlers.study_handler import SessionState, is_stale

        self.assertTrue(is_stale(None, "2026-09-10"))
        legacy = SessionState(
            nodes=[], total_cards=0, tier3_context={},
            study_msg_id=None, plan="free",
        )
        self.assertTrue(is_stale(legacy, "2026-09-10"))
        old = SessionState(
            nodes=[], total_cards=0, tier3_context={},
            study_msg_id=None, plan="free", session_date="2026-09-09",
        )
        self.assertTrue(is_stale(old, "2026-09-10"))
        fresh = SessionState(
            nodes=[], total_cards=0, tier3_context={},
            study_msg_id=None, plan="free", session_date="2026-09-10",
        )
        self.assertFalse(is_stale(fresh, "2026-09-10"))


class RestoreDiscardClearsLedgerTests(unittest.TestCase):
    """_restore_persisted_session discard clears row AND ledger atomically."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        self.addCleanup(self._restore)
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()

    def _restore(self):
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema

    def test_corrupt_json_clears_ledger(self):
        from handlers.study_handler import _restore_persisted_session

        db.save_study_session(1, _today(), "{not valid json")
        db.mark_word_graded(1, 42, "srs_review")
        self.assertTrue(db.is_word_graded(1, 42, "srs_review"))
        self.assertIsNone(_restore_persisted_session(1))
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, 42, "srs_review"))

    def test_empty_nodes_clears_ledger(self):
        from handlers.study_handler import _restore_persisted_session

        db.save_study_session(1, _today(), '{"nodes": []}')
        db.mark_word_graded(1, 43, "srs_review")
        self.assertTrue(db.is_word_graded(1, 43, "srs_review"))
        self.assertIsNone(_restore_persisted_session(1))
        self.assertIsNone(db.load_study_session(1))
        self.assertFalse(db.is_word_graded(1, 43, "srs_review"))


if __name__ == "__main__":
    unittest.main()
