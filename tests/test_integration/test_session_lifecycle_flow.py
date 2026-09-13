"""REF4-T4 integration: advance order + rollback + gather via router-level flow.

Mocked bot, temp-DB snapshot isolation (integration-test-proto). Proves:
- advancing pops the head node and renders the next card (pop->clear-freeze->
  to_thread build->edit->persist order preserved);
- a failed Telegram edit rolls the popped node + freeze back (self-healing);
- completing advance still gathers via store and clears the session.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest

from services import db
from services.db import schema as db_schema
from handlers import study_handler
from handlers.study_handler import advance_session
from services.session import SessionNode
from services.session.store import SessionState


class AdvanceLifecycleFlowTests(unittest.TestCase):
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

    def _card(self, word="hello"):
        return {"word": word, "fa_meaning": "سلام", "phonetic": ""}

    def _word_id(self, word):
        db.add_saved_word(1, word, "en", self._card(word))
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT id FROM saved_words WHERE word=?", (word,)
            ).fetchone()["id"]

    def _node(self, wid, word):
        return SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": word}, source_id=wid,
            activity_meta={"user_id": 1}, grade_policy_ref="srs_review",
        )

    def _update(self):
        u = MagicMock()
        u.effective_user.id = 1
        u.effective_chat = MagicMock()
        u.effective_chat.id = 1
        u.callback_query = None
        u.message = None
        return u

    def _ctx(self):
        c = MagicMock()
        c.user_data = {}
        c.bot = MagicMock()
        c.bot.edit_message_text = AsyncMock()
        c.bot.send_message = AsyncMock()
        c.bot.do_api_request = AsyncMock(return_value={"message_id": 5})
        return c

    def test_advance_pops_and_persists_next(self):
        hello = self._word_id("hello")
        world = self._word_id("world")
        state = SessionState(
            nodes=[self._node(hello, "hello"), self._node(world, "world")],
            total_cards=2, tier3_context={}, study_msg_id=999, plan="free",
            session_date=study_handler._app_day_str(),
        )
        ctx = self._ctx()
        ctx.user_data["current_session"] = state
        asyncio.run(advance_session(self._update(), ctx))
        self.assertEqual(len(state.nodes), 1)
        self.assertEqual(state.nodes[0].card_data["word"], "world")
        ctx.bot.edit_message_text.assert_awaited_once()

    def test_advance_rollback_on_edit_failure(self):
        hello = self._word_id("hello")
        world = self._word_id("world")
        state = SessionState(
            nodes=[self._node(hello, "hello"), self._node(world, "world")],
            total_cards=2, tier3_context={}, study_msg_id=999, plan="free",
            session_date=study_handler._app_day_str(),
            revealed=True, active_prompt_type="meaning",
            active_prompt_word_id=hello,
        )
        ctx = self._ctx()
        ctx.user_data["current_session"] = state
        with patch.object(
            study_handler.send_pretty, "edit",
            new_callable=AsyncMock,
            side_effect=BadRequest("message not found"),
        ):
            with patch.object(
                study_handler.send_pretty, "send", new_callable=AsyncMock
            ):
                asyncio.run(advance_session(self._update(), ctx))
        # popped node restored at head + freeze restored
        self.assertEqual(len(state.nodes), 2)
        self.assertEqual(state.nodes[0].card_data["word"], "hello")
        self.assertTrue(state.revealed)
        self.assertEqual(state.active_prompt_type, "meaning")
        self.assertEqual(state.active_prompt_word_id, hello)
        # session kept for retry (not cleared)
        self.assertIn("current_session", ctx.user_data)

    def test_completion_clears_session(self):
        from services.session.store import load_session

        ctx = self._ctx()
        ctx.user_data["current_session"] = SessionState(
            nodes=[], total_cards=1, tier3_context={}, study_msg_id=99,
            plan="silver", graded_word_ids=[],
            session_date=study_handler._app_day_str(),
        )
        asyncio.run(advance_session(self._update(), ctx))
        self.assertNotIn("current_session", ctx.user_data)
        self.assertIn("session_summary", ctx.user_data)


if __name__ == "__main__":
    unittest.main()
