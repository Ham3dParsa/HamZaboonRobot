"""Integration coverage for the removed legacy daily-card TTS action."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from config.keyboards import query_result_keyboard
from services import db
from services.db import schema as db_schema


class TtsDailyActionRemovalTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import bot

        self.offline_patcher = patch.object(bot, "_telegram_offline", False)
        self.offline_patcher.start()
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db_path = db.DB_PATH
        self.previous_schema_db_path = db_schema.DB_PATH
        db.DB_PATH = os.path.join(self.tempdir.name, "test.sqlite")
        db_schema.DB_PATH = db.DB_PATH
        db.init_db()
        db.create_user_if_needed(1, "learner")
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE users SET onboarded=1, plan='gold' WHERE user_id=1"
            )
            conn.commit()

    def tearDown(self):
        self.offline_patcher.stop()
        db.DB_PATH = self.previous_db_path
        db_schema.DB_PATH = self.previous_schema_db_path
        self.tempdir.cleanup()

    async def test_legacy_daily_tts_action_is_rejected_without_db_access(self):
        from bot import callback_router
        import bot

        query = MagicMock()
        query.data = "tts:pronounce:d:1:2026-07-12:0"
        query.answer = AsyncMock()
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        context = MagicMock()
        context.user_data = {}

        with (
            patch.object(
                bot.db,
                "get_user",
                side_effect=AssertionError("legacy TTS must not read the user"),
            ) as get_user,
            patch.object(
                bot.db,
                "get_setting",
                side_effect=AssertionError("legacy TTS must not read settings"),
            ) as get_setting,
        ):
            await callback_router(update, context)

        query.answer.assert_awaited_once_with(
            "دکمه نامعتبر است.", show_alert=True
        )
        get_user.assert_not_called()
        get_setting.assert_not_called()
        with db.get_conn() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_words").fetchone()[0],
                0,
            )

    async def test_query_tts_action_still_sends_voice(self):
        from bot import callback_router
        import bot

        token = db.create_query_result(
            1,
            "hello",
            "hello",
            "en",
            {"word": "hello"},
        )
        voice_path = Path(self.tempdir.name) / "voice.mp3"
        voice_path.write_bytes(b"voice")
        markup = query_result_keyboard(token)
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        callback_data = next(
            callback for callback in callbacks if callback.startswith("tts:pronounce:q:")
        )
        self.assertEqual(callback_data, "tts:pronounce:q:" + token)
        update, context = self._callback(callback_data)

        with (
            patch.object(bot.tts, "pronounce", AsyncMock(return_value=voice_path)) as pronounce,
            patch("services.tts_service._send_voice", AsyncMock()) as send_voice,
        ):
            await callback_router(update, context)

        pronounce.assert_awaited_once_with("hello", "en")
        send_voice.assert_awaited_once()

    async def test_saved_word_tts_action_still_sends_voice(self):
        from bot import callback_router
        import bot

        db.add_saved_word(1, "world", "en", {"word": "world"})
        word_id = db.get_saved_word(1, user_id=1)["id"]
        voice_path = Path(self.tempdir.name) / "voice.mp3"
        voice_path.write_bytes(b"voice")
        update, context = self._callback(f"tts:pronounce:s:1:{word_id}")

        with (
            patch.object(bot.tts, "pronounce", AsyncMock(return_value=voice_path)) as pronounce,
            patch("services.tts_service._send_voice", AsyncMock()) as send_voice,
        ):
            await callback_router(update, context)

        pronounce.assert_awaited_once_with("world", "en")
        send_voice.assert_awaited_once()

    async def test_free_user_tts_delivers_voice(self):
        """Pronounce is always available to every plan (#390): a free user must
        receive voice, not be blocked by a plan gate (handler-level delivery
        coverage, not just button rendering)."""
        from bot import callback_router
        import bot

        with db.get_conn() as conn:
            conn.execute("UPDATE users SET plan='free' WHERE user_id=1")
            conn.commit()

        db.add_saved_word(1, "world", "en", {"word": "world"})
        word_id = db.get_saved_word(1, user_id=1)["id"]
        voice_path = Path(self.tempdir.name) / "voice.mp3"
        voice_path.write_bytes(b"voice")
        update, context = self._callback(f"tts:pronounce:s:1:{word_id}")

        with (
            patch.object(bot.tts, "pronounce", AsyncMock(return_value=voice_path)) as pronounce,
            patch("services.tts_service._send_voice", AsyncMock()) as send_voice,
        ):
            await callback_router(update, context)

        pronounce.assert_awaited_once_with("world", "en")
        send_voice.assert_awaited_once()

    @staticmethod
    def _callback(data: str):
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.message.message_id = 10
        update = MagicMock()
        update.effective_user.id = 1
        update.effective_chat.id = 1
        update.callback_query = query
        context = MagicMock()
        context.user_data = {}
        context.bot = MagicMock()
        return update, context


if __name__ == "__main__":
    unittest.main()
