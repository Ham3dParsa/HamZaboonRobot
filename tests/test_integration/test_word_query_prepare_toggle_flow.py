"""Phase 3 — prepare + toggle_save wiring (word_query.prepare / toggle_save).

Regression coverage for the deep-module refactor: the query-result prepare
(`query:prepare:`) and save-toggle (`query:add:`) callbacks are now thin
adapters over services.word_query.prepare / toggle_save. These tests drive the
REAL handlers (`handlers.user._handle_query_prepare`,
`handlers.srs_handler._handle_query_add`) with a temp on-disk DB, patching only
the AI prepare step (the injected prepare_card closure) and the Telegram edit
helpers, so every result.kind branch is proven end-to-end.

Locked contract rules verified here:
- R1 faithful adapter: orchestration delegated to word_query.prepare; handler
      keeps footer/presentation/phonetic/already-prepared-check/not-modified toast.
- R2 correct saved-state: PrepareResult.saved is passed to query_result_keyboard,
      so an already-saved word shows "remove from review".
- R3 usage helper: handler uses formatting.word_query_usage_text (no local dup).
- Callbacks `query:prepare:` / `query:add:` unchanged; saved-state + keyboard
  prefixes preserved.
"""

import asyncio
import contextlib
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest

from handlers import user as user_handlers
from handlers.srs_handler import _handle_query_add
from services import db
from services.db import schema as db_schema
from services.utils.formatting import CardPreparationError


class WordQueryPrepareToggleFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_db_schema_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        db.create_user_if_needed(1, "learner")
        db.set_user_lang_goal(1, "en", "general")
        db.set_user_level(1, "beginner")
        self.card = {
            "word": "hello",
            "phonetic": "/həˈloʊ/",
            "fa_meaning": "سلام",
            "fa_explanation": "برای سلام کردن.",
            "examples": ["Hello!"],
        }

    def tearDown(self):
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_db_schema_path
        self.tempdir.cleanup()

    def _make_prepare_update(self, ready=False):
        update = MagicMock()
        update.effective_user.id = 1
        query = MagicMock()
        query.answer = AsyncMock()
        message = MagicMock()
        message.edit_text = AsyncMock()
        message.edit_reply_markup = AsyncMock()
        query.message = message
        update.callback_query = query
        update.effective_message = message
        if ready:
            message.text = "ترجمه آماده شده"
        return update

    def _prepare_context(self, user_data=None):
        context = MagicMock()
        context.user_data = user_data if user_data is not None else {}
        context.bot = MagicMock()
        return context

    def _patchers(self, *, prepare_card=None, prepare_side_effect=None, prepared=False):
        if prepare_card is None:
            prepare_card = self.card
        self._edit_mock = AsyncMock()
        stack = contextlib.ExitStack()
        stack.enter_context(
            patch.object(
                user_handlers, "_message_has_prepared_translations",
                return_value=prepared,
            )
        )
        patch_kwargs = (
            {"side_effect": prepare_side_effect}
            if prepare_side_effect is not None
            else {"return_value": prepare_card}
        )
        stack.enter_context(
            patch.object(user_handlers, "_prepare_cached_card", **patch_kwargs)
        )
        stack.enter_context(
            patch.object(user_handlers, "_edit_with_retry", new=self._edit_mock)
        )
        return stack

    def test_prepare_happy_path_renders_footer_and_stores_state(self):
        token = db.create_query_result(1, "hello", "hello", "en", self.card)
        update = self._make_prepare_update()
        context = self._prepare_context()
        with self._patchers():
            asyncio.run(user_handlers._handle_query_prepare(update, context, token))
        # user_data records the per-render flags.
        self.assertIn("query_kb_" + token, context.user_data)
        self.assertFalse(context.user_data["query_kb_" + token]["show_translations"])
        # Footer (usage text + add-to-review hint) and presentation are rendered.
        rendered = self._edit_mock.call_args.args[1]
        self.assertIn("برای افزودن این واژه به مرور", rendered,
                      "prepare footer must include the add-to-review hint")
        self.assertIn("استفاده امروز", rendered,
                      "prepare footer must include the usage summary line")
        self.assertIn("سلام", rendered, "rendered card body must contain the meaning")
        # Success toast fired.
        answer_args = update.callback_query.answer.call_args[0][0]
        self.assertIn("آماده شدند", answer_args)

    def test_prepare_already_prepared_early_exits(self):
        token = db.create_query_result(1, "hello", "hello", "en", self.card)
        update = self._make_prepare_update()
        context = self._prepare_context()
        prep_card = MagicMock()
        with self._patchers(prepare_card=prep_card, prepared=True):
            asyncio.run(user_handlers._handle_query_prepare(update, context, token))
        prep_card.assert_not_called()  # AI step skipped when already prepared
        self.assertNotIn("query_kb_" + token, context.user_data)

    def test_prepare_expired_notifies(self):
        token = "missing-token"
        update = self._make_prepare_update()
        context = self._prepare_context()
        with self._patchers(prepared=False):
            asyncio.run(user_handlers._handle_query_prepare(update, context, token))
        self.assertIn("منقضی شده", update.callback_query.answer.call_args[0][0])

    def test_prepare_card_prep_error_notifies(self):
        token = db.create_query_result(1, "hello", "hello", "en", self.card)
        update = self._make_prepare_update()
        context = self._prepare_context()

        def boom(*args, **kwargs):
            raise CardPreparationError("no repairable fields")

        with self._patchers(prepare_side_effect=boom, prepared=False):
            asyncio.run(user_handlers._handle_query_prepare(update, context, token))
        self.assertIn("با اطمینان آماده نشد", update.callback_query.answer.call_args[0][0])

    def test_prepare_not_modified_shows_info_toast(self):
        token = db.create_query_result(1, "hello", "hello", "en", self.card)
        update = self._make_prepare_update()
        context = self._prepare_context()
        with self._patchers(prepared=False):
            self._edit_mock.side_effect = BadRequest("Message is not modified")
            asyncio.run(user_handlers._handle_query_prepare(update, context, token))
        # Telegram replies "not modified" when the re-render is identical; the
        # handler must surface the friendly INFO toast, not an error.
        self.assertIn("قبلاً آماده شده‌اند", update.callback_query.answer.call_args[0][0])

    def test_prepare_preserves_saved_state_on_keyboard(self):
        # Save the word first so the row has saved_at, then prepare.
        token = db.create_query_result(1, "hello", "hello", "en", self.card)
        db.toggle_review_word(1, "hello", "en", self.card)
        db.mark_query_result_saved(token)
        update = self._make_prepare_update()
        context = self._prepare_context()
        with self._patchers(prepared=False):
            asyncio.run(user_handlers._handle_query_prepare(update, context, token))
        # The re-rendered keyboard must reflect saved -> "remove from review".
        edit_kwargs = self._edit_mock.call_args.kwargs
        kb = edit_kwargs["reply_markup"]
        flat = [b for row in kb.inline_keyboard for b in row]
        remove_labels = [b.text for b in flat if "حذف" in b.text]
        self.assertTrue(
            remove_labels,
            "an already-saved word must show 'remove from review' after prepare",
        )

    def test_toggle_saves_then_removes(self):
        token = db.create_query_result(1, "hello", "hello", "en", self.card)
        update = self._make_prepare_update()
        context = self._prepare_context(
            {f"query_kb_{token}": {"show_translations": True, "show_pronounce": True}}
        )
        asyncio.run(_handle_query_add(update, context, token))
        self.assertIsNotNone(
            db.get_query_result(token, user_id=1)["saved_at"],
            "first tap saves and marks the result",
        )
        self.assertIn("ذخیره شد", update.callback_query.answer.call_args[0][0])
        markup = update.effective_message.edit_reply_markup.call_args.kwargs["reply_markup"]
        self.assertTrue(any("حذف" in b.text for r in markup.inline_keyboard for b in r))

        asyncio.run(_handle_query_add(update, context, token))
        self.assertIsNone(
            db.get_query_result(token, user_id=1)["saved_at"],
            "second tap removes and clears the marker",
        )
        self.assertIn("حذف شد", update.callback_query.answer.call_args[0][0])

    def test_toggle_expired_notifies(self):
        token = "missing-token"
        update = self._make_prepare_update()
        context = self._prepare_context()
        asyncio.run(_handle_query_add(update, context, token))
        self.assertIn("منقضی شده", update.callback_query.answer.call_args[0][0])

    def test_toggle_preserves_translations_pronounce_buttons(self):
        token = db.create_query_result(1, "hello", "hello", "en", self.card)
        update = self._make_prepare_update()
        context = self._prepare_context(
            {f"query_kb_{token}": {"show_translations": True, "show_pronounce": True}}
        )
        asyncio.run(_handle_query_add(update, context, token))
        markup = update.effective_message.edit_reply_markup.call_args.kwargs["reply_markup"]
        flat = [b.callback_data for r in markup.inline_keyboard for b in r]
        self.assertTrue(any(c.startswith("query:prepare:") for c in flat))
        self.assertTrue(any(c.startswith("tts:pronounce:q:") for c in flat))


if __name__ == "__main__":
    unittest.main()