import json
import re
from collections.abc import Mapping

from openai import OpenAI

from config import DEFAULT_AI_BASE_URL, DEFAULT_AI_API_KEY, DEFAULT_AI_MODEL
import db


def _client() -> OpenAI:
    base_url = db.get_setting("ai_base_url", DEFAULT_AI_BASE_URL)
    api_key = db.get_setting("ai_api_key", DEFAULT_AI_API_KEY)
    return OpenAI(base_url=base_url, api_key=api_key)


def _model() -> str:
    return db.get_setting("ai_model", DEFAULT_AI_MODEL)


class CardValidationError(ValueError):
    """Raised when the model output cannot be stored as a vocabulary card."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    # حذف بلاک کد
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    # پیدا کردن بزرگ‌ترین آبجکت JSON
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    return json.loads(text)


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


def ask_json(system_prompt: str, user_prompt: str = "بساز.") -> dict:
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


def ask_card(system_prompt: str, user_prompt: str = "بساز.") -> dict:
    return validate_card(ask_json(system_prompt, user_prompt))
