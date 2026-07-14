import json
import logging
import re
import time
from collections.abc import Mapping

from openai import OpenAI

from config import (
    AI_MAX_OUTPUT_TOKENS,
    AI_TEMPERATURE,
    AI_TIMEOUT_SECONDS,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_MODEL,
)
import db

log = logging.getLogger("hamzaban.ai")


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


def _log_llm_request(
    *,
    request_kind: str,
    user_id: int | None,
    plan: str | None,
    model: str,
    telemetry: dict[str, object],
    outcome: str,
    error: Exception | None = None,
):
    usage = telemetry.get("usage")
    latency_ms = telemetry.get("latency_ms")
    latency_value = round(float(latency_ms)) if isinstance(latency_ms, (int, float)) else None
    if usage is None:
        prompt_tokens = completion_tokens = total_tokens = None
    else:
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
    log.info(
        "ai request kind=%s user_id=%s model=%s outcome=%s latency_ms=%s "
        "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        request_kind,
        user_id,
        model,
        outcome,
        latency_value,
        prompt_tokens,
        completion_tokens,
        total_tokens,
    )
    batch_validation = telemetry.get("batch_validation")
    if isinstance(batch_validation, dict):
        log.info(
            "ai batch validation kind=%s user_id=%s received=%s accepted=%s "
            "validation_rejected=%s duplicates=%s duplicates_against_avoid=%s "
            "duplicates_within_batch=%s avoid_words=%s",
            request_kind,
            user_id,
            batch_validation.get("received", 0),
            batch_validation.get("accepted", 0),
            batch_validation.get("validation_rejected", 0),
            batch_validation.get("duplicates", 0),
            batch_validation.get("duplicates_against_avoid", 0),
            batch_validation.get("duplicates_within_batch", 0),
            batch_validation.get("avoid_words", 0),
        )
    rejection_reasons = telemetry.get("batch_validation_reasons")
    if isinstance(rejection_reasons, dict) and rejection_reasons:
        log.info(
            "ai batch validation rejection reasons kind=%s user_id=%s reasons=%s",
            request_kind,
            user_id,
            rejection_reasons,
        )
    profile = db.get_llm_cost_profile()
    db.add_llm_request(
        user_id=user_id or 0,
        plan=plan or "unknown",
        request_kind=request_kind,
        model=model,
        outcome=outcome,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        input_cost_usd_per_million=profile["input_cost_usd_per_million"],
        output_cost_usd_per_million=profile["output_cost_usd_per_million"],
        usd_to_toman_rate=profile["usd_to_toman_rate"],
        latency_ms=latency_value,
        error_class=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
    )


class CardValidationError(ValueError):
    """Raised when the model output cannot be stored as a vocabulary card."""


class BatchValidationError(ValueError):
    """Raised when a model response cannot be interpreted as a usable batch."""

    def __init__(self, message: str, diagnostics: dict[str, int] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


_COMPACT_CARD_FIELDS = {
    "w": "word",
    "ph": "phonetic",
    "m": "fa_meaning",
    "x": "fa_explanation",
    "s": "synonyms",
    "a": "antonyms",
    "e": "examples",
    "t": "example_translations",
    "g": "grammar_tip",
}


def _expand_card_aliases(data: Mapping[str, object]) -> dict[str, object]:
    expanded = dict(data)
    for compact_name, canonical_name in _COMPACT_CARD_FIELDS.items():
        if canonical_name not in expanded and compact_name in expanded:
            expanded[canonical_name] = expanded[compact_name]
    return expanded


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


def _validate_optional_rich_list(field: str, values: list[str]) -> None:
    if not values:
        return
    normalized = [" ".join(value.split()).casefold() for value in values]
    if len(values) < 2 or len(set(normalized)) != len(values):
        raise CardValidationError(
            f"Card field '{field}' must contain at least two distinct items"
        )


def validate_card(data: object) -> dict:
    if not isinstance(data, Mapping):
        raise CardValidationError("Card output must be a JSON object")
    data = _expand_card_aliases(data)

    examples = _text_list(data, "examples", required=True)
    translations = _text_list(data, "example_translations", required=True)
    if len(examples) != 2 or len(translations) != 2:
        raise CardValidationError("Card must contain exactly two examples and translations")
    if len(examples) != len(translations):
        raise CardValidationError("Each example must have exactly one translation")
    synonyms = _text_list(data, "synonyms")
    antonyms = _text_list(data, "antonyms")
    _validate_optional_rich_list("synonyms", synonyms)
    _validate_optional_rich_list("antonyms", antonyms)

    return {
        "word": _required_text(data, "word"),
        "phonetic": str(data.get("phonetic") or "").strip(),
        "fa_meaning": _required_text(data, "fa_meaning"),
        "fa_explanation": _required_text(data, "fa_explanation"),
        "synonyms": synonyms,
        "antonyms": antonyms,
        "examples": examples,
        "example_translations": translations,
        "grammar_tip": str(data.get("grammar_tip") or "").strip(),
    }


def _request_json(
    system_prompt: str,
    user_prompt: str = "بساز.",
    *,
    request_kind: str = "json",
    user_id: int | None = None,
    plan: str | None = None,
    telemetry: dict[str, object] | None = None,
) -> object:
    """یک تماس با مدل زبانی می‌گیرد و انتظار دارد خروجی JSON خام باشد."""
    client = _client()
    model = _model()
    started = time.monotonic()
    telemetry = telemetry if telemetry is not None else {}
    telemetry["model"] = model
    telemetry["request_kind"] = request_kind
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=AI_TEMPERATURE,
        max_tokens=AI_MAX_OUTPUT_TOKENS,
    )
    telemetry["usage"] = resp.usage
    telemetry["latency_ms"] = (time.monotonic() - started) * 1000
    content = resp.choices[0].message.content or ""
    try:
        return _extract_json(content)
    except Exception as exc:
        telemetry["error"] = exc
        raise


