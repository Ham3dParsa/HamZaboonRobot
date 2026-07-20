"""Edge TTS pronunciation for vocabulary cards."""

import hashlib
from pathlib import Path

import edge_tts

from config.catalog import LANGUAGES

_TTS_CACHE_DIR = Path("tts_cache")

_FALLBACK_VOICES = {
    "en": "en-US-JennyNeural",
    "es": "es-ES-ElviraNeural",
    "ar": "ar-SA-ZariyahNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "tr": "tr-TR-EmelNeural",
    "he": "he-IL-HilaNeural",
    "fa": "fa-IR-DilaraNeural",
}

_VOICES: dict[str, dict[str, str]] = {}
_VOICES_LOADED = False


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
        return _FALLBACK_VOICES.get(lang, "en-US-JennyNeural")
    fallback = _FALLBACK_VOICES.get(lang)
    if fallback and fallback in pool:
        return fallback
    return next(iter(pool))


def _cache_path(word: str, lang: str) -> Path:
    _TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    normalized = " ".join(word.split()).casefold()
    key = hashlib.sha256(f"{lang}:{normalized}".encode()).hexdigest()[:16]
    return _TTS_CACHE_DIR / f"{key}.mp3"


async def pronounce(word: str, lang: str) -> Path:
    path = _cache_path(word, lang)
    if path.exists():
        return path
    await _ensure_voices()
    voice = _default_voice(lang)
    communicate = edge_tts.Communicate(word, voice)
    await communicate.save(str(path))
    return path
