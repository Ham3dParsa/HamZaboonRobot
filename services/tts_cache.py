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
# T3 (plan-retention R5): file-cache retention bounds. Rows whose last_used_at
# is older than _UNUSED_DAYS are evicted (DB row + mp3 file together); above
# _MAX_BYTES the oldest-used rows evict until under the cap. A miss simply
# regenerates via Edge TTS, so eviction loses nothing.
_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB — "low GBs" per locked ticket T3
_UNUSED_DAYS = 90  # per locked plan-retention R5 (older-than-90d eviction)
_MP3_DIR = Path("tts_cache")  # mirrors services/tts.py::_TTS_CACHE_DIR
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


def _mp3_path_for_key(cache_key: str) -> Path:
    """Mp3 file for a cache key — same derivation as services/tts._cache_path.

    Duplicated (not imported) so this module stays import-light for
    ``to_thread`` use: ``sha256(cache_key)[:16].mp3`` under the cache dir.
    """
    import hashlib

    key = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
    return _MP3_DIR / f"{key}.mp3"


def _delete_row_and_file(cache_key: str) -> None:
    """Delete one DB row + its mp3 file + LRU entry together (never one alone)."""
    with _DB_LOCK:
        conn = sqlite3.connect(_db_path(), timeout=10)
        try:
            conn.execute("DELETE FROM tts_cache WHERE cache_key=?", (cache_key,))
            conn.commit()
        finally:
            conn.close()
    with _lru_lock:
        _lru.pop(cache_key, None)
    try:
        _mp3_path_for_key(cache_key).unlink(missing_ok=True)
    except OSError:
        logger.warning("tts_cache mp3 unlink failed key=%r", cache_key, exc_info=True)


def purge_tts_cache(
    *,
    batch: int = 500,
    max_bytes: int = _MAX_BYTES,
    unused_days: int = _UNUSED_DAYS,
) -> dict[str, int]:
    """Evict stale/over-cap TTS file_id cache rows (T3, plan-retention R5).

    Pass 1 deletes rows with ``last_used_at`` older than ``unused_days``
    (default 90); pass 2 evicts oldest-used rows while mp3 files on disk
    exceed ``max_bytes`` (default 2 GiB). Each eviction removes the DB row,
    the mp3 file, and the LRU entry together. Pass 1 selects in ``batch``-sized
    chunks and each eviction deletes its DB row in its own short autocommit
    transaction; idempotent; a miss regenerates via Edge TTS.
    Returns ``{"expired": n, "over_cap": m}``. Function only — the nightly
    job in services/retention.py is the sole scheduler caller.
    """
    _ensure_db()
    batch = max(1, int(batch))
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=unused_days)
    ).isoformat()
    counts = {"expired": 0, "over_cap": 0}
    while True:
        with _DB_LOCK:
            conn = sqlite3.connect(_db_path(), timeout=10)
            try:
                rows = conn.execute(
                    "SELECT cache_key FROM tts_cache WHERE last_used_at < ? "
                    "ORDER BY last_used_at ASC LIMIT ?",
                    (cutoff, batch),
                ).fetchall()
                keys = [r[0] for r in rows]
            finally:
                conn.close()
        if not keys:
            break
        for key in keys:
            _delete_row_and_file(key)
        counts["expired"] += len(keys)
        if len(keys) < batch:
            break
    # Pass 2: over-cap eviction, oldest-used first. LIMIT-chunked (A1) so
    # per-query rows and memory stay O(batch) regardless of table size:
    # chunk-scan the total, then evict the oldest chunk until under cap.
    while True:
        total = 0
        offset = 0
        while True:
            with _DB_LOCK:
                conn = sqlite3.connect(_db_path(), timeout=10)
                try:
                    rows = conn.execute(
                        "SELECT cache_key FROM tts_cache ORDER BY last_used_at ASC "
                        "LIMIT ? OFFSET ?",
                        (batch, offset),
                    ).fetchall()
                    keys = [r[0] for r in rows]
                finally:
                    conn.close()
            if not keys:
                break
            for key in keys:
                try:
                    total += _mp3_path_for_key(key).stat().st_size
                except OSError:
                    continue
            if len(keys) < batch:
                break
            offset += batch
        if total <= max_bytes:
            break
        with _DB_LOCK:
            conn = sqlite3.connect(_db_path(), timeout=10)
            try:
                rows = conn.execute(
                    "SELECT cache_key FROM tts_cache ORDER BY last_used_at ASC LIMIT ?",
                    (batch,),
                ).fetchall()
                victims = [r[0] for r in rows]
            finally:
                conn.close()
        if not victims:
            break
        for victim in victims:
            try:
                size = _mp3_path_for_key(victim).stat().st_size
            except OSError:
                size = 0
            _delete_row_and_file(victim)
            counts["over_cap"] += 1
            total -= size
            if total <= max_bytes:
                break
    if counts["expired"] or counts["over_cap"]:
        logger.info("purge_tts_cache evicted=%s", counts)
    return counts
