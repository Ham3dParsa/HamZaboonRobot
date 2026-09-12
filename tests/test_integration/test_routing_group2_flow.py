"""REF1-T5: group-2 callbacks route via the central registry with identical
dispatch and a single callback answer.

Covers query/study/tts/srs through ``bot.callback_router`` (which must hand
them to ``routing_dispatch``): registered prefixes, longest-prefix delete
priority (``srs:delete:*`` wins over the generic grade parser), byte-identical
toasts/fallbacks, exactly one ``query.answer`` per callback.
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services import db
from services.db import schema as db_schema


def _answer_texts(query):
    texts = []
    for call in query.answer.await_args_list:
        args, kwargs = call
        if args:
            texts.append(args[0])
        elif "text" in kwargs:
            texts.append(kwargs["text"])
    return texts


class RoutingGroup2FlowTests(unittest.TestCase):
    def setUp(self):
        import bot

        bot._callback_dedup.clear()
        self._offline = bot._telegram_offline
        bot._telegram_offline = False
        self.tempdir = tempfile.TemporaryDirectory()
        self._prev_db = db.DB_PATH
        self._prev_schema = db_schema.DB_PATH
        new_path = os.path.join(self.tempdir.name, "test.sqlite")
        db.DB_PATH = new_path
        db_schema.DB_PATH = new_path
        db.init_db()
        # Onboarded learner for query/tts flows.
        db.create_user_if_needed(11, "learner")
        db.set_user_lang_goal(11, "en", "general")
        db.set_user_level(11, "beginner")

    def tearDown(self):
        import bot

        bot._telegram_offline = self._offline
        db.DB_PATH = self._prev_db
        db_schema.DB_PATH = self._prev_schema
        self.tempdir.cleanup()

    def _make_update(self, data, user_id=11):
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_chat.id = 100
        query = AsyncMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.message = MagicMock()
        query.message.delete = AsyncMock()
        update.callback_query = query
        return update

    def _make_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        ctx.bot = MagicMock()
        ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
        ctx.bot.edit_message_text = AsyncMock()
        ctx.bot.edit_message_reply_markup = AsyncMock()
        ctx.bot.do_api_request = AsyncMock(return_value={"message_id": 5})
        return ctx

    def _run(self, data, user_id=11):
        import bot

        update = self._make_update(data, user_id=user_id)
        ctx = self._make_context()
        asyncio.run(bot.callback_router(update, ctx))
        return update, ctx

    def test_group2_prefixes_registered(self):
        import bot  # noqa: F401  (group-2 dispatchers register at import)
        import handlers.srs_handler  # noqa: F401  (srs:delete routes)
        import handlers.study_handler  # noqa: F401  (session/reports routes)
        from services.routing import ROUTES

        registered = {prefix for (prefix, _, _) in ROUTES}
        for prefix in ("query", "study", "tts", "srs"):
            self.assertIn(prefix, registered, f"group-2 prefix {prefix!r} not registered")

    def test_srs_delete_entry_wins_over_grade_parser(self):
        """``srs:delete:<uid>:<wid>`` must reach the delete-confirm handler,
        not the generic ``srs:<grade>:...`` parser (longest-prefix match)."""
        from bot import callback_router

        card = {
            "word": "hello",
            "phonetic": "/w/",
            "fa_meaning": "سلام",
            "fa_explanation": "توضیح",
            "synonyms": ["hi"],
            "antonyms": ["bye"],
            "examples": ["hello there!"],
            "example_translations": ["سلام!"],
            "grammar_tip": "نکته",
        }
        db.add_saved_word(11, "hello", "en", card)
        with db.get_conn() as conn:
            word_id = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=11 AND word=?", ("hello",)
            ).fetchone()["id"]
        self.assertTrue(db.grade_first_exposure(word_id, 3, 11).ok)

        from services.session import SessionNode

        node = SessionNode(
            activity_type="srs_review", source_tier=1,
            card_data={"word": "hello"}, source_id=word_id,
            activity_meta={"user_id": 11}, grade_policy_ref="srs_review",
        )
        ctx = self._make_context()
        study_update = self._make_update("study:start")
        from handlers.study_handler import handle_study_start

        with patch(
            "handlers.study_handler.build_session_list",
            return_value=([node], {"user_id": 11, "remaining_slots": 0}),
        ):
            asyncio.run(handle_study_start(study_update, ctx))

        delete_update = self._make_update(f"srs:delete:11:{word_id}")
        asyncio.run(callback_router(delete_update, ctx))
        # Delete-confirm handler re-renders the markup (grade parser would
        # have answered "این دکمه دیگر معتبر نیست." with no markup edit).
        ctx.bot.edit_message_reply_markup.assert_awaited()
        texts = _answer_texts(delete_update.callback_query)
        self.assertFalse(any("دیگر معتبر نیست" in t for t in texts))
        # Nothing graded or deleted by the entry tap itself.
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM saved_words WHERE user_id=11 AND word=?", ("hello",)
            ).fetchone()
        self.assertIsNotNone(row)

    def test_srs_invalid_grade_toast_single_answer(self):
        update, _ = self._run("srs:9:11:5")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("این دکمه دیگر معتبر نیست" in t for t in texts))

    def test_srs_malformed_toast_single_answer(self):
        update, _ = self._run("srs:reveal:11")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("دکمه‌ی نامعتبر است" in t for t in texts))

    def test_query_unknown_action_fallback_single_answer(self):
        update, _ = self._run("query:bogus")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("عملیات ناموفق بود" in t for t in texts))
        _, kwargs = update.callback_query.answer.call_args
        self.assertTrue(kwargs.get("show_alert", False))

    def test_query_add_expired_token_toast(self):
        update, _ = self._run("query:add:deadbeef")
        update.callback_query.answer.assert_awaited()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("منقضی شده" in t for t in texts))

    def test_study_unknown_action_fallback_single_answer(self):
        update, _ = self._run("study:bogus")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("عملیات ناموفق بود" in t for t in texts))

    def test_tts_invalid_payload_toast_single_answer(self):
        update, _ = self._run("tts:pronounce:xx")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("دکمه نامعتبر است" in t for t in texts))

    def test_tts_unknown_action_fallback_single_answer(self):
        update, _ = self._run("tts:bogus")
        update.callback_query.answer.assert_awaited_once()
        texts = _answer_texts(update.callback_query)
        self.assertTrue(any("عملیات ناموفق بود" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
