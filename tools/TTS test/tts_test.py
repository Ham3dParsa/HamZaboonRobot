"""Edge TTS test module: pronounce words using voices for catalog-supported languages."""

import argparse
import asyncio
import sys
from pathlib import Path

import edge_tts

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config.catalog import LANGUAGES

_VOICES: dict[str, dict[str, str]] = {}
_VOICES_LOADED = False

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


async def _ensure_voices() -> None:
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


def _default_voice(lang: str, gender: str | None) -> str:
    pool = _VOICES.get(lang)
    if not pool:
        return _FALLBACK_VOICES.get(lang, "en-US-JennyNeural")
    if gender:
        candidates = [n for n, g in pool.items() if g.lower() == gender.lower()]
        if candidates:
            return candidates[0]
    fallback = _FALLBACK_VOICES.get(lang)
    if fallback and fallback in pool:
        return fallback
    return next(iter(pool))


async def supported_languages() -> str:
    await _ensure_voices()
    lines = []
    for code, opt in sorted(LANGUAGES.items()):
        pool = _VOICES.get(code, {})
        genders = sorted(set(pool.values()))
        lines.append(f"  {code:>4s}  {opt.name_fa:16s}  genders={{{','.join(genders)}}}  ({len(pool)} voices)")
    pool = _VOICES.get("fa", {})
    genders = sorted(set(pool.values()))
    lines.append(f"  {'fa':>4s}  {'فارسی':16s}  genders={{{','.join(genders)}}}  ({len(pool)} voices)")
    return "\n".join(lines)


async def speak(
    word: str,
    lang: str,
    gender: str | None = None,
    rate: str = "+0%",
    output: str | None = None,
) -> str:
    await _ensure_voices()
    voice = _default_voice(lang, gender)
    if output is None:
        output = Path(f"{lang}_{word}.mp3")
    communicate = edge_tts.Communicate(word, voice, rate=rate)
    await communicate.save(str(output))
    return str(output)


async def list_voices(target: str | None = None) -> str:
    await _ensure_voices()
    lines = []
    codes = {target} if target else set(_VOICES)
    for code in sorted(codes):
        pool = _VOICES.get(code, {})
        if not pool:
            continue
        label = LANGUAGES[code].name_fa if code in LANGUAGES else code
        lines.append(f"\n{code} ({label}):")
        for name in sorted(pool):
            lines.append(f"  {name}")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pronounce a word using Edge TTS for catalog-supported languages."
    )
    parser.add_argument("word", nargs="?", help="The word to pronounce")
    parser.add_argument(
        "-l",
        "--lang",
        default="en",
        help="Language code (default: en, supports catalog codes + fa)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output MP3 path (default: <lang>_<word>.mp3)",
    )
    parser.add_argument(
        "--gender",
        default=None,
        choices=["Male", "Female"],
        help="Preferred voice gender (default: auto per language)",
    )
    parser.add_argument(
        "--rate",
        default="+0%",
        help='Speaking rate, e.g. "+0%", "-20%", "+30%" (default: +0%)',
    )
    parser.add_argument(
        "--list-languages",
        action="store_true",
        help="List supported languages and available voices",
    )
    parser.add_argument(
        "--list-voices",
        type=str,
        nargs="?",
        const="",
        metavar="LANG",
        help="List all Edge TTS voice names (optionally filter by language code)",
    )
    args = parser.parse_args()

    if args.list_languages:
        print("Supported languages (from catalog + فارسی):")
        print(await supported_languages())
        return

    if args.list_voices is not None:
        target = args.list_voices if args.list_voices else None
        print(await list_voices(target))
        return

    if not args.word:
        parser.error("the following arguments are required: word")

    try:
        out = await speak(args.word, args.lang, args.gender, args.rate, args.output)
        print(f"Saved: {out}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
