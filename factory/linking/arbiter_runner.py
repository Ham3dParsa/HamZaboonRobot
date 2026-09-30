"""LLM arbiter runner (P1): prompt → transport → strict parse → records.

Pure orchestration over injected seams (no I/O, no network, no registry
reads here — the caller supplies senses, preset, and transport):

- prompt: ``SenseLinkingArbitrationPromptBuilder`` (BASE template; the
  builder is the single owner of prompt wording).
- transport: ``prompt_text -> raw_model_text`` callable. Production
  passes a provider adapter; tests pass stubs. Transport exceptions
  (timeout etc.) are caught per sense.
- parse: strict JSON ``{verdict LINK|NONE, winner_index N|null, ...}``
  with first-``{...}``-block tolerance for chat prose. Winner NUMBER
  resolves through the builder's ``index_map``.

Abstention rule (fail-closed, never an invented verdict): malformed
payloads, out-of-range winners, and transport failures yield
``verdict None`` + ``needs_review True`` (+ ``error`` text). Only clean
parses yield ``link``/``none``. The gate layer routes every
``needs_review`` record to supervised review regardless of verdict.
"""

from __future__ import annotations

import json

from factory.linking.arbitration_prompt import (
    ArbitrationPromptTemplate,
    SenseLinkingArbitrationPromptBuilder,
)

PROMPT_VERSION = "v0.7-BASE"

_BUILDER = SenseLinkingArbitrationPromptBuilder()


def _to_kaikki(item):
    """Batch-shaped sense -> builder-shaped kaikki (honest empties)."""
    examples = [item.get("example")] if item.get("example") else []
    return {
        "lemma": item.get("lemma", ""),
        "gloss": item.get("definition", ""),
        "synonyms": [],
        "examples": examples,
    }


def _to_candidates(item):
    """Batch-shaped candidates -> builder-shaped candidates."""
    out = []
    for cand in item.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        examples = [cand.get("example")] if cand.get("example") else []
        out.append({
            "sensekey": cand.get("synset_id", ""),
            "gloss": cand.get("definition", ""),
            "lemmas": [],
            "examples": examples,
        })
    return out


def _extract_json_block(text):
    """First balanced ``{...}`` block, or None (strict, no guessing)."""
    depth = 0
    start = None
    for pos, char in enumerate(text or ""):
        if char == "{":
            if depth == 0:
                start = pos
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    return text[start:pos + 1]
    return None


def _parse_answer(raw, index_map):
    """(verdict, target, evidence, error): verdict None = abstain."""
    block = _extract_json_block(raw)
    if block is None:
        return None, None, {}, "no JSON block in model answer"
    try:
        payload = json.loads(block)
    except ValueError as exc:
        return None, None, {}, "answer JSON unparsable (%s)" % exc
    if not isinstance(payload, dict):
        return None, None, {}, "answer JSON is not an object"
    verdict = str(payload.get("verdict") or "").strip().upper()
    if verdict not in ("LINK", "NONE"):
        return None, None, {}, "bad verdict %r (want LINK|NONE)" % (
            payload.get("verdict"),)
    evidence = {
        "kaikki_evidence": payload.get("kaikki_evidence", ""),
        "wordnet_evidence": payload.get("wordnet_evidence", ""),
    }
    if verdict == "NONE":
        return "none", None, evidence, ""
    winner = payload.get("winner_index")
    target = (index_map or {}).get(str(winner))
    if not target:
        return None, None, evidence, \
            "winner_index %r not among candidates" % (winner,)
    return "link", target, evidence, ""


def run_arbiter(senses, preset, transport,
                template=ArbitrationPromptTemplate.BASE):
    """Run the arbiter over senses; return verdict records (pure).

    ``preset`` carries ``provider``/``model`` for record identity (WHO
    judged — never credentials). ``transport`` exceptions abstain per
    sense; one bad sense never stops the rest.
    """
    preset = preset or {}
    model = str(preset.get("model") or "").strip()
    out = []
    for item in senses or []:
        if not isinstance(item, dict):
            continue
        prompt, index_map = _BUILDER.build(
            _to_kaikki(item), _to_candidates(item), template)
        try:
            raw = transport(prompt)
        except Exception as exc:
            out.append({
                "sense_id": item.get("sense_id", ""),
                "verdict": None,
                "target_synset": None,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "needs_review": True,
                "evidence": {},
                "error": "%s: %s" % (type(exc).__name__, exc),
            })
            continue
        verdict, target, evidence, error = _parse_answer(raw, index_map)
        out.append({
            "sense_id": item.get("sense_id", ""),
            "verdict": verdict,
            "target_synset": target,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "needs_review": verdict is None,
            "evidence": evidence,
            "error": error,
        })
    return out
