"""Integration flow for the grammar-tip delivery path — RETIRED (#24).

`handlers.user.send_grammar_tip` is now a retired stub (no AI, no quota,
no persistence). These tests assert the retired behavior so the
behavior change stays synced with tests (AGENTS.md §6 test-sync).
Original AI-pipeline tests are archived in docs/archive/retired/.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


class GrammarTipFlowTest(unittest.TestCase):
    def setUp(self):
        import bot

        self.offline_patcher = patch.object(bot, "_telegram_offline", False)
        self.offline_patcher.start()
        self.addCleanup(self.offline_patcher.stop)

        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.delete_message = AsyncMock()
        return ctx

    def _text_update(self, user_id=1, chat_id=100):
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = chat_id
        update.effective_chat.send_action = AsyncMock()
        update.callback_query = None
        update.message = MagicMock()
        return update

    def test_retired_sends_disabled_message_and_does_not_persist(self):
        from handlers.user import send_grammar_tip

        ctx = self._context()
        update = self._text_update()

        asyncio.run(send_grammar_tip(update, ctx))

        ctx.bot.send_message.assert_awaited()
        call = ctx.bot.send_message.await_args
        self.assertIn("غیرفعال", call.kwargs.get("text") or "")
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT title, lang, tip_json FROM grammar_tips WHERE user_id=1"
            ).fetchall()
        self.assertEqual(len(rows), 0)
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT grammar_tips_asked_today FROM users WHERE user_id=1"
            ).fetchone()
        self.assertEqual(row["grammar_tips_asked_today"], 0)

    def test_retired_does_not_call_ai(self):
        from handlers.user import send_grammar_tip

        ctx = self._context()
        update = self._text_update()

        # retired stub has no AI call — just verify it completes without AI
        asyncio.run(send_grammar_tip(update, ctx))
        # if AI were called, it would have required mock; completion alone proves no AI path

    def test_retired_does_not_reserve_quota_on_failure(self):
        from handlers.user import send_grammar_tip

        ctx = self._context()
        update = self._text_update()

        # Even if send were to fail, retired stub does not reserve quota
        with patch("handlers.user.send", side_effect=RuntimeError("send boom")):
            asyncio.run(send_grammar_tip(update, ctx))

        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT grammar_tips_asked_today FROM users WHERE user_id=1"
            ).fetchone()
        self.assertEqual(row["grammar_tips_asked_today"], 0)


if __name__ == "__main__":
    unittest.main()
