import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import tts


class TtsCachePathTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_cache = tts._TTS_CACHE_DIR
        tts._TTS_CACHE_DIR = Path(self.tempdir.name) / "tts_cache"

    def tearDown(self):
        tts._TTS_CACHE_DIR = self.original_cache
        self.tempdir.cleanup()

    def test_cache_path_creates_directory(self):
        path = tts._cache_path("hello", "en")
        self.assertTrue(path.parent.exists())
        self.assertEqual(path.suffix, ".mp3")

    def test_cache_path_normalizes_word(self):
        path_a = tts._cache_path("  Hello  ", "en")
        path_b = tts._cache_path("hello", "en")
        self.assertEqual(path_a, path_b)

    def test_cache_path_differs_by_lang(self):
        path_en = tts._cache_path("hello", "en")
        path_fr = tts._cache_path("hello", "fr")
        self.assertNotEqual(path_en, path_fr)

    def test_cache_path_is_deterministic(self):
        path_a = tts._cache_path("bonjour", "fr")
        path_b = tts._cache_path("bonjour", "fr")
        self.assertEqual(path_a, path_b)


class TtsVoiceSelectionTests(unittest.TestCase):
    def setUp(self):
        tts._VOICES.clear()
        tts._VOICES_LOADED = False

    def tearDown(self):
        tts._VOICES.clear()
        tts._VOICES_LOADED = False

    def test_fallback_when_no_voices_loaded(self):
        voice = tts._default_voice("en")
        self.assertEqual(voice, "en-US-JennyNeural")

    def test_fallback_for_unsupported_language(self):
        voice = tts._default_voice("xx")
        self.assertEqual(voice, "en-US-JennyNeural")

    def test_fallback_picks_configured_voice_when_available(self):
        tts._VOICES["en"] = {"en-US-JennyNeural": "Female", "en-US-TonyNeural": "Male"}
        tts._VOICES_LOADED = True
        voice = tts._default_voice("en")
        self.assertEqual(voice, "en-US-JennyNeural")

    def test_fallback_picks_first_voice_when_configured_not_available(self):
        tts._VOICES["fa"] = {"fa-IR-FaridNeural": "Male"}
        tts._VOICES_LOADED = True
        voice = tts._default_voice("fa")
        self.assertEqual(voice, "fa-IR-FaridNeural")


class TtsPronounceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_cache = tts._TTS_CACHE_DIR
        tts._TTS_CACHE_DIR = Path(self.tempdir.name) / "tts_cache"
        tts._VOICES.clear()
        tts._VOICES_LOADED = False

    def tearDown(self):
        tts._TTS_CACHE_DIR = self.original_cache
        tts._VOICES.clear()
        tts._VOICES_LOADED = False
        self.tempdir.cleanup()

    @patch.object(tts, "_ensure_voices", new_callable=AsyncMock)
    @patch.object(tts.edge_tts, "Communicate")
    def test_pronounce_generates_and_caches(self, mock_comm, mock_ensure):
        async def fake_save(path):
            Path(path).touch()

        mock_instance = MagicMock()
        mock_instance.save = AsyncMock(side_effect=fake_save)
        mock_comm.return_value = mock_instance

        path = asyncio.run(tts.pronounce("hello", "en"))
        self.assertTrue(path.exists())
        mock_ensure.assert_awaited_once()
        mock_instance.save.assert_awaited_once_with(str(path))

    @patch.object(tts, "_ensure_voices", new_callable=AsyncMock)
    @patch.object(tts.edge_tts, "Communicate")
    def test_pronounce_uses_cache_on_second_call(self, mock_comm, mock_ensure):
        async def fake_save(path):
            Path(path).touch()

        mock_instance = MagicMock()
        mock_instance.save = AsyncMock(side_effect=fake_save)
        mock_comm.return_value = mock_instance

        path1 = asyncio.run(tts.pronounce("hello", "en"))
        path2 = asyncio.run(tts.pronounce("hello", "en"))
        self.assertEqual(path1, path2)
        self.assertEqual(mock_instance.save.call_count, 1)

    @patch.object(tts, "_ensure_voices", new_callable=AsyncMock)
    @patch.object(tts.edge_tts, "Communicate")
    def test_pronounce_normalizes_word_for_cache(self, mock_comm, mock_ensure):
        async def fake_save(path):
            Path(path).touch()

        mock_instance = MagicMock()
        mock_instance.save = AsyncMock(side_effect=fake_save)
        mock_comm.return_value = mock_instance

        path1 = asyncio.run(tts.pronounce("  Hello  ", "en"))
        path2 = asyncio.run(tts.pronounce("hello", "en"))
        self.assertEqual(path1, path2)
        self.assertEqual(mock_instance.save.call_count, 1)

    @patch.object(tts, "_ensure_voices", new_callable=AsyncMock)
    @patch.object(tts.edge_tts, "Communicate")
    def test_pronounce_different_words_get_different_cache(self, mock_comm, mock_ensure):
        async def fake_save(path):
            Path(path).touch()

        mock_instance = MagicMock()
        mock_instance.save = AsyncMock(side_effect=fake_save)
        mock_comm.return_value = mock_instance

        path1 = asyncio.run(tts.pronounce("hello", "en"))
        mock_instance.save.reset_mock()
        path2 = asyncio.run(tts.pronounce("world", "en"))
        self.assertNotEqual(path1, path2)
        self.assertEqual(mock_instance.save.call_count, 1)
