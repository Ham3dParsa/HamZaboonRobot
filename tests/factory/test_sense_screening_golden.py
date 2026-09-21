"""Sense-screening golden benchmark reader (204 rows).

Hermetic: stdlib only (json + collections + os), no production imports,
no network, no model calls. Pins the finalized consensus fixture shape.

NOTE (spec deviation 2026-09-21): the build spec asked for a 136 KEEP /
68 DROP / 0 NEEDS-REVIEW split, but mechanical per-row application of the
locked rulings yields 139 / 65 / 0 — the three rule-3 DIALECTAL->KEEP
conversions (rows 65, 196, 198) add +3 KEEP over the 155 - 19 hyper-niche
projection. Verdicts were NOT fudged to hit the spec counts; this test
pins the honest outcome. Owner decision needed: accept 139/65/0 or revise
the three rule-3 rulings.
"""

import collections
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(_HERE, "..", "data", "sense_screening_golden_204.json")

N_ROWS = 204
N_KEEP = 139
N_DROP = 65
N_NEEDS_REVIEW = 0

ALLOWED_REASONS = frozenset({
    "KEEP_CORE", "KEEP_LIVING_SLANG", "KEEP_STANDARD_UK",
    "DROP_PROPER_NOUN", "DROP_OBSOLETE", "DROP_DIALECTAL",
    "DROP_FORM_OF", "DROP_TWIN", "DROP_HYPER_NICHE",
    "DROP_OBSCURE_ACRONYM",
})

REQUIRED_FIELDS = frozenset({
    "lemma", "sense_index", "pos", "gloss", "tags", "topics",
    "categories", "has_example", "example_count",
    "verdict", "reason", "notes", "status", "adjudicated_by",
})

STATUS = "confirmed"
ADJUDICATED_BY = "gemini_human_consensus"


def _load():
    with open(os.path.normpath(GOLD), encoding="utf-8") as fh:
        rows = json.load(fh)
    assert isinstance(rows, list)
    return rows


def test_golden_has_204_rows():
    assert len(_load()) == N_ROWS


def test_golden_verdict_split():
    counts = collections.Counter(r["verdict"] for r in _load())
    assert counts.get("KEEP", 0) == N_KEEP
    assert counts.get("DROP", 0) == N_DROP
    assert counts.get("NEEDS-REVIEW", 0) == N_NEEDS_REVIEW
    assert sum(counts.values()) == N_ROWS


def test_golden_reason_vocabulary():
    reasons = {r["reason"] for r in _load()}
    assert reasons <= ALLOWED_REASONS, sorted(reasons - ALLOWED_REASONS)


def test_golden_required_fields():
    for i, row in enumerate(_load()):
        missing = REQUIRED_FIELDS - set(row)
        assert not missing, f"row {i} missing {sorted(missing)}"


def test_golden_status_and_adjudication():
    for i, row in enumerate(_load()):
        assert row["status"] == STATUS, f"row {i} status={row['status']!r}"
        assert row["adjudicated_by"] == ADJUDICATED_BY, (
            f"row {i} adjudicated_by={row['adjudicated_by']!r}")


def test_golden_verdict_reason_agreement():
    for i, row in enumerate(_load()):
        assert row["reason"].startswith(row["verdict"].split("-")[0] + "_"), (
            f"row {i} {row['verdict']}/{row['reason']}")


def test_golden_global_lemma_order():
    rows = _load()
    blocks = [(0, 7, "achieve"), (7, 41, "book"), (41, 62, "wear"),
              (62, 102, "well"), (102, 204, "set")]
    for lo, hi, lemma in blocks:
        bad = [i for i in range(lo, hi) if rows[i]["lemma"] != lemma]
        assert not bad, f"block {lemma} [{lo},{hi}): bad rows {bad}"


def test_golden_consensus_rulings():
    rows = _load()
    # Row 65: living slang intensifier kept.
    assert (rows[65]["lemma"], rows[65]["pos"]) == ("well", "adv")
    assert (rows[65]["verdict"], rows[65]["reason"]) == ("KEEP", "KEEP_LIVING_SLANG")
    # Rows 196/198: standard-UK class-group senses kept.
    assert (rows[196]["lemma"], rows[196]["pos"]) == ("set", "noun")
    assert (rows[196]["verdict"], rows[196]["reason"]) == ("KEEP", "KEEP_STANDARD_UK")
    assert (rows[198]["lemma"], rows[198]["pos"]) == ("set", "verb")
    assert (rows[198]["verdict"], rows[198]["reason"]) == ("KEEP", "KEEP_STANDARD_UK")
    # Rows 202/203: obscure SET acronyms dropped.
    assert (rows[202]["lemma"], rows[202]["pos"]) == ("set", "name")
    assert (rows[202]["verdict"], rows[202]["reason"]) == ("DROP", "DROP_OBSCURE_ACRONYM")
    assert "Energy Technologies" in rows[202]["gloss"]
    assert (rows[203]["lemma"], rows[203]["pos"]) == ("set", "name")
    assert (rows[203]["verdict"], rows[203]["reason"]) == ("DROP", "DROP_OBSCURE_ACRONYM")
    assert "Thailand" in rows[203]["gloss"]