def ask_json(
    system_prompt: str,
    user_prompt: str = "بساز.",
    *,
    request_kind: str = "json",
    user_id: int | None = None,
    plan: str | None = None,
) -> dict:
    telemetry: dict[str, object] = {}
    error: Exception | None = None
    try:
        value = _request_json(
            system_prompt,
            user_prompt,
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
        )
        if not isinstance(value, Mapping):
            raise CardValidationError("Expected a JSON object")
        return dict(value)
    except Exception as exc:
        error = exc
        raise
    finally:
        _log_llm_request(
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            model=str(telemetry.get("model") or _model()),
            telemetry=telemetry,
            outcome="success" if error is None else (
                "failure_billed" if telemetry.get("usage") is not None else "failure_zero_cost"
            ),
            error=error,
        )


def ask_card(
    system_prompt: str,
    user_prompt: str = "بساز.",
    *,
    request_kind: str = "card",
    user_id: int | None = None,
    plan: str | None = None,
) -> dict:
    telemetry: dict[str, object] = {}
    error: Exception | None = None
    try:
        value = _request_json(
            system_prompt,
            user_prompt,
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
        )
        return validate_card(value)
    except Exception as exc:
        error = exc
        raise
    finally:
        _log_llm_request(
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            model=str(telemetry.get("model") or _model()),
            telemetry=telemetry,
            outcome="success" if error is None else (
                "failure_billed" if telemetry.get("usage") is not None else "failure_zero_cost"
            ),
            error=error,
        )


def validate_batch(
    data: object,
    expected_count: int,
    used_words: list[str] | None = None,
    diagnostics: dict[str, int] | None = None,
    rejection_reasons: dict[str, int] | None = None,
) -> list[dict]:
    stats = diagnostics if diagnostics is not None else {}
    stats.setdefault("received", 0)
    stats.setdefault("accepted", 0)
    stats.setdefault("validation_rejected", 0)
    stats.setdefault("duplicates", 0)
    stats.setdefault("duplicates_against_avoid", 0)
    stats.setdefault("duplicates_within_batch", 0)
    if isinstance(data, Mapping):
        data = data.get("cards")
    if not isinstance(data, list):
        raise BatchValidationError("Batch output must be a JSON array", stats)

    avoid = {
        word.strip().casefold()
        for word in (used_words or [])
        if isinstance(word, str) and word.strip()
    }
    used = set(avoid)
    stats["avoid_words"] = len(avoid)
    cards: list[dict] = []
    for item in data:
        stats["received"] += 1
        try:
            card = validate_card(item)
        except CardValidationError as exc:
            stats["validation_rejected"] += 1
            if rejection_reasons is not None:
                reason = str(exc)
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
            continue
        normalized_word = card["word"].strip().casefold()
        if normalized_word in avoid:
            stats["duplicates_against_avoid"] += 1
            stats["duplicates"] += 1
            continue
        if normalized_word in used:
            stats["duplicates_within_batch"] += 1
            stats["duplicates"] += 1
            continue
        used.add(normalized_word)
        cards.append(card)
        stats["accepted"] += 1
        if len(cards) >= expected_count:
            break
    return cards


def ask_batch(
    system_prompt: str,
    expected_count: int,
    used_words: list[str] | None = None,
    *,
    request_kind: str = "batch",
    user_id: int | None = None,
    plan: str | None = None,
) -> list[dict]:
    telemetry: dict[str, object] = {}
    error: Exception | None = None
    diagnostics: dict[str, int] = {}
    rejection_reasons: dict[str, int] = {}
    telemetry["batch_validation"] = diagnostics
    telemetry["batch_validation_reasons"] = rejection_reasons
    try:
        value = _request_json(
            system_prompt,
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
        )
        cards = validate_batch(
            value,
            expected_count,
            used_words=used_words,
            diagnostics=diagnostics,
            rejection_reasons=rejection_reasons,
        )
        if not cards:
            raise BatchValidationError(
                "No valid cards remained after batch validation",
                diagnostics,
            )
        return cards
    except Exception as exc:
        error = exc
        raise
    finally:
        _log_llm_request(
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            model=str(telemetry.get("model") or _model()),
            telemetry=telemetry,
            outcome="success" if error is None else (
                "failure_billed" if telemetry.get("usage") is not None else "failure_zero_cost"
            ),
            error=error,
        )
