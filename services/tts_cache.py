"""TTS file_id cache — separate tts_cache.db + in-memory LRU."""
import datetime
import logging
import os
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path

from config import TTS_CACHE_DB_PATH

logger = logging.getLogger(__name__)

_LRU_CAP = 3000
_lru: OrderedDict[str, dict] = OrderedDict()
_lru_lock = threading.Lock()
_DB_LOCK = threading.Lock()
_DB_INIT_LOCK = threading.Lock()
_DB_INITIALIZED = False


def _db_path() -> str:
    return TTS_CACHE_DB_PATH


def init_tts_cache_db(path: str | None = None) -> None:
    global _DB_INITIALIZED
    p = path or _db_path()
    conn = sqlite3.connect(p, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS tts_cache (
            cache_key TEXT PRIMARY KEY,
            lang TEXT NOT NULL,
            text TEXT NOT NULL,
            file_id TEXT NOT NULL,
            file_unique_id TEXT NOT NULL,
            channel_message_id INTEGER,
            created_at TEXT NOT NULL,
            last_used_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS tts_cache_lang_idx ON tts_cache(lang)")
        conn.commit()
        _DB_INITIALIZED = True
    finally:
        conn.close()


def _ensure_db(path: str | None = None):
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    with _DB_INIT_LOCK:
        if _DB_INITIALIZED:
            return
        p = path or _db_path()
        if not os.path.exists(p):
            init_tts_cache_db(p)
        else:
            # Ensure schema exists even if file already present (e.g. empty file)
            init_tts_cache_db(p)


def get_cached(cache_key: str) -> dict | None:
    with _lru_lock:
        if cache_key in _lru:
            _lru.move_to_end(cache_key)
            logger.debug("tts_cache LRU hit key=%r", cache_key)
            return dict(_lru[cache_key])
    logger.debug("tts_cache LRU miss key=%r", cache_key)
    _ensure_db()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with _DB_LOCK:
            conn = sqlite3.connect(_db_path(), timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute("SELECT * FROM tts_cache WHERE cache_key=?", (cache_key,)).fetchone()
                if not row:
                    logger.debug("tts_cache DB miss key=%r", cache_key)
                    return None
                logger.debug("tts_cache DB hit key=%r", cache_key)
                try:
                    conn.execute("UPDATE tts_cache SET last_used_at=? WHERE cache_key=?", (now, cache_key))
                    conn.commit()
                except sqlite3.OperationalError:
                    logger.warning("tts_cache last_used_at update failed for %r", cache_key, exc_info=True)
                except Exception:
                    logger.warning("tts_cache last_used_at update failed for %r", cache_key, exc_info=True)
                d = dict(row)
                d["last_used_at"] = now
                with _lru_lock:
                    _lru[cache_key] = d
                    _lru.move_to_end(cache_key)
                    if len(_lru) > _LRU_CAP:
                        _lru.popitem(last=False)
                return d
            finally:
                conn.close()
    except sqlite3.OperationalError:
        logger.warning("tts_cache get_cached OperationalError key=%r", cache_key, exc_info=True)
        return None

def put_cached(cache_key: str, lang: str, text: str, file_id: str, file_unique_id: str, channel_message_id: int | None = None) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _ensure_db()
    with _DB_LOCK:
        conn = sqlite3.connect(_db_path(), timeout=10)
        try:
            conn.execute("INSERT OR REPLACE INTO tts_cache(cache_key, lang, text, file_id, file_unique_id, channel_message_id, created_at, last_used_at) VALUES (?,?,?,?,?,?,?,?)",
                         (cache_key, lang, text, file_id, file_unique_id, channel_message_id, now, now))
            conn.commit()
        finally:
            conn.close()
    d = {"cache_key": cache_key, "lang": lang, "text": text, "file_id": file_id, "file_unique_id": file_unique_id, "channel_message_id": channel_message_id, "created_at": now, "last_used_at": now}
    with _lru_lock:
        _lru[cache_key] = d
        _lru.move_to_end(cache_key)
        if len(_lru) > _LRU_CAP:
            _lru.popitem(last=False)

def clear_lru():
    with _lru_lock:
        _lru.clear()
