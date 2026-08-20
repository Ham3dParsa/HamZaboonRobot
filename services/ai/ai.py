import json
import logging
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from openai import OpenAI

from config import (
    AI_MAX_OUTPUT_TOKENS,
    AI_TEMPERATURE,
    AI_TIMEOUT_SECONDS,
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    COST,
)
from services import db
from services.ai import ai_read_cache, preset_fields, prompts

log = logging.getLogger(__name__)


def create_client(preset: dict | None = None, *, api_key_override: str | None = None) -> OpenAI:
    """Create an OpenAI client for a preset (or the active settings).

    This is the single seam for constructing an OpenAI client. API keys are
    resolved **only** through ``db.resolve_preset_key(preset)``, which is
    fail-closed: a missing master key or absent preset key resolves to ``""``
    and never to a plaintext fallback (BUG-2). The explicit ``api_key_override``
    is reserved for admin connection probes (``test_connection``) where the
    caller intentionally supplies credentials to test; it is never inferred.
    """
    if preset is None:
        preset = db.get_active_preset()
    base_url = preset_fields.resolve(preset, "base_url")
    # A falsy override (empty string) is treated as "not provided" so the caller
    # falls through to the fail-closed key resolution instead of sending an
    # explicit empty key (SUGGESTION from review: never bypass resolution with
    # a blank override).
    api_key = (
        api_key_override
        if api_key_override
        else db.resolve_preset_key(preset)
    )
    timeout = preset_fields.resolve(preset, "timeout_seconds")
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
    )


def _client(preset: dict | None = None) -> OpenAI:
    """Thin compatibility alias delegating to the single ``create_client`` seam."""
    return create_client(preset)


def _model(preset: dict | None = None) -> str:
    if preset is None:
        preset = db.get_active_preset()
    if preset.get("model"):
        return preset["model"]
    return db.get_setting("ai_model", DEFAULT_AI_MODEL)


def test_connection(
    base_url: str,
    api_key: str,
    model: str,
    timeout: float = AI_TIMEOUT_SECONDS,
) -> dict:
    """Lightweight connection test (not tracked in llm_requests).

    Routes client construction through ``create_client`` so the connection
    probe shares the same fail-closed/key-resolution seam (BUG-3). The
    ``api_key`` here is the explicit override the caller intends to test.
    """
    client = create_client(
        {"base_url": base_url, "model": model, "timeout_seconds": timeout},
        api_key_override=api_key,
    )
    started = time.monotonic()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        latency_ms = (time.monotonic() - started) * 1000
        return {
            "success": True,
            "latency_ms": round(latency_ms),
            "model": resp.model,
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                "total_tokens": resp.usage.total_tokens if resp.usage else 0,
            },
        }
    except Exception as exc:
        latency_ms = (time.monotonic() - started) * 1000
        return {
            "success": False,
            "latency_ms": round(latency_ms),
            "error_class": type(exc).__name__,
            "error_message": str(exc)[:500],
        }


def custom_test_card(
    system_prompt: str,
    user_prompt: str,
    lang: str,
    goal: str,
    level: str,
    preset: dict | None = None,
    *,
    request_kind: str = "custom_test",
    user_id: int | None = None,
    plan: str | None = None,
) -> dict:
    """Run a real ask_card call for preview/testing.

    Goes through the full validation pipeline. Not tracked in cost dashboard.
    """
    telemetry: dict[str, object] = {}
    error: Exception | None = None
    try:
        if preset is None:
            preset = db.get_active_preset()
        client = _client(preset)
        model = _model(preset)
        started = time.monotonic()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=preset_fields.resolve(preset or {}, "temperature"),
            max_tokens=preset_fields.resolve(preset or {}, "max_output_tokens"),
        )
        telemetry["usage"] = resp.usage
        telemetry["latency_ms"] = (time.monotonic() - started) * 1000
        telemetry["model"] = model
        telemetry["request_kind"] = request_kind
        content = resp.choices[0].message.content or ""
        value = _extract_json(content)
        return validate_card(value)
    except Exception as exc:
        error = exc
        raise
    finally:
        # Log to config_tests table instead of llm_requests
        db.log_config_test(
            test_type="custom",
            preset_name=preset.get("name") if preset else db.get_active_preset_name(),
            prompt=user_prompt,
            result={
                "success": error is None,
                "error_class": type(error).__name__ if error else None,
                "error_message": str(error)[:500] if error else None,
            },
        )


