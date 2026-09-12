"""Pure JSON extraction for AI provider responses (REF5-T1).

Stdlib-only leaf: must never import ``services.ai.ai`` (cycle). Owns the
fence-strip + ``raw_decode`` scan + ``No JSON value found`` contract;
``services/ai/ai.py`` keeps ``_extract_json`` as a thin re-export alias.
"""

import json
import re


def _extract_json(text: str) -> object:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise json.JSONDecodeError("No JSON value found", text, 0)
