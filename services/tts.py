"""Edge TTS pronunciation for vocabulary cards."""

import hashlib
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

_VOICES: dict[str, dict[str, str]] = {}
_VOICES_LOADED = False


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
