"""Integration flow for the grammar-tip delivery path (G2 R6/F6).

Drives the real ``handlers.user.send_grammar_tip`` with a mocked AI result
(the limiter wrapper ``_call_ai_limited`` is patched to return a fixed
grammar-tip dict) and asserts:
- the learner receives the message built by ``format_grammar_tip`` — each
  dynamic field escaped exactly once by the ``send_pretty`` renderer (a missed
  escape would produce a Telegram ``BadRequest``, which is the bug class R6
  targets);
- the tip is persisted via ``db.add_grammar_tip``.

The AI token budget stays zero: no real provider call is made.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.constants import ParseMode

from services import db
from services.db import schema as db_schema
from services.send_pretty import Backend
from services.utils.formatting import format_grammar_tip


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

    def _tip(self):
        return {
            "title": "ماضی استمراری",
            "explanation": "داشتن + فعل ماضی",
            "example": "داشتم میرفتم.",
        }

    def test_delivers_escaped_message_and_persists_tip(self):
        from handlers.user import _grammar_tip_usage_text, send_grammar_tip

        ctx = self._context()
        update = self._text_update()

        with patch("handlers.user._call_ai_limited", return_value=self._tip()):
            asyncio.run(send_grammar_tip(update, ctx))

        expected_text = format_grammar_tip(
            self._tip(), usage_text=_grammar_tip_usage_text(db.get_user(1))
        ).render(Backend.MDV2)

        ctx.bot.send_message.assert_awaited()
        call = ctx.bot.send_message.await_args
        self.assertEqual(call.kwargs["chat_id"], 100)
        self.assertEqual(call.kwargs["text"], expected_text)
        self.assertEqual(call.kwargs["parse_mode"], ParseMode.MARKDOWN_V2)

        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT title, lang, tip_json FROM grammar_tips WHERE user_id=1"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "ماضی استمراری")
        self.assertEqual(rows[0]["lang"], "en")

    def test_dynamic_value_with_mdv2_specials_is_escaped_in_delivery(self):
        from handlers.user import send_grammar_tip

        ctx = self._context()
        update = self._text_update()

        tip = {
            "title": "ضربدر (×) و [پرانتز]",
            "explanation": "نقطه. و ستاره *",
            "example": "کد با ` و \\",
        }
        with patch("handlers.user._call_ai_limited", return_value=tip):
            asyncio.run(send_grammar_tip(update, ctx))

        call = ctx.bot.send_message.await_args
        rendered = call.kwargs["text"]
        # The raw MDV2-braking substrings must not appear unescaped.
        self.assertNotIn("(×)", rendered)
        self.assertNotIn("[پرانتز]", rendered)
        self.assertNotIn("ستاره *", rendered)
        # Escaped forms must be present.
        self.assertIn(r"\(×\)", rendered)
        self.assertIn(r"\[پرانتز\]", rendered)

    def test_delivery_failure_releases_reserved_tip(self):
        from handlers.user import send_grammar_tip

        ctx = self._context()
        update = self._text_update()

        with patch("handlers.user._call_ai_limited", return_value=self._tip()), patch(
            "handlers.user.send", side_effect=RuntimeError("send boom")
        ):
            # Only the delivery ``send`` fails; the error-notification send
            # (``_send_with_retry`` on the mocked bot) succeeds, so the handler
            # swallows the delivery error, notifies, releases the reservation,
            # and returns without propagating.
            asyncio.run(send_grammar_tip(update, ctx))

        error_texts = [
            call.kwargs.get("text")
            for call in ctx.bot.send_message.await_args_list
            if call.kwargs.get("text")
        ]
        self.assertTrue(
            any("ارسال نکته" in text for text in error_texts),
            "expected an error-notification send",
        )
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT grammar_tips_asked_today FROM users WHERE user_id=1"
            ).fetchone()
        self.assertEqual(row["grammar_tips_asked_today"], 0)


if __name__ == "__main__":
    unittest.main()