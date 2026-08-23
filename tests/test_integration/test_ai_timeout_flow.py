import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import bot
from services import db
from services.db import schema as db_schema
from handlers import user as user_handler


class AiTimeoutFlowTest(unittest.IsolatedAsyncioTestCase):
    """AI hang must refund the reserved quota, remove the wait message, and
    show the dedicated busy message instead of silently consuming a quota."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        with db.get_conn() as conn:
            conn.execute("UPDATE users SET onboarded=1, plan='silver' WHERE user_id=1")
            conn.commit()

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    def _make_update(self):
        message = MagicMock()
        message.text = "hello"
        message.reply_text = AsyncMock()
        chat = MagicMock()
        chat.id = 1
        chat.send_action = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.message = message
        update.effective_chat = chat
        return update

    def _make_context(self):
        context = MagicMock()
        context.user_data = {"awaiting": "ask_word"}
        wait_message = MagicMock()
        wait_message.delete = AsyncMock()
        context.bot = AsyncMock()
        context.bot.send_message.return_value = wait_message
        return context, wait_message

    def _slow_ai(self, *args, **kwargs):
        time.sleep(0.5)
        return {"word": "hello", "fa_meaning": "سلام"}

    async def test_ask_word_ai_hang_refunds_quota_and_sends_busy_message(self):
        update = self._make_update()
        context, wait_message = self._make_context()

        with patch.object(bot, "_telegram_offline", False), \
             patch.object(bot, "is_owner", return_value=False), \
             patch.object(bot, "ASK_WORD_AI_TIMEOUT_SECONDS", 0.05), \
             patch.object(bot, "_call_ai_limited", side_effect=self._slow_ai):
            await bot.text_router(update, context)

        row = db.get_user(1)
        self.assertEqual(row["words_asked_today"], 0, "quota must be refunded on timeout")

        texts = [c.kwargs.get("text") for c in context.bot.send_message.call_args_list]
        self.assertTrue(
            any(t and "شلوغ" in t for t in texts),
            "dedicated busy message must be sent on timeout",
        )
        wait_message.delete.assert_awaited()

        with db.get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) c FROM query_results WHERE user_id=1"
            ).fetchone()["c"]
        self.assertEqual(count, 0, "no card may be delivered on timeout")

    async def test_grammar_tip_retired_sends_disabled_and_no_quota(self):
        # Retired stub: no AI hang, no quota, just disabled message (#24)
        update = self._make_update()
        context, wait_message = self._make_context()

        await user_handler.send_grammar_tip(update, context)

        row = db.get_user(1)
        self.assertEqual(row["grammar_tips_asked_today"], 0, "retired tip must not reserve quota")
        texts = [c.kwargs.get("text") for c in context.bot.send_message.call_args_list]
        self.assertTrue(any(t and "غیرفعال" in t for t in texts), "retired disabled message must be sent")


if __name__ == "__main__":
    unittest.main()
