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

Hermetic golden fixtures: two rows vendored verbatim into this file
(BASE kid en-run-en-verb-4acunXz3, WITH kid en-fall-en-noun-7thbY1M6)
as always-executing tests with no W: read, so the builder ships with
executing byte-parity coverage on Linux CI where the frozen dir is absent.
The full W:-backed parity tests below remain as extended local verification.
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

# Portability guard (clean-checkout/CI): per-test skip for the W:-backed
# full-parity tests when the frozen batch dir is absent — no behavior
# change when present. The vendored golden tests at the bottom of this
# file carry no mark and always execute.
_REQUIRES_RUN20 = pytest.mark.skipif(
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


@_REQUIRES_RUN20
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


@_REQUIRES_RUN20
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


@_REQUIRES_RUN20
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


# ---------------------------------------------------------------------------
# Hermetic golden fixtures (vendored verbatim from the frozen proof batches).
# These two tests ALWAYS execute — including on Linux CI where the W: dir is
# absent — so the builder ships with executing byte-parity coverage everywhere.
# Source rows (read-only, never modified):
# - BASE: judge_batch_run20.json entry kid=en-run-en-verb-4acunXz3
#   (kaikki sidecar from candidates_run20.json[en-run-en-verb-4acunXz3], top3 -> candidates)
# - WITH: slice_unseen_50.json entry kid=en-fall-en-noun-7thbY1M6 (kaikki/candidates verbatim,
#   incl. extra keys the builder ignores such as pos/fires/jaccard)
# ---------------------------------------------------------------------------


_GOLDEN_BASE_KAAIKKI = {
  "lemma": "run",
  "gloss": "To move forward quickly upon two feet by alternately making a short jump off either foot.",
  "synonyms": [],
  "examples": [
    "Run, and you might still catch the train!",
    "Through the open front door ran Jessamy, down the steps to where Kitto was sitting at the bottom with the pram beside him."
  ],
  "topics": []
}


_GOLDEN_BASE_CANDIDATES = [
  {
    "sensekey": "run%2:38:11::",
    "gloss": "move about freely and without restraint, or act as if running around in an uncontrolled way",
    "lemmas": [
      "run"
    ],
    "examples": [
      "who are these people running around in the building?",
      "She runs around telling everyone of her troubles"
    ]
  },
  {
    "sensekey": "run%2:38:01::",
    "gloss": "move along, of liquids",
    "lemmas": [
      "course",
      "feed",
      "flow",
      "run"
    ],
    "examples": [
      "Water flowed into the cave",
      "the Missouri feeds into the Mississippi"
    ]
  },
  {
    "sensekey": "run%2:38:00::",
    "gloss": "move fast by using one's feet, with one foot off the ground at any given time",
    "lemmas": [
      "run"
    ],
    "examples": [
      "Don't run--you'll be out of breath",
      "The children ran to the store"
    ]
  }
]


_GOLDEN_BASE_PROMPT = """You are judging a word-sense link for the headword "run".

LEARNER-DICTIONARY ENTRY (kaikki):
gloss: To move forward quickly upon two feet by alternately making a short jump off either foot.
synonyms: (none)
examples: Run, and you might still catch the train! || Through the open front door ran Jessamy, down the steps to where Kitto was sitting at the bottom with the pram beside him.

CANDIDATE SENSES (answer with the NUMBER only):
1. move about freely and without restraint, or act as if running around in an uncontrolled way || words: run || eg: who are these people running around in the building? || She runs around telling everyone of her troubles
2. move along, of liquids || words: course; feed; flow; run || eg: Water flowed into the cave || the Missouri feeds into the Mississippi
3. move fast by using one's feet, with one foot off the ground at any given time || words: run || eg: Don't run--you'll be out of breath || The children ran to the store

RULE: quote the evidence, pick <=1 or NONE, never generalize the headword level
Respond with JSON ONLY, exactly these keys:
{"verdict": "LINK" or "NONE", "winner_index": 1, 2, 3 or null, "kaikki_evidence": "<exact substring copied from the LEARNER-DICTIONARY ENTRY above>", "wordnet_evidence": "<exact substring copied from ONE numbered candidate above>"}
If verdict is NONE, winner_index must be null and wordnet_evidence must be "".
NEVER write a dotted code or parenthesized label; the winner is the NUMBER only."""


_GOLDEN_WITH_KAAIKKI = {
  "lemma": "fall",
  "pos": "noun",
  "gloss": "The chasing of a hunted whale.",
  "synonyms": [],
  "examples": [],
  "topics": [
    "nautical",
    "transport"
  ]
}


_GOLDEN_WITH_CANDIDATES = [
  {
    "sensekey": "fall%1:28:00::",
    "gloss": "the season when the leaves fall from the trees",
    "lemmas": [
      "autumn",
      "fall"
    ],
    "examples": [
      "in the fall of 1973"
    ],
    "fires": [],
    "jaccard": 0.0
  },
  {
    "sensekey": "tumble%1:04:01::",
    "gloss": "a sudden drop from an upright position",
    "lemmas": [
      "fall",
      "spill",
      "tumble"
    ],
    "examples": [
      "he had a nasty spill on the ice"
    ],
    "fires": [],
    "jaccard": 0.0
  },
  {
    "sensekey": "fall%1:11:03::",
    "gloss": "the lapse of mankind into sinfulness because of the sin of Adam and Eve",
    "lemmas": [
      "Fall"
    ],
    "examples": [
      "women have been blamed ever since the Fall"
    ],
    "fires": [],
    "jaccard": 0.0
  }
]


_GOLDEN_WITH_PROMPT = """You are judging a word-sense link for the headword "fall".

LEARNER-DICTIONARY ENTRY (kaikki):
gloss: The chasing of a hunted whale.
synonyms: (none)
examples: (none)
topics: nautical; transport

CANDIDATE SENSES (answer with the NUMBER only):
1. the season when the leaves fall from the trees || words: autumn; fall || eg: in the fall of 1973
2. a sudden drop from an upright position || words: fall; spill; tumble || eg: he had a nasty spill on the ice
3. the lapse of mankind into sinfulness because of the sin of Adam and Eve || words: Fall || eg: women have been blamed ever since the Fall

RULE: quote the evidence, pick <=1 or NONE, never generalize the headword level
Respond with JSON ONLY, exactly these keys:
{"verdict": "LINK" or "NONE", "winner_index": 1, 2, 3 or null, "kaikki_evidence": "<exact substring copied from the LEARNER-DICTIONARY ENTRY above>", "wordnet_evidence": "<exact substring copied from ONE numbered candidate above>"}
If verdict is NONE, winner_index must be null and wordnet_evidence must be "".
NEVER write a dotted code or parenthesized label; the winner is the NUMBER only.

--- ADDED (Guarded-D substitution test) ---
SUBSTITUTION TEST: winner gloss must replace kaikki gloss in the example sentence without shifting meaning, else NONE."""


def test_golden_base_byte_parity():
    """Vendored BASE row byte-identical (always executes, no W: read)."""
    prompt, index_map = _BUILDER.build(
        _GOLDEN_BASE_KAAIKKI,
        _GOLDEN_BASE_CANDIDATES,
        ArbitrationPromptTemplate.BASE,
    )
    _assert_byte_identical(
        prompt, _GOLDEN_BASE_PROMPT, "en-run-en-verb-4acunXz3", "golden/BASE"
    )
    assert index_map == {
        str(i + 1): c["sensekey"]
        for i, c in enumerate(_GOLDEN_BASE_CANDIDATES)
    }
    assert "ADDED" not in prompt


def test_golden_with_substitution_byte_parity():
    """Vendored WITH row byte-identical (always executes, no W: read)."""
    prompt, index_map = _BUILDER.build(
        _GOLDEN_WITH_KAAIKKI,
        _GOLDEN_WITH_CANDIDATES,
        ArbitrationPromptTemplate.WITH_IN_PROMPT_SUBSTITUTION,
    )
    _assert_byte_identical(
        prompt, _GOLDEN_WITH_PROMPT, "en-fall-en-noun-7thbY1M6", "golden/WITH"
    )
    assert index_map == {
        str(i + 1): c["sensekey"]
        for i, c in enumerate(_GOLDEN_WITH_CANDIDATES)
    }
    assert prompt.endswith(
        "--- ADDED (Guarded-D substitution test) ---\n"
        "SUBSTITUTION TEST: winner gloss must replace kaikki gloss "
        "in the example sentence without shifting meaning, else NONE."
    )
