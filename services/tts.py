"""Edge TTS pronunciation for vocabulary cards."""

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

import edge_tts

from config.catalog import LANGUAGES

_TTS_CACHE_DIR = Path("tts_cache")

#: Default Edge TTS voice per language lives on each catalog LanguageOption
#: (config/catalog.py). This is the sole voice source; adding a language needs a
#: single catalog edit. ``fa`` (Persian) is the *interface* language, not a
#: learning target, so it is intentionally absent from LANGUAGES and handled as
#: an explicit exception here.
_UI_VOICE_FA = "fa-IR-DilaraNeural"
assert _UI_VOICE_FA, "Persian (fa) TTS voice must be non-empty"

_VOICES: dict[str, dict[str, str]] = {}
_VOICES_LOADED = False

# Per-key async locks for pronounce() to prevent concurrent writes to the same
# cache file (ticket #4 tts-race). Key is "lang:normalized_word".
# Bounded to prevent unbounded growth on long uptime: old idle locks are
# evicted when the map exceeds _MAX_TTS_LOCKS.
_TTS_LOCKS: dict[str, asyncio.Lock] = {}
_TTS_LOCKS_LOCK = asyncio.Lock()
_MAX_TTS_LOCKS = 2000


def voice_for(lang: str) -> str:
    """Return the default Edge TTS voice for a language code.

    Sources the canonical catalog voice for each learning language; falls back
    to English for unknown codes. Persian (``fa``) is a documented special case
    because it is the interface language, not a learning target.
    """
    option = LANGUAGES.get(lang)
    if option is not None and option.voice:
        return option.voice
    if lang == "fa":
        return _UI_VOICE_FA
    return LANGUAGES["en"].voice


async def _ensure_voices():
    global _VOICES, _VOICES_LOADED
    if _VOICES_LOADED:
        return
    codes = set(LANGUAGES) | {"fa"}
    raw = await edge_tts.list_voices()
    for v in raw:
        c = v["Locale"][:2]
        if c in codes:
            _VOICES.setdefault(c, {})[v["ShortName"]] = v.get("Gender", "Unknown")
    _VOICES_LOADED = True


def _default_voice(lang: str) -> str:
    pool = _VOICES.get(lang)
    if not pool:
        return voice_for(lang)
    preferred = voice_for(lang)
    if preferred in pool:
        return preferred
    return next(iter(pool))


def normalize_tts_text(text: str) -> str:
    """Normalize whitespace for TTS key/caption (single source)."""
    return " ".join((text or "").split())


def tts_caption(text: str) -> str:
    """Exact spoken text, whitespace-normalized, truncated to 1024 with …."""
    norm = normalize_tts_text(text)
    if len(norm) > 1024:
        return norm[:1023] + "…"
    return norm


def tts_cache_key(text: str, lang: str) -> str:
    """Stable dedup key: lang + normalized+casefolded text."""
    norm = " ".join((text or "").split()).casefold()
    return f"{lang}:{norm}"


def _slugify(text: str, max_len: int = 60) -> str:
    import re
    norm = normalize_tts_text(text)
    # keep alnum, replace others with _
    slug = re.sub(r"[^A-Za-z0-9]+", "_", norm).strip("_").lower()
    if not slug:
        slug = "tts"
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("_")
    return slug


def tts_filename(text: str, lang: str, now: object | None = None) -> str:
    """Filename: time_lang_slug_hash.mp3  e.g. 20260901-143022_en_hello_a3f1.mp3"""
    import datetime
    dt = now
    if dt is None:
        from config import APP_TZ
        dt = datetime.datetime.now(APP_TZ)
    time_part = dt.strftime("%Y%m%d-%H%M%S")
    slug = _slugify(text, 60)
    h = hashlib.sha256(tts_cache_key(text, lang).encode()).hexdigest()[:4]
    return f"{time_part}_{lang}_{slug}_{h}.mp3"


def _cache_path(word: str, lang: str) -> Path:
    _TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    normalized = " ".join(word.split()).casefold()
    key = hashlib.sha256(f"{lang}:{normalized}".encode()).hexdigest()[:16]
    return _TTS_CACHE_DIR / f"{key}.mp3"


def _tts_lock_key(word: str, lang: str) -> str:
    normalized = " ".join(word.split()).casefold()
    return f"{lang}:{normalized}"


async def _get_tts_lock(key: str) -> asyncio.Lock:
    async with _TTS_LOCKS_LOCK:
        lock = _TTS_LOCKS.get(key)
        if lock is None:
            # Bounded eviction: only idle locks are evicted. If all locks
            # are held, skip eviction and let the map grow temporarily —
            # per-key serialization matters more than a strict cap.
            if len(_TTS_LOCKS) >= _MAX_TTS_LOCKS:
                for k, lk in list(_TTS_LOCKS.items()):
                    if not lk.locked():
                        del _TTS_LOCKS[k]
                        if len(_TTS_LOCKS) < _MAX_TTS_LOCKS:
                            break
            lock = asyncio.Lock()
            _TTS_LOCKS[key] = lock
        return lock


async def pronounce(word: str, lang: str) -> Path:
    path = _cache_path(word, lang)
    if path.exists():
        return path
    key = _tts_lock_key(word, lang)
    lock = await _get_tts_lock(key)
    async with lock:
        if path.exists():
            return path
        await _ensure_voices()
        voice = _default_voice(lang)
        communicate = edge_tts.Communicate(word, voice)
        # Atomic write: save to temp file in same dir then replace
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp", dir=str(path.parent), prefix=path.stem + "_"
        )
        os.close(tmp_fd)
        try:
            await communicate.save(tmp_path)
            os.replace(tmp_path, str(path))
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
        return path
