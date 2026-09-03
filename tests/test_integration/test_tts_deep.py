"""Phase-01 TTS deep: service owns lock+cache+channel+fallback.

- concurrent same-key speak() from 2 users -> 1 channel upload
- Forbidden on channel -> direct fallback still delivers
- bot.py delegates (no per-key lock import, no direct tts_cache DB calls)
"""
import asyncio
import pathlib
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestTTSSpeakConcurrency(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_same_key_single_channel_upload(self):
        from services import tts_service as svc

        fake_path = MagicMock()
        fake_path.read_bytes.return_value = b"voice-bytes"
        channel_messages = []
        user_sends = []
        cache_state = {}

        async def fake_pronounce(word, lang):
            await asyncio.sleep(0.05)
            return fake_path

        async def fake_cache_get(key):
            return cache_state.get(key)

        put_calls = []

        async def fake_cache_put(*args):
            put_calls.append(args)
            cache_state[args[0]] = {"file_id": args[3]}

        async def fake_send(bot, chat_id, **kwargs):
            # route by chat_id: channel vs user
            if chat_id == -100123:
                channel_messages.append(chat_id)
                m = MagicMock()
                m.voice.file_id = "FID123"
                m.voice.file_unique_id = "FUID123"
                m.message_id = 7
                # slow channel upload widens the race window
                await asyncio.sleep(0.05)
                return m
            user_sends.append(chat_id)
            return MagicMock()

        with (
            patch.object(svc, "resolve_tts_cache_chat_id", return_value=-100123),
            patch.object(svc, "_cache_get", side_effect=fake_cache_get),
            patch.object(svc, "_cache_put", side_effect=fake_cache_put),
            patch("services.tts.pronounce", side_effect=fake_pronounce),
            patch("services.tts_service._send_media_with_retry", side_effect=fake_send),
        ):
            bot = MagicMock()
            r = await asyncio.gather(
                svc.speak("hello", "en", bot=bot, chat_id=111, reply_to=1),
                svc.speak("hello", "en", bot=bot, chat_id=222, reply_to=2),
            )
        self.assertEqual(len(channel_messages), 1, f"expected 1 channel upload, got {channel_messages}")
        self.assertEqual(len(user_sends), 2)
        self.assertTrue(all(k in ("channel_upload", "file_id_hit", "file_id_hit_after") for k in r))

    async def test_channel_forbidden_falls_back_direct(self):
        from services import tts_service as svc
        from telegram.error import Forbidden

        fake_path = MagicMock()
        fake_path.read_bytes.return_value = b"voice-bytes"
        user_sends = []

        async def fake_send(bot, chat_id, **kwargs):
            if chat_id == -100123:
                raise Forbidden("bot is not a member")
            user_sends.append(chat_id)
            return MagicMock()

        with (
            patch.object(svc, "resolve_tts_cache_chat_id", return_value=-100123),
            patch.object(svc, "_cache_get", return_value=None),
            patch.object(svc, "_cache_put", return_value=None),
            patch("services.tts.pronounce", return_value=fake_path),
            patch("services.tts_service._send_media_with_retry", side_effect=fake_send),
        ):
            kind = await svc.speak("hello", "en", bot=MagicMock(), chat_id=111, reply_to=1)
        self.assertEqual(kind, "direct_fallback")
        self.assertEqual(user_sends, [111])


class TestTTSDelegation(unittest.TestCase):
    def test_bot_delegates_no_lock_no_direct_cache(self):
        text = pathlib.Path("bot.py").read_text(encoding="utf-8")
        self.assertIn("from services.tts_service import handle_callback", text)
        self.assertNotIn("_get_tts_lock", text)
        self.assertNotIn("get_cached", text)
        self.assertNotIn("put_cached", text)
        self.assertNotIn("from services.tts_cache import", text)

    def test_no_direct_tts_cache_db_outside_owner(self):
        import re

        allowed = {"services/tts_service.py", "services/tts_cache.py"}
        offenders = []
        for p in list(pathlib.Path("services").rglob("*.py")) + [
            pathlib.Path("bot.py"),
            pathlib.Path("handlers/admin.py"),
        ]:
            if not p.is_file():
                continue
            posix = p.as_posix()
            if posix in allowed or posix == "services/tts_cache.py":
                continue
            t = p.read_text(encoding="utf-8")
            if re.search(r"(get_cached|put_cached|init_tts_cache_db)", t):
                offenders.append(posix)
        self.assertEqual(offenders, [], f"direct tts_cache DB use outside owner: {offenders}")

    def test_service_uses_unified_media_retry(self):
        text = pathlib.Path("services/tts_service.py").read_text(encoding="utf-8")
        self.assertIn("_send_media_with_retry", text)
        self.assertNotIn("idempotent", text)

    def test_resolve_word_branches(self):
        from services import tts_service as svc

        with (
            patch("services.db.get_query_result", return_value={"word": "hi", "lang": "en"}),
        ):
            w, lang, err = svc.resolve_word("q", ["q", "tok"], 5)
            self.assertEqual((w, lang, err), ("hi", "en", None))
        w, lang, err = svc.resolve_word("q", ["q"], 5)
        self.assertEqual(err, "invalid")
        w, lang, err = svc.resolve_word("s", ["s", "6", "1"], 5)
        self.assertEqual(err, "cross_user")
        w, lang, err = svc.resolve_word("x", ["x"], 5)
        self.assertEqual(err, "invalid")


if __name__ == "__main__":
    unittest.main()
