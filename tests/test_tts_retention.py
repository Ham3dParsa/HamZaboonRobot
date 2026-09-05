"""TTS file_id cache retention (T3, plan-retention R5).

Proves the ticket acceptance set on an isolated tts_cache.db:
  - an entry unused for >90d evicts its DB row AND its mp3 file together;
  - a fresh entry (row + file) survives the same run;
  - deterministic keys (lang + normalized word) still hit after the change;
  - the total-size cap evicts oldest-used entries until under budget.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services import tts, tts_cache


def _old_ts(days: int = 200) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days)
    ).isoformat()


class TtsRetentionCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.prev_db_path = tts_cache.TTS_CACHE_DB_PATH
        self.prev_mp3_dir = tts_cache._MP3_DIR
        self.prev_initialized = tts_cache._DB_INITIALIZED
        tts_cache.TTS_CACHE_DB_PATH = os.path.join(self.tempdir.name, "tts_cache.db")
        tts_cache._MP3_DIR = Path(self.tempdir.name) / "tts_cache"
        tts_cache._DB_INITIALIZED = False
        tts_cache.clear_lru()

    def tearDown(self):
        tts_cache.TTS_CACHE_DB_PATH = self.prev_db_path
        tts_cache._MP3_DIR = self.prev_mp3_dir
        tts_cache._DB_INITIALIZED = self.prev_initialized
        tts_cache.clear_lru()
        self.tempdir.cleanup()

    def _put(self, word, lang, file_id="fid-1", fuid="fuid-1"):
        key = tts.tts_cache_key(word, lang)
        tts_cache.put_cached(key, lang, word, file_id, fuid, None)
        return key

    def _backdate(self, key, days=200):
        conn = sqlite3.connect(tts_cache.TTS_CACHE_DB_PATH, timeout=10)
        try:
            conn.execute(
                "UPDATE tts_cache SET last_used_at=? WHERE cache_key=?",
                (_old_ts(days), key),
            )
            conn.commit()
        finally:
            conn.close()
        tts_cache.clear_lru()

    def _row(self, key):
        conn = sqlite3.connect(tts_cache.TTS_CACHE_DB_PATH, timeout=10)
        try:
            return conn.execute(
                "SELECT * FROM tts_cache WHERE cache_key=?", (key,)
            ).fetchone()
        finally:
            conn.close()

    def test_old_unused_evicts_row_and_file_together(self):
        old_key = self._put("hello", "en", file_id="fid-old")
        self._backdate(old_key)
        old_mp3 = tts_cache._mp3_path_for_key(old_key)
        old_mp3.parent.mkdir(parents=True, exist_ok=True)
        old_mp3.write_bytes(b"old-audio")

        fresh_key = self._put("bonjour", "fr", file_id="fid-fresh")
        fresh_mp3 = tts_cache._mp3_path_for_key(fresh_key)
        fresh_mp3.parent.mkdir(parents=True, exist_ok=True)
        fresh_mp3.write_bytes(b"fresh-audio")

        counts = tts_cache.purge_tts_cache()

        self.assertEqual(counts["expired"], 1)
        self.assertIsNone(self._row(old_key))
        self.assertFalse(old_mp3.exists())
        self.assertIsNotNone(self._row(fresh_key))
        self.assertTrue(fresh_mp3.exists())

    def test_deterministic_keys_still_hit(self):
        key_a = tts.tts_cache_key("  HELLO ", "en")
        key_b = tts.tts_cache_key("hello", "en")
        self.assertEqual(key_a, key_b)
        tts_cache.put_cached(key_a, "en", "hello", "fid-x", "fuid-x", None)
        tts_cache.clear_lru()  # force the DB (not LRU) path
        hit = tts_cache.get_cached(key_b)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["file_id"], "fid-x")

    def test_size_cap_evicts_oldest_used_first(self):
        old_key = self._put("old", "en", file_id="fid-old")
        old_mp3 = tts_cache._mp3_path_for_key(old_key)
        old_mp3.parent.mkdir(parents=True, exist_ok=True)
        old_mp3.write_bytes(b"x" * 100)
        # Make the old row strictly older than the fresh one without
        # tripping the 90d unused rule.
        self._backdate(old_key, days=10)
        fresh_key = self._put("new", "en", file_id="fid-new")
        fresh_mp3 = tts_cache._mp3_path_for_key(fresh_key)
        fresh_mp3.write_bytes(b"y" * 100)

        counts = tts_cache.purge_tts_cache(max_bytes=100)

        self.assertEqual(counts["expired"], 0)
        self.assertEqual(counts["over_cap"], 1)
        self.assertIsNone(self._row(old_key))
        self.assertFalse(old_mp3.exists())
        self.assertIsNotNone(self._row(fresh_key))
        self.assertTrue(fresh_mp3.exists())


if __name__ == "__main__":
    unittest.main()