_COST_OUTCOME_ICON = {
    "success": "✓",
    "failure_billed": "✕",
    "failure_zero_cost": "⚪",
}

def _log_llm_request(
    *,
    request_kind: str,
    user_id: int | None,
    plan: str | None,
    model: str,
    telemetry: dict[str, object],
    outcome: str,
    preset: dict | None = None,
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

    preset_name = preset.get("name", "?") if preset else "?"

    # Resolve cost per-million from the preset dict already in hand (it came
    # from the chain/active read, so no re-query), falling back to the global
    # profile. The profile read is served from a TTL cache (BOT-2) invalidated
    # on admin save. Preset-level cost edits via admin_ai take effect at the
    # chain TTL (~10s); the profile fallback is invalidated instantly.
    if preset:
        input_cost = preset.get("input_cost_per_million")
        output_cost = preset.get("output_cost_per_million")
    else:
        input_cost = None
        output_cost = None

    profile = ai_read_cache.get_cost_profile()
    input_cost_per_million = input_cost if input_cost is not None else profile["input_cost_usd_per_million"]
    output_cost_per_million = output_cost if output_cost is not None else profile["output_cost_usd_per_million"]

    if prompt_tokens and completion_tokens:
        cost_usd = (
            prompt_tokens * input_cost_per_million
            + completion_tokens * output_cost_per_million
        ) / 1_000_000
    else:
        cost_usd = 0.0
    outcome_icon = _COST_OUTCOME_ICON.get(outcome, "?")
    outcome_label = f"{outcome_icon} {outcome.removeprefix('failure_').removeprefix('billed_') if outcome.startswith('failure') else outcome}"
    tokens_str = f"{total_tokens} tok" if total_tokens is not None else "———"
    cost_str = f"${cost_usd:.6f}" if cost_usd > 0 else "———"

    log.log(
        COST,
        "kind=%s user=%s preset=%s outcome=%s tokens=%s latency=%sms cost=%s",
        request_kind,
        str(user_id or "?"),
        preset_name,
        outcome_label,
        tokens_str,
        latency_value if latency_value is not None else "?",
        cost_str,
    )

    batch_validation = telemetry.get("batch_validation")
    if isinstance(batch_validation, dict):
        log.log(
            COST,
            "batch validation: received=%-4s accepted=%-4s rejected=%-4s "
            "duplicates=%-3s avoid_dup=%-3s batch_dup=%-3s avoid_words=%-3s",
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
        log.log(
            COST,
            "rejection reasons: kind=%s reasons=%s",
            request_kind,
            rejection_reasons,
        )

    db.add_llm_request(
        user_id=user_id or 0,
        plan=plan or "unknown",
        request_kind=request_kind,
        model=model,
        outcome=outcome,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        input_cost_usd_per_million=input_cost_per_million,
        output_cost_usd_per_million=output_cost_per_million,
        usd_to_toman_rate=profile["usd_to_toman_rate"],
        latency_ms=latency_value,
        error_class=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        preset_name=preset_name,
    )


def _call_tracked(
    fn,
    *,
    request_kind: str,
    user_id: int | None = None,
    plan: str | None = None,
    preset: dict | None = None,
    log_target: Callable[..., None] | None = None,
):
    """Run a tracked AI call, owning the telemetry/error/outcome lifecycle.

    ``fn(telemetry)`` must describe the request, perform the model call
    (populating ``telemetry``), and return the validated value. On any
    exception the error is captured and re-raised; the ``finally`` block logs
    the request and classifies the cost outcome (success vs billed vs
    zero-cost) based on whether ``usage`` was recorded.

    ``log_target`` overrides where the request record is written. It defaults
    to ``_log_llm_request`` (the ``llm_requests`` table); a test-only caller
    may pass a different writer (e.g. to the ``config_tests`` table) so that
    throwaway/test calls do not pollute the cost dashboard.

    Returns a ``TrackedResult`` wrapping the value and the telemetry so the
    AI limiter can read real token usage (BUG-1). Callers that do not need the
    telemetry read ``.value``.
    """
    telemetry: dict[str, object] = {}
    error: Exception | None = None
    writer = log_target if log_target is not None else _log_llm_request
    try:
        value = fn(telemetry)
    except Exception as exc:
        error = exc
        raise
    finally:
        writer(
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            model=str(telemetry.get("model") or _model(preset)),
            telemetry=telemetry,
            outcome="success" if error is None else (
                "failure_billed" if telemetry.get("usage") is not None else "failure_zero_cost"
            ),
            preset=preset,
            error=error,
        )
    return TrackedResult(value=value, telemetry=telemetry)


class RateLimitError(Exception):
    """Raised when an AI provider returns HTTP 429 (rate limited)."""


@dataclass
class TrackedResult:
    """Return value of a tracked AI call, carrying its telemetry.

    The limiter reads ``.telemetry`` to apply real TPM enforcement (BUG-1) and
    unwraps ``.value`` before handing the result to callers, so the public
    functions keep returning their plain dict/list value to callers while the
    token usage stays visible to the quota layer.
    """

    value: object
    telemetry: dict[str, object] = field(default_factory=dict)


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

_PHONETIC_LINE_RE = re.compile(r"^\s*(ipa)\s*:\s*(.+?)\s*$", re.IGNORECASE)


def normalize_phonetic(raw: str) -> dict[str, str] | None:
    raw = raw.strip()
    if not raw:
        return None

    # Label-based parsing (IPA only)
    sections: dict[str, str] = {}
    for line in raw.splitlines():
        match = _PHONETIC_LINE_RE.match(line)
        if match:
            sections[match.group(1).casefold()] = match.group(2).strip()

    if "ipa" in sections:
        return {"ipa": sections["ipa"]}

    return None


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
    if len(set(normalized)) != len(values):
        raise CardValidationError(
            f"Card field '{field}' must contain distinct items"
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

    # Normalize phonetic field to structured format
    phonetic_raw = data.get("phonetic")
    if phonetic_raw is None:
        phonetic_normalized = {"ipa": ""}
    elif isinstance(phonetic_raw, dict):
        phonetic_normalized = {"ipa": phonetic_raw.get("ipa", "")}
    elif isinstance(phonetic_raw, str) and phonetic_raw.strip():
        phonetic_raw_clean = phonetic_raw.strip()
        phonetic_normalized = normalize_phonetic(phonetic_raw_clean)
        if phonetic_normalized is None:
            log.warning("phonetic unparseable raw=[%s] treating as bare IPA", phonetic_raw_clean[:200])
            phonetic_normalized = {"ipa": phonetic_raw_clean}
    else:
        phonetic_normalized = {"ipa": ""}

    return {
        "word": _required_text(data, "word"),
        "phonetic": phonetic_normalized,
        "fa_meaning": _required_text(data, "fa_meaning"),
        "fa_explanation": _required_text(data, "fa_explanation"),
        "synonyms": synonyms,
        "antonyms": antonyms,
        "examples": examples,
        "example_translations": translations,
        "grammar_tip": str(data.get("grammar_tip") or "").strip(),
    }


def card_repair_fields(data: object) -> list[str]:
    if not isinstance(data, Mapping):
        return [
            "word",
            "fa_meaning",
            "fa_explanation",
            "examples",
            "example_translations",
        ]

    data = _expand_card_aliases(data)
    fields: list[str] = []
    for field in ("word", "fa_meaning", "fa_explanation"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            fields.append(field)

    examples = data.get("examples")
    translations = data.get("example_translations")
    examples_valid = (
        isinstance(examples, list)
        and len(examples) == 2
        and all(isinstance(item, str) and item.strip() for item in examples)
    )
    translations_valid = (
        isinstance(translations, list)
        and len(translations) == 2
        and all(isinstance(item, str) and item.strip() for item in translations)
    )
    if not examples_valid or not translations_valid:
        fields.extend(["examples", "example_translations"])

    phonetic_value = data.get("phonetic")
    if phonetic_value is None:
        phonetic_value = data.get("ph")
    if isinstance(phonetic_value, str) and phonetic_value.strip() and normalize_phonetic(phonetic_value) is None:
        fields.append("phonetic")
    elif isinstance(phonetic_value, dict):
        if not phonetic_value.get("ipa"):
            fields.append("phonetic")

    for field in ("synonyms", "antonyms"):
        value = data.get(field)
        if value is None:
            continue
        try:
            values = _text_list(data, field)
            _validate_optional_rich_list(field, values)
        except CardValidationError:
            fields.append(field)
    return list(dict.fromkeys(fields))


def validate_card_patch(data: object, fields: list[str]) -> dict:
    if not isinstance(data, Mapping):
        raise CardValidationError("Card repair output must be a JSON object")
    expanded = _expand_card_aliases(data)
    requested = set(fields)
    if set(expanded) != requested:
        raise CardValidationError(
            "Card repair output must contain exactly the requested fields"
        )

    patch: dict[str, object] = {}
    for field in fields:
        if field in {"word", "fa_meaning", "fa_explanation"}:
            patch[field] = _required_text(expanded, field)
        elif field in {"examples", "example_translations"}:
            values = _text_list(expanded, field, required=True)
            if len(values) != 2:
                raise CardValidationError(
                    f"Card repair field '{field}' must contain exactly two items"
                )
            patch[field] = values
        elif field in {"synonyms", "antonyms"}:
            values = _text_list(expanded, field)
            _validate_optional_rich_list(field, values)
            patch[field] = values
        elif field == "phonetic":
            patch[field] = _required_text(expanded, field)
        else:
            raise CardValidationError(f"Unsupported card repair field '{field}'")
    if {"examples", "example_translations"} & requested:
        if not {"examples", "example_translations"} <= requested:
            raise CardValidationError(
                "Examples and translations must be repaired together"
            )
    return patch


def repair_card(
    card: object,
    fields: list[str],
    lang: str,
    *,
    user_id: int | None = None,
    plan: str | None = None,
    preset: dict | None = None,
) -> TrackedResult:
    def _run(telemetry: dict[str, object]) -> dict:
        value = _request_json(
            prompts.card_repair_system_prompt(lang, card, fields),
            user_prompt="فقط patch حداقلی فیلدهای درخواست‌شده را بساز.",
            request_kind="card_repair",
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
            preset=preset,
        )
        return validate_card_patch(value, fields)

    return _call_tracked(
        _run,
        request_kind="card_repair",
        user_id=user_id,
        plan=plan,
        preset=preset,
    )


def _request_json(
    system_prompt: str,
    user_prompt: str = "بساز.",
    *,
    request_kind: str = "json",
    user_id: int | None = None,
    plan: str | None = None,
    telemetry: dict[str, object] | None = None,
    preset: dict | None = None,
) -> object:
    """یک تماس با مدل زبانی می‌گیرد و انتظار دارد خروجی JSON خام باشد."""
    if preset is None:
        preset = db.get_active_preset()
    client = _client(preset)
    model = _model(preset)
    temp = preset_fields.resolve(preset or {}, "temperature")
    mtokens = preset_fields.resolve(preset or {}, "max_output_tokens")
    started = time.monotonic()
    telemetry = telemetry if telemetry is not None else {}
    telemetry["model"] = model
    telemetry["request_kind"] = request_kind
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temp,
            max_tokens=mtokens,
        )
    except Exception as exc:
        if getattr(exc, "status_code", None) == 429 or "RateLimitError" in type(exc).__name__:
            raise RateLimitError(str(exc)) from exc
        raise
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
    preset: dict | None = None,
) -> TrackedResult:
    def _run(telemetry: dict[str, object]) -> dict:
        value = _request_json(
            system_prompt,
            user_prompt,
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
            preset=preset,
        )
        if not isinstance(value, Mapping):
            raise CardValidationError("Expected a JSON object")
        return dict(value)

    return _call_tracked(
        _run,
        request_kind=request_kind,
        user_id=user_id,
        plan=plan,
        preset=preset,
    )


def ask_card(
    system_prompt: str,
    user_prompt: str = "بساز.",
    *,
    request_kind: str = "card",
    user_id: int | None = None,
    plan: str | None = None,
    preset: dict | None = None,
) -> TrackedResult:
    def _run(telemetry: dict[str, object]) -> dict:
        value = _request_json(
            system_prompt,
            user_prompt,
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
            preset=preset,
        )
        try:
            return validate_card(value)
        except CardValidationError:
            log.warning("ask_card raw [%s]", json.dumps(value, ensure_ascii=False)[:500])
            raise

    return _call_tracked(
        _run,
        request_kind=request_kind,
        user_id=user_id,
        plan=plan,
        preset=preset,
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
    preset: dict | None = None,
) -> TrackedResult:
    def _run(telemetry: dict[str, object]) -> list[dict]:
        diagnostics: dict[str, int] = {}
        rejection_reasons: dict[str, int] = {}
        telemetry["batch_validation"] = diagnostics
        telemetry["batch_validation_reasons"] = rejection_reasons
        value = _request_json(
            system_prompt,
            request_kind=request_kind,
            user_id=user_id,
            plan=plan,
            telemetry=telemetry,
            preset=preset,
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

    return _call_tracked(
        _run,
        request_kind=request_kind,
        user_id=user_id,
        plan=plan,
        preset=preset,
    )
