import json
import re
from collections.abc import Mapping

from openai import OpenAI

from config import (
    AI_TIMEOUT_SECONDS,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_MODEL,
)
import db


def _client() -> OpenAI:
    base_url = db.get_setting("ai_base_url", DEFAULT_AI_BASE_URL)
    api_key = db.get_setting("ai_api_key", DEFAULT_AI_API_KEY)
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=AI_TIMEOUT_SECONDS,
    )


def _model() -> str:
    return db.get_setting("ai_model", DEFAULT_AI_MODEL)


class CardValidationError(ValueError):
    """Raised when the model output cannot be stored as a vocabulary card."""


class BatchValidationError(ValueError):
    """Raised when a model response cannot be interpreted as a card batch."""


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


def _required_text(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CardValidationError(f"Card field '{field}' must be a non-empty string")
    return value.strip()


def _text_list(data: Mapping[str, object], field: str, *, required: bool = False) -> list[str]:
    value = data.get(field)
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CardValidationError(f"Card field '{field}' must be a list of strings")
    result = [item.strip() for item in value if item.strip()]
    if required and not result:
        raise CardValidationError(f"Card field '{field}' must not be empty")
    return result


def validate_card(data: object) -> dict:
    if not isinstance(data, Mapping):
        raise CardValidationError("Card output must be a JSON object")

    examples = _text_list(data, "examples", required=True)
    translations = _text_list(data, "example_translations", required=True)
    if len(examples) != len(translations):
        raise CardValidationError("Each example must have exactly one translation")

    return {
        "word": _required_text(data, "word"),
        "phonetic": str(data.get("phonetic") or "").strip(),
        "fa_meaning": _required_text(data, "fa_meaning"),
        "fa_explanation": _required_text(data, "fa_explanation"),
        "synonyms": _text_list(data, "synonyms"),
        "antonyms": _text_list(data, "antonyms"),
        "examples": examples,
        "example_translations": translations,
        "grammar_tip": str(data.get("grammar_tip") or "").strip(),
    }


def _request_json(system_prompt: str, user_prompt: str = "بساز.") -> object:
    """یک تماس با مدل زبانی می‌گیرد و انتظار دارد خروجی JSON خام باشد."""
    client = _client()
    resp = client.chat.completions.create(
        model=_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.9,
    )
    content = resp.choices[0].message.content or ""
    return _extract_json(content)


def ask_json(system_prompt: str, user_prompt: str = "بساز.") -> dict:
    value = _request_json(system_prompt, user_prompt)
    if not isinstance(value, Mapping):
        raise CardValidationError("Expected a JSON object")
    return dict(value)


def ask_card(system_prompt: str, user_prompt: str = "بساز.") -> dict:
    return validate_card(ask_json(system_prompt, user_prompt))


def validate_batch(
    data: object,
    expected_count: int,
    used_words: list[str] | None = None,
) -> list[dict]:
    if isinstance(data, Mapping):
        data = data.get("cards")
    if not isinstance(data, list):
        raise BatchValidationError("Batch output must be a JSON array")

    used = {
        word.strip().casefold()
        for word in (used_words or [])
        if isinstance(word, str) and word.strip()
    }
    cards: list[dict] = []
    for item in data:
        try:
            card = validate_card(item)
        except CardValidationError:
            continue
        normalized_word = card["word"].strip().casefold()
        if normalized_word in used:
            continue
        used.add(normalized_word)
        cards.append(card)
        if len(cards) >= expected_count:
            break
    return cards


def ask_batch(
    system_prompt: str,
    expected_count: int,
    used_words: list[str] | None = None,
) -> list[dict]:
    return validate_batch(
        _request_json(system_prompt),
        expected_count,
        used_words=used_words,
    )
