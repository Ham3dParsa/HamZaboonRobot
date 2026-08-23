"""Session slot quota atomicity (fix/session-slot-atomic #3).

Verifies:
- consume succeeds under limit, second consume fails at limit (atomic)
- release allows re-consume, release idempotent MAX 0
- no await inside transaction for consume/release
- handler empty-session releases quota
- handler render/send failure releases quota
"""

from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


def _set_db(tmpdir, db_module, schema_module):
    new_path = os.path.join(tmpdir.name, "test.sqlite")
    db_module.DB_PATH = new_path
    schema_module.DB_PATH = new_path
    db_module.init_db()
    return new_path


class SessionSlotAtomicTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db = db.DB_PATH
        self.prev_schema = db_schema.DB_PATH
        _set_db(self.tempdir, db, db_schema)
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1, plan='free' WHERE user_id=1")
            conn.commit()
        # ensure plan limits known: free max_sessions default 1
        # Override to 1 explicitly if needed
        # Use set_setting or plans table? rely on DB plan_spec; default free is 1
        # No need to modify; test will patch _max_sessions_for_plan

    def tearDown(self):
        db.DB_PATH = self.prev_db
        db_schema.DB_PATH = self.prev_schema
        self.tempdir.cleanup()

    def _sessions_used(self):
        from services.scheduling import _session_key
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (_session_key(1),)
            ).fetchone()
        return int(row["value"]) if row and row["value"] is not None else 0

    def _patch_limit(self, limit):
        return patch("services.scheduling._max_sessions_for_plan", return_value=limit)

    def test_consume_succeeds_under_limit(self):
        from services.scheduling import consume_session_slot

        with self._patch_limit(2):
            self.assertTrue(consume_session_slot(1, plan="free"))
            self.assertEqual(self._sessions_used(), 1)
            self.assertTrue(consume_session_slot(1, plan="free"))
            self.assertEqual(self._sessions_used(), 2)

    def test_second_consume_fails_at_limit_atomic(self):
        from services.scheduling import consume_session_slot

        with self._patch_limit(1):
            self.assertTrue(consume_session_slot(1, plan="free"))
            self.assertEqual(self._sessions_used(), 1)
            ok2 = consume_session_slot(1, plan="free")
            self.assertFalse(ok2)
            self.assertEqual(self._sessions_used(), 1, "atomic: failed consume must not increment")

    def test_release_allows_reconsume(self):
        from services.scheduling import consume_session_slot, release_session_slot

        with self._patch_limit(1):
            self.assertTrue(consume_session_slot(1, plan="free"))
            self.assertEqual(self._sessions_used(), 1)
            self.assertFalse(consume_session_slot(1, plan="free"))
            release_session_slot(1)
            self.assertEqual(self._sessions_used(), 0)
            self.assertTrue(consume_session_slot(1, plan="free"))
            self.assertEqual(self._sessions_used(), 1)

    def test_release_idempotent_max_zero(self):
        from services.scheduling import release_session_slot

        with self._patch_limit(1):
            # release when zero stays zero
            release_session_slot(1)
            self.assertEqual(self._sessions_used(), 0)
            release_session_slot(1)
            self.assertEqual(self._sessions_used(), 0)
            # consume 1 then double release clamps to 0
            from services.scheduling import consume_session_slot

            consume_session_slot(1, plan="free")
            self.assertEqual(self._sessions_used(), 1)
            release_session_slot(1)
            release_session_slot(1)
            self.assertEqual(self._sessions_used(), 0)

    def test_no_await_inside_transaction(self):
        import services.scheduling as sched_mod

        for name in ("consume_session_slot", "release_session_slot"):
            src = inspect.getsource(getattr(sched_mod, name))
            self.assertNotIn("await", src, f"{name} must not contain await inside transaction")
            self.assertIn("transaction()", src, f"{name} must use transaction()")

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        return ctx

    def _study_update(self):
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 100
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.data = "study:start"
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

    def _seed_word(self, word):
        card = {
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
        db.add_saved_word(1, word, "en", card)
        with db.get_conn() as conn:
            wid = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=1 AND word=?", (word,)
            ).fetchone()["id"]
        self.assertTrue(db.grade_first_exposure(wid, 3, 1).ok)
        return wid

    def test_handler_empty_session_releases_quota(self):
        """build_session_list empty must release consumed slot."""
        from handlers.study_handler import handle_study_start
        import bot

        with patch.object(bot, "_telegram_offline", False):
            with self._patch_limit(1):
                # need to ensure consume will be called; patch cards_per_session but not needed
                ctx = self._context()
                update = self._study_update()
                with patch("handlers.study_handler.build_session_list", return_value=([], {})):
                    asyncio.run(handle_study_start(update, ctx))
                self.assertEqual(self._sessions_used(), 0, "empty session must release slot")
                # empty notice sent via notify_callback
                ctx.bot.send_message.assert_not_called()  # empty path uses notify_callback, not send
                # ensure callback was answered with "جلسه‌ای برای امروز نداری"
                update.callback_query.answer.assert_awaited()

    def test_handler_build_exception_releases_quota(self):
        """build_session_list exception must release slot (delivered==False)."""
        from handlers.study_handler import handle_study_start
        import bot

        with patch.object(bot, "_telegram_offline", False):
            with self._patch_limit(1):
                ctx = self._context()
                update = self._study_update()
                with patch("handlers.study_handler.build_session_list", side_effect=RuntimeError("boom")):
                    asyncio.run(handle_study_start(update, ctx))
                self.assertEqual(self._sessions_used(), 0, "exception must release slot")

    def test_handler_send_failure_releases_quota(self):
        """Telegram send failure after persist must release slot."""
        from handlers.study_handler import handle_study_start
        import bot

        w1 = self._seed_word("hello")
        node = self._node(w1)
        with patch.object(bot, "_telegram_offline", False):
            with self._patch_limit(1):
                ctx = self._context()
                update = self._study_update()
                # build returns 1 node
                with patch("handlers.study_handler.build_session_list", return_value=([node], {"user_id": 1, "remaining_slots": 0})):
                    # make send_pretty.send fail for first card
                    with patch("services.send_pretty.send", side_effect=RuntimeError("send boom")):
                        asyncio.run(handle_study_start(update, ctx))
                self.assertEqual(self._sessions_used(), 0, "send failure must release slot")
                self.assertNotIn("current_session", ctx.user_data)


if __name__ == "__main__":
    unittest.main()
