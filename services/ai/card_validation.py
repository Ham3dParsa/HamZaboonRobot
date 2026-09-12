"""Pure card-validation leaf for AI-generated vocabulary cards (REF5-T2).

Verbatim home of ``validate_card``, ``card_repair_fields``,
``validate_card_patch`` and ``validate_batch`` (+ private helpers, alias sets
and error types) previously defined in ``services/ai/ai.py``. This module is
stdlib-only: it takes already-parsed data and never touches extraction
(the network, the database or ``services.ai.ai`` (never
import it — callers combine extraction with these validators). Zero AI-volume
delta: pure local checks, no provider calls.
"""

import logging
import re
from collections.abc import Mapping

log = logging.getLogger(__name__)


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
