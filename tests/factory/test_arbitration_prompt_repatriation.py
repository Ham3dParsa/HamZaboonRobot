"""Byte-parity repatriation pins for factory.linking.arbitration_prompt.

Frozen-file dependency (documented, non-hermetic by design): these tests
read the read-only factory proof batches at test time — no model calls,
no network, pure string comparison:

- ``W:\\hamzaban_data_factory\\proof-linker\\run20\\judge_batch_run20.json``
  (327 entries, stored ``pass1.prompt`` reference) plus
  ``candidates_run20.json`` (full top3 sidecar: gloss/lemmas/examples —
  the batch entries carry sensekeys only).
- ``W:\\hamzaban_data_factory\\proof-linker\\run20\\slice_unseen_50.json``
  (50 entries, full ``candidates`` inline, stored WITH-substitution
  prompts).
- ``W:\\hamzaban_data_factory\\proof-linker\\run20\\gemini_sample_30x30.json``
  (LINK 30 + REJECTED 30; 17 LINK rows have ``prompt: None`` by design —
  linker-direct rows carry no packs — so 43 rows pin BASE).

Variant note: the frozen gemini prompts are BASE pattern (0/43 contain
the substitution block), therefore they are pinned under BASE. WITH
coverage is pinned by all 50 slice rows. Any char/space/JSON-structure
difference raises AssertionError with the entry kid + first-diff offset.
"""

import json
import os
from pathlib import Path

import pytest

from factory.linking.arbitration_prompt import (
    ArbitrationPromptTemplate,
    SenseLinkingArbitrationPromptBuilder,
)

# Overridable for absence simulation: HAMZABAN_RUN20_DIR=<dir> pytest ...
RUN20 = Path(
    os.environ.get(
        "HAMZABAN_RUN20_DIR", r"W:\hamzaban_data_factory\proof-linker\run20"
    )
)
BATCH_RUN20 = RUN20 / "judge_batch_run20.json"
SIDECAR_RUN20 = RUN20 / "candidates_run20.json"
SLICE_50 = RUN20 / "slice_unseen_50.json"
GEMINI_SAMPLE = RUN20 / "gemini_sample_30x30.json"

# Portability guard (clean-checkout/CI): skip the whole module when the
# frozen batch dir is absent — no behavior change when present.
pytestmark = pytest.mark.skipif(
    not RUN20.is_dir(),
    reason=(
        "frozen run20 batch dir absent (%s): byte-parity pins require "
        "local proof batches" % RUN20
    ),
)

_BUILDER = SenseLinkingArbitrationPromptBuilder()


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _assert_byte_identical(got, want, kid, label):
    assert got == want, (
        "%s byte mismatch for %s: len got=%d want=%d first_diff=%s\n"
        "got : %r\nwant: %r"
        % (
            label,
            kid,
            len(got),
            len(want),
            next(
                (
                    i
                    for i, (a, b) in enumerate(zip(got, want))
                    if a != b
                ),
                min(len(got), len(want)),
            ),
            got[:300],
            want[:300],
        )
    )


def _cand(row):
    return {
        "sensekey": row["sensekey"],
        "gloss": row["gloss"],
        "lemmas": row["lemmas"],
        "examples": row["examples"],
    }


def test_run20_base_byte_parity():
    """All 327 run20 rows byte-identical under BASE."""
    batch = _load(BATCH_RUN20)
    sidecar = _load(SIDECAR_RUN20)
    entries = batch["entries"]
    assert len(entries) == 327, len(entries)
    checked = 0
    for e in entries:
        sc = sidecar[e["kid"]]
        kaikki = {
            "lemma": sc["lemma"],
            "gloss": sc["gloss"],
            "synonyms": sc["synonyms"],
            "examples": sc["examples"],
            "topics": sc["topics"],
        }
        cands = [_cand(c) for c in sc["top3"]]
        prompt, index_map = _BUILDER.build(
            kaikki, cands, ArbitrationPromptTemplate.BASE
        )
        _assert_byte_identical(
            prompt, e["pass1"]["prompt"], e["kid"], "run20/BASE"
        )
        assert index_map == {
            str(i + 1): c["sensekey"] for i, c in enumerate(cands)
        }, e["kid"]
        assert "ADDED" not in prompt, e["kid"]
        checked += 1
    assert checked == 327, checked


def test_slice_unseen_with_substitution_byte_parity():
    """All 50 slice rows byte-identical under WITH_IN_PROMPT_SUBSTITUTION."""
    batch = _load(SLICE_50)
    entries = batch["entries"]
    assert len(entries) == 50, len(entries)
    checked = 0
    for e in entries:
        prompt, index_map = _BUILDER.build(
            e["kaikki"],
            e["candidates"],
            ArbitrationPromptTemplate.WITH_IN_PROMPT_SUBSTITUTION,
        )
        _assert_byte_identical(
            prompt, e["pass1"]["prompt"], e["kid"], "slice/WITH"
        )
        assert index_map == {
            str(i + 1): c["sensekey"]
            for i, c in enumerate(e["candidates"])
        }, e["kid"]
        assert prompt.endswith(
            "--- ADDED (Guarded-D substitution test) ---\n"
            "SUBSTITUTION TEST: winner gloss must replace kaikki gloss "
            "in the example sentence without shifting meaning, else NONE."
        ), e["kid"]
        checked += 1
    assert checked == 50, checked


def test_gemini_sample_base_byte_parity():
    """Gemini rows carrying prompts (43/60) byte-identical under BASE.

    17 LINK rows have ``prompt: None`` by design (linker-direct rows carry
    no packs) and are skipped explicitly — never hand-filled.
    """
    batch = _load(GEMINI_SAMPLE)
    assert len(batch["LINK"]) == 30, len(batch["LINK"])
    assert len(batch["REJECTED"]) == 30, len(batch["REJECTED"])
    checked = skipped = 0
    for side in ("LINK", "REJECTED"):
        for row in batch[side]:
            if not isinstance(row.get("prompt"), str):
                skipped += 1
                continue
            prompt, index_map = _BUILDER.build(
                row["kaikki"], row["top3"], ArbitrationPromptTemplate.BASE
            )
            _assert_byte_identical(
                prompt, row["prompt"], row["kid"], "gemini/BASE"
            )
            assert index_map == {
                str(i + 1): c["sensekey"]
                for i, c in enumerate(row["top3"])
            }, row["kid"]
            assert "ADDED" not in prompt, row["kid"]
            checked += 1
    assert (checked, skipped) == (43, 17), (checked, skipped)


def test_module_boundaries():
    """New module owns prompt assembly only: two templates, no tally/queue."""
    assert {t.name for t in ArbitrationPromptTemplate} == {
        "BASE",
        "WITH_IN_PROMPT_SUBSTITUTION",
    }
    surface = set(dir(_BUILDER)) | set(
        dir(__import__("factory.linking.arbitration_prompt", fromlist=["x"]))
    )
    for forbidden in (
        "parse_verdict",
        "majority_vote",
        "human_queue",
        "judge_batch",
    ):
        assert forbidden not in surface, forbidden
