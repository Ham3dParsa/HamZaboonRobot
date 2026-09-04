"""Edge TTS pronunciation for vocabulary cards."""

import asyncio
import hashlib
import logging
import os
import tempfile
from pathlib import Path

import edge_tts

from config.catalog import LANGUAGES

logger = logging.getLogger(__name__)

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
_VOICES_EVENT = asyncio.Event()
_VOICES_LOCK = asyncio.Lock()

# NOTE (phase 02 R1): pronounce() is intentionally lock-free. Per-key
# single-flight lives in services/tts_service._SPEAK_LOCKS (the only
# production caller, speak(), holds it). Concurrent same-key DIRECT
# pronounce() calls each issue their own Edge TTS request (accepted
# trade-off); the atomic tmp-write + os.replace only guarantees no torn
# file, not no duplicate upstream spend. Direct callers needing
# single-flight must serialize themselves.


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
    global _VOICES_LOADED
    if _VOICES_LOADED:
        logger.info("tts _ensure_voices cache hit")
        return
    # Deduplicate concurrent warmups via Event+Lock
    if _VOICES_EVENT.is_set():
        return
    async with _VOICES_LOCK:
        if _VOICES_LOADED:
            return
        if _VOICES_EVENT.is_set():
            return
        logger.info("tts _ensure_voices cache miss — fetching voices")
        codes = set(LANGUAGES) | {"fa"}
        try:
            raw = await edge_tts.list_voices()
        except Exception:
            logger.exception("tts _ensure_voices failed to list voices")
            raise
        for v in raw:
            c = v["Locale"][:2]
            if c in codes:
                _VOICES.setdefault(c, {})[v["ShortName"]] = v.get("Gender", "Unknown")
        _VOICES_LOADED = True
        _VOICES_EVENT.set()


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
    # Keep Unicode word characters (\w includes Persian/Arabic letters with UNICODE)
    slug = re.sub(r"[^\w]+", "_", norm, flags=re.UNICODE).strip("_").lower()
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
    h = hashlib.sha256(tts_cache_key(text, lang).encode()).hexdigest()[:8]
    return f"{time_part}_{lang}_{slug}_{h}.mp3"


def _cache_path(word: str, lang: str) -> Path:
    _TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(tts_cache_key(word, lang).encode()).hexdigest()[:16]
    return _TTS_CACHE_DIR / f"{key}.mp3"


_TTS_TIMEOUT_S = 12


async def pronounce(word: str, lang: str) -> Path:
    path = _cache_path(word, lang)
    if path.exists():
        logger.info("tts pronounce cache hit lang=%s word=%r path=%s", lang, word, path)
        return path
    logger.info("tts pronounce cache miss lang=%s word=%r", lang, word)
    # Warm voices first (Event dedup prevents thundering herd)
    try:
        await asyncio.wait_for(_ensure_voices(), timeout=_TTS_TIMEOUT_S)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.warning("tts _ensure_voices timeout/cancel lang=%s word=%r", lang, word, exc_info=True)
        raise
    except Exception:
        logger.exception("tts _ensure_voices failed lang=%s word=%r", lang, word)
        raise
    voice = _default_voice(lang)
    logger.info("tts pronounce generating lang=%s voice=%s word=%r", lang, voice, word)
    communicate = edge_tts.Communicate(word, voice)
    # Atomic write: save to temp file in same dir then replace
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp", dir=str(path.parent), prefix=path.stem + "_"
    )
    os.close(tmp_fd)
    try:
        try:
            await asyncio.wait_for(communicate.save(tmp_path), timeout=_TTS_TIMEOUT_S)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            logger.warning(
                "tts communicate.save timeout/cancel lang=%s voice=%s word=%r",
                lang,
                voice,
                word,
                exc_info=True,
            )
            raise
        except Exception:
            logger.exception(
                "tts communicate.save failed lang=%s voice=%s word=%r",
                lang,
                voice,
                word,
            )
            raise
        os.replace(tmp_path, str(path))
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    return path
