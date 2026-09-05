"""TTS file_id cache — separate tts_cache.db + in-memory LRU."""
import datetime
import logging
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path

from config import TTS_CACHE_DB_PATH
from services.tts import _TTS_CACHE_DIR, _mp3_path_for_cache_key

logger = logging.getLogger(__name__)

_LRU_CAP = 3000
# T3 (plan-retention R5): file-cache retention bounds. Rows whose last_used_at
# is older than _UNUSED_DAYS are evicted (DB row + mp3 file together); above
# _MAX_BYTES the oldest-used rows evict until under the cap. A miss simply
# regenerates via Edge TTS, so eviction loses nothing.
_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB — "low GBs" per locked ticket T3
_UNUSED_DAYS = 90  # per locked plan-retention R5 (older-than-90d eviction)
# Patchable override for tests (rebind to a tmp dir); production identity is
# the single source services/tts.py::_TTS_CACHE_DIR — never a second copy of
# the path or the hash derivation (see _mp3_path_for_key).
_MP3_DIR = _TTS_CACHE_DIR
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
    """Mp3 file for a cache key — delegates to services/tts (single source).

    ``_MP3_DIR`` is a test-only rebindable override (production: the shared
    ``_TTS_CACHE_DIR`` object); the hash derivation itself always lives in
    ``services.tts._mp3_path_for_cache_key``. The module stays import-light
    for ``to_thread`` use apart from this one shared import (no edge_tts
    calls at import time).
    """
    return _mp3_path_for_cache_key(cache_key, base_dir=_MP3_DIR)


def _delete_rows_and_files(cache_keys: list[str]) -> None:
    """Delete DB rows in one short txn, then unlink files + drop LRU entries.

    One transaction per chunk (never one connection per key); file unlinks
    stay outside the txn so a missing file can never roll back the deletes.
    """
    if not cache_keys:
        return
    with _DB_LOCK:
        conn = sqlite3.connect(_db_path(), timeout=10)
        try:
            placeholders = ",".join("?" * len(cache_keys))
            conn.execute(
                f"DELETE FROM tts_cache WHERE cache_key IN ({placeholders})",
                cache_keys,
            )
            conn.commit()
        finally:
            conn.close()
    with _lru_lock:
        for cache_key in cache_keys:
            _lru.pop(cache_key, None)
    for cache_key in cache_keys:
        try:
            _mp3_path_for_key(cache_key).unlink(missing_ok=True)
        except OSError:
            logger.warning("tts_cache mp3 unlink failed key=%r", cache_key, exc_info=True)


def purge_tts_cache(
    *,
    batch: int = 500,
    max_bytes: int = _MAX_BYTES,
    unused_days: int = _UNUSED_DAYS,
    deadline: float | None = None,
) -> dict[str, int]:
    """Evict stale/over-cap TTS file_id cache rows (T3, plan-retention R5).

    Pass 1 deletes rows with ``last_used_at`` older than ``unused_days``
    (default 90); pass 2 evicts oldest-used rows while mp3 files on disk
    exceed ``max_bytes`` (default 2 GiB). Each eviction removes the DB row,
    the mp3 file, and the LRU entry together. Pass 1 selects in ``batch``-sized
    chunks with one short transaction per chunk delete; pass 2 sizes every
    file in a single ordered key pass (no OFFSET pagination) and evicts the
    oldest rows in chunked transactions until under the cap. Idempotent; a
    miss regenerates via Edge TTS. Stops batching at ``deadline``
    (monotonic) when set so a backlog defers the remainder.
    Only ``[:16].mp3`` cache files written via ``services/tts._cache_path``
    are swept — ``tts_filename()`` display names have no production writer
    into this dir, so nothing else can accumulate here.
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
        if deadline is not None and time.monotonic() >= deadline:
            break
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
        _delete_rows_and_files(keys)
        counts["expired"] += len(keys)
        if len(keys) < batch:
            break
    # Pass 2: over-cap eviction, oldest-used first. One ordered key pass sizes
    # every file (no LIMIT/OFFSET scan), then the oldest rows evict in
    # chunked single transactions until under the cap.
    if deadline is None or time.monotonic() < deadline:
        with _DB_LOCK:
            conn = sqlite3.connect(_db_path(), timeout=10)
            try:
                rows = conn.execute(
                    "SELECT cache_key FROM tts_cache "
                    "ORDER BY last_used_at ASC, cache_key ASC"
                ).fetchall()
                ordered = [r[0] for r in rows]
            finally:
                conn.close()
        sizes: dict[str, int] = {}
        total = 0
        for key in ordered:
            try:
                size = _mp3_path_for_key(key).stat().st_size
            except OSError:
                size = 0
            sizes[key] = size
            total += size
        over = total - max_bytes
        if over > 0:
            freed = 0
            victims: list[str] = []
            for key in ordered:
                victims.append(key)
                freed += sizes[key]
                if freed >= over:
                    break
            for i in range(0, len(victims), batch):
                if deadline is not None and time.monotonic() >= deadline:
                    break
                chunk = victims[i:i + batch]
                _delete_rows_and_files(chunk)
                counts["over_cap"] += len(chunk)
    if counts["expired"] or counts["over_cap"]:
        logger.info("purge_tts_cache evicted=%s", counts)
    return counts
