"""Phase 02 — per-user sliding-window lock (plan-27).

Verifies handler integration: 5/10s window per action.
Rapid 6 clicks on study/srs/query -> 5 pass, 6th throttled,
and no quota burn / no AI call on throttled request.

Through routing layer where possible, mocked Telegram + real DB
(snapshot isolation), following tests/test_integration pattern.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


THROTTLE_TEXT = "⏳ لطفاً کمی صبر کنید و دوباره تلاش کنید."


def _clear_rate():
    from services.scheduling import _clear_rate_buckets

    _clear_rate_buckets()


class PerUserLockStudyTest(unittest.TestCase):
    def setUp(self):
        import bot

        self.offline_patcher = patch.object(bot, "_telegram_offline", False)
        self.offline_patcher.start()
        _clear_rate()
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1, plan='free' WHERE user_id=1")
            conn.commit()

    def tearDown(self):
        _clear_rate()
        self.offline_patcher.stop()
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _sessions_used(self):
        from services.scheduling import _session_key

        with db.get_conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (_session_key(1),)).fetchone()
        return int(row["value"]) if row and row["value"] else 0

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        return ctx

    def _update(self):
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 100
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.data = "study:start"
        update.callback_query.message = MagicMock()
        update.callback_query.message.message_id = 10
        return update

    def _node(self, word_id):
        from services.session import SessionNode

        return SessionNode(
            activity_type="srs_review",
            source_tier=1,
            card_data={"word": "hello"},
            source_id=word_id,
            activity_meta={"user_id": 1},
            grade_policy_ref="srs_review",
        )

    def test_study_rapid_6_clicks_5_pass_6th_throttled_no_quota_burn(self):
        """study_start guard: 5 allowed, 6th throttled before consume_session_slot."""
        from handlers.study_handler import handle_study_start

        # Need words to build session; seed one
        card = {"word": "hello", "fa_meaning": "سلام", "fa_explanation": "ت", "examples": ["Hi"], "example_translations": ["سلام"], "synonyms": [], "antonyms": [], "grammar_tip": ""}
        db.add_saved_word(1, "w1", "en", card)
        with db.get_conn() as conn:
            wid = conn.execute("SELECT id FROM saved_words WHERE word='w1'").fetchone()["id"]
        # ensure exposing so build can use it if not mocked
        db.grade_first_exposure(wid, 3, 1)

        node = self._node(wid)

        # High limit so quota doesn't block before throttle
        patch_limit = patch("services.scheduling._max_sessions_for_plan", return_value=10)
        patch_limit.start()
        # mock build to always return a node, and send to succeed
        build_patcher = patch("handlers.study_handler.build_session_list", return_value=([node], {"user_id": 1, "remaining_slots": 0}))
        build_patcher.start()
        send_patcher = patch("services.send_pretty.send", new=AsyncMock(return_value=MagicMock(message_id=100)))
        send_patcher.start()
        # also mock clear/load to avoid cross-call resume interference: clear after each call
        try:
            # Track consume calls
            from services import scheduling as sched
            orig_consume = sched.consume_session_slot
            consume_calls = []

            def counting_consume(uid, plan="free"):
                res = orig_consume(uid, plan)
                if res:
                    consume_calls.append(uid)
                return res

            with patch("handlers.study_handler.consume_session_slot", side_effect=counting_consume):
                for i in range(5):
                    ctx = self._context()
                    update = self._update()
                    # clear persisted session to force fresh build each time
                    db.clear_study_session(1)
                    asyncio.run(handle_study_start(update, ctx))
                    # verify throttle not triggered for first 5
                    answer_text = ""
                    if update.callback_query.answer.await_count:
                        answer_text = update.callback_query.answer.call_args[0][0] if update.callback_query.answer.call_args[0] else ""
                    self.assertNotIn("صبر کنید", answer_text)
                    # persisted session would exist; clear for next iteration
                    db.clear_study_session(1)

                # 6th click should be throttled — no consume
                ctx6 = self._context()
                update6 = self._update()
                db.clear_study_session(1)
                asyncio.run(handle_study_start(update6, ctx6))
                # Throttle answer
                self.assertTrue(update6.callback_query.answer.await_count >= 1)
                called_texts = [c[0][0] for c in update6.callback_query.answer.call_args_list if c[0]]
                self.assertTrue(any(THROTTLE_TEXT in (t or "") for t in called_texts), f"expected throttle, got {called_texts}")
                # consume not called on 6th -> total 5
                self.assertEqual(len(consume_calls), 5, "6th throttled must not consume quota")
                self.assertEqual(self._sessions_used(), 5)
        finally:
            send_patcher.stop()
            build_patcher.stop()
            patch_limit.stop()


class PerUserLockSrsTest(unittest.TestCase):
    def setUp(self):
        import bot

        self.offline_patcher = patch.object(bot, "_telegram_offline", False)
        self.offline_patcher.start()
        _clear_rate()
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1 WHERE user_id=1")
            conn.commit()

    def tearDown(self):
        _clear_rate()
        self.offline_patcher.stop()
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _seed_due_word(self, word):
        card = {"word": word, "fa_meaning": "م", "fa_explanation": "ت", "examples": ["A"], "example_translations": ["م"]}
        db.add_saved_word(1, word, "en", card)
        with db.get_conn() as conn:
            row = conn.execute("SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)).fetchone()
            wid = row["id"]
        db.grade_first_exposure(wid, 3, 1)
        # make due by setting next_review_at in past
        with db.get_conn() as conn:
            conn.execute("UPDATE saved_words SET next_review_at='2000-01-01T00:00:00+00:00' WHERE id=?", (wid,))
            conn.commit()
        return wid

    def _make_update(self, word_id):
        q = MagicMock()
        q.answer = AsyncMock()
        q.message = MagicMock()
        upd = MagicMock()
        upd.effective_user.id = 1
        upd.effective_chat.id = 100
        upd.callback_query = q
        upd.callback_query.data = f"srs:3:1:{word_id}"
        return upd

    def _ctx(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        return ctx

    def test_srs_rapid_6_grades_5_pass_6th_throttled_no_fsrs(self):
        from handlers.srs_handler import _handle_srs_review

        wids = [self._seed_due_word(f"w{i}") for i in range(6)]

        grade_calls = []

        orig_grade = db.grade_word_review

        def counting_grade(word_id, grade, user_id, *args, **kwargs):
            # F1 batch: the handler forwards event/streak kwargs; forward them
            # so the mock stays compatible with the batched signature.
            res = orig_grade(word_id, grade, user_id, *args, **kwargs)
            grade_calls.append(word_id)
            return res

        # Need active session per grade to pass active check. Mock get_active_study_session
        from services.session import SessionNode
        from handlers.study_handler import SessionState

        def make_state_for(wid):
            node = SessionNode(activity_type="srs_review", source_tier=1, card_data={"word": f"w{wid}"}, source_id=wid, activity_meta={"user_id": 1}, grade_policy_ref="srs_review")
            st = SessionState(
                nodes=[node],
                total_cards=1,
                tier3_context={},
                study_msg_id=999,
                plan="free",
                graded_word_ids=[],
                before_stability={},
                revealed=False,
                active_prompt_type=None,
                active_prompt_word_id=None,
            )
            return st

        call_count = {"n": 0}

        def fake_get_active(uid, ctx):
            idx = call_count["n"]
            if idx < len(wids):
                return make_state_for(wids[idx])
            return None

        with patch("handlers.srs_handler.get_active_study_session", side_effect=fake_get_active), \
             patch.object(db, "grade_word_review", side_effect=counting_grade), \
             patch("handlers.srs_handler.advance_session", new=AsyncMock()), \
             patch("services.send_pretty.edit", new=AsyncMock()):

            for i in range(5):
                call_count["n"] = i
                upd = self._make_update(wids[i])
                ctx = self._ctx()
                asyncio.run(_handle_srs_review(upd, 3, "1", str(wids[i]), ctx))
                # not throttled
                texts = [c[0][0] for c in upd.callback_query.answer.call_args_list if c[0]]
                self.assertFalse(any(THROTTLE_TEXT in (t or "") for t in texts), f"unexpected throttle at i={i}")

            # 6th should throttle before grade_word_review
            call_count["n"] = 5
            upd6 = self._make_update(wids[5])
            ctx6 = self._ctx()
            asyncio.run(_handle_srs_review(upd6, 3, "1", str(wids[5]), ctx6))
            texts6 = [c[0][0] for c in upd6.callback_query.answer.call_args_list if c[0]]
            self.assertTrue(any(THROTTLE_TEXT in (t or "") for t in texts6), f"expected throttle, got {texts6}")
            self.assertEqual(len(grade_calls), 5, "6th throttled must not call grade_word_review")


class PerUserLockQueryTest(unittest.TestCase):
    def setUp(self):
        import bot

        self.offline_patcher = patch.object(bot, "_telegram_offline", False)
        self.offline_patcher.start()
        _clear_rate()
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1, plan='emerald' WHERE user_id=1")
            conn.commit()
        self.card = {
            "word": "hello",
            "phonetic": "/həˈloʊ/",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "examples": ["Hello!"],
            "example_translations": ["سلام!"],
            "synonyms": [],
            "antonyms": [],
            "grammar_tip": "",
        }

    def tearDown(self):
        _clear_rate()
        self.offline_patcher.stop()
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _make_update(self, text):
        msg = MagicMock()
        msg.text = text
        chat = MagicMock()
        chat.id = 100
        chat.send_action = AsyncMock()
        upd = MagicMock()
        upd.effective_user.id = 1
        upd.effective_chat = chat
        upd.message = msg
        upd.effective_message = msg
        # text_router uses update.message or effective_message text
        upd.callback_query = None
        return upd

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {"awaiting": "ask_word"}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        ctx.bot.send_chat_action = AsyncMock()
        return ctx

    def test_query_rapid_6_asks_5_pass_6th_throttled_no_ai(self):
        import bot

        # patch limits high? free plan word_query limit is ~10? Use actual but 5 < limit
        ai_calls = []

        def fake_call_ai(*args, **kwargs):
            ai_calls.append(1)
            # Return distinct word per query so word-dedup does not collapse 6 distinct queries into 1
            # bot passes user_prompt as the query text; make word unique per query
            user_prompt = kwargs.get("user_prompt", "")
            card = dict(self.card)
            if isinstance(user_prompt, str) and user_prompt:
                card["word"] = user_prompt
            return card

        def fake_prepare(data, **kw):
            return data

        words = ["hello", "world", "apple", "banana", "cherry", "grape"]
        for i, w in enumerate(words):
            upd = self._make_update(w)
            ctx = self._make_context()
            # need awaiting routing: text_router expects awaiting == ask_word already set
            with patch.object(bot, "_call_ai_limited", side_effect=fake_call_ai), \
                 patch.object(bot, "_prepare_cached_card", side_effect=fake_prepare), \
                 patch.object(bot, "_start_llm_wait_state", new=AsyncMock(return_value=None)), \
                 patch.object(bot, "_finish_llm_wait_state", new=AsyncMock()), \
                 patch.object(bot, "is_owner", return_value=False):
                asyncio.run(bot.text_router(upd, ctx))
            if i < 5:
                self.assertEqual(len(ai_calls), i + 1, f"AI should be called for i={i}")
                # first 5 not throttled: should have delivered card, so awaiting cleared or not throttle text
                sent_texts = [c.kwargs.get("text", "") for c in ctx.bot.send_message.call_args_list]
                self.assertFalse(any(THROTTLE_TEXT in (t or "") for t in sent_texts), f"unexpected throttle at i={i} texts={sent_texts}")
            else:
                # 6th throttled: AI not called, throttle message sent, quota unchanged
                self.assertEqual(len(ai_calls), 5, "6th throttled must not call AI")
                sent_texts = [c.kwargs.get("text", "") for c in ctx.bot.send_message.call_args_list]
                self.assertTrue(any(THROTTLE_TEXT in (t or "") for t in sent_texts), f"expected throttle, got {sent_texts}")
                # quota should be 5, not 6
                row = db.get_user(1)
                self.assertEqual(row["words_asked_today"], 5, "throttled request must not burn quota")

        # also verify that after window, a different user is not throttled (isolation)
        # but we just clear rate and try with user 2 would pass; not needed


if __name__ == "__main__":
    unittest.main()
