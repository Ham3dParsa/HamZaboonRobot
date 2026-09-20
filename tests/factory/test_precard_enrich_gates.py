"""F3 v0.8 gates wired into the enrich path (locked contract:

CONTRACT-linker.md F3 + 2026-09-19 SignalQualityVeto log-only lock).

Enrich-path integration: hermetic fixtures, zero model calls, zero
network. gate_ctx keys are optional — missing signals fail open to
LINK (missing data never routes), exactly like gates_r.py preserve
rules. Table v4.x builds untouched; pipeline row assembly untouched
(gate annotations live on the enrich payload; row surfacing is
follow-up, not invented here).
"""

from factory.linker import gates
from factory.precard import enrich as new_enrich


def _idx():
    def rows(glosses, ipa):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": [{"text": (
                                           "She eats a fresh red apple "
                                           "every morning")}]}
                                      for g in glosses]}}]
    index = {"apple": rows(["a round fruit", "a tech company"], "/aɪpa/")}

    def read_entry(row):
        return row["entry"]

    return index, read_entry


def _item_pick():
    item = {"kind": "word", "text": "apple", "pool_level": "A1"}
    pick = {"sense_id": "apple#0", "gloss": "a round fruit"}
    return item, pick


def _clean_ctx(**over):
    ctx = {
        "rank_index": 0, "winner_jaccard": 0.27,
        "winner_gloss": "a round fruit",
        "wordnet_evidence": "x a round fruit y",
        "winner_fires": ["Sa:j=0.27", "Sb:source"],
        "votes_for": 3, "votes_total": 3, "failed": 0,
        "rank1_fires": ["Sa:j=0.27", "Sb:source"],
        "rank2_fires": ["Sd:hyp=move"],
    }
    ctx.update(over)
    return ctx


def test_enrich_no_ctx_links_with_empty_fires_backward_compat():
    index, read_entry = _idx()
    item, pick = _item_pick()
    out = new_enrich.enrich_item(item, pick, index, read_entry, {})
    assert out["gate_verdict"] == gates.LINK
    assert out["gate_fires"] == []
    assert out["signal_quality_would_fire"] is False
    assert out["sense_id"] == "apple#0"
    assert out["en_def"] == "a round fruit"


def test_enrich_split_two_one_escalates_never_direct_links():
    index, read_entry = _idx()
    item, pick = _item_pick()
    out = new_enrich.enrich_item(
        item, pick, index, read_entry, {},
        gate_ctx=_clean_ctx(votes_for=2, votes_total=3))
    assert out["gate_verdict"] == "ESCALATE:HUMAN_QUEUE"
    assert "SplitVoteVeto" in out["gate_fires"]
    assert out["sense_id"] == "apple#0"


def test_enrich_low_rank_zero_overlap_escalates():
    index, read_entry = _idx()
    item, pick = _item_pick()
    out = new_enrich.enrich_item(
        item, pick, index, read_entry, {},
        gate_ctx=_clean_ctx(rank_index=2, winner_jaccard=0.0,
                            winner_fires=["Sd:hyp=fruit"]))
    assert out["gate_verdict"] == "ESCALATE:HUMAN_QUEUE"
    assert "LowRankZeroOverlapVeto" in out["gate_fires"]


def test_enrich_evidence_mismatch_escalates_but_bailout_links():
    index, read_entry = _idx()
    item, pick = _item_pick()
    fired = new_enrich.enrich_item(
        item, pick, index, read_entry, {},
        gate_ctx=_clean_ctx(winner_jaccard=0.10,
                            wordnet_evidence="Sa:j=0.10+Sd:hyp=company"))
    assert fired["gate_verdict"] == "ESCALATE:HUMAN_QUEUE"
    assert "EvidenceGlossMismatchVeto" in fired["gate_fires"]
    bailed = new_enrich.enrich_item(
        item, pick, index, read_entry, {},
        gate_ctx=_clean_ctx(winner_jaccard=0.20,
                            wordnet_evidence="Sa:j=0.40+Sd:hyp=company"))
    assert bailed["gate_verdict"] == gates.LINK
    assert bailed["gate_fires"] == []


def test_enrich_signal_quality_log_only_never_blocks():
    index, read_entry = _idx()
    item, pick = _item_pick()
    out = new_enrich.enrich_item(
        item, pick, index, read_entry, {},
        gate_ctx=_clean_ctx(rank1_fires=["Sd:hyp=move"],
                            rank2_fires=["Sb:source", "Sd:topic=light"]))
    assert out["signal_quality_would_fire"] is True
    assert out["gate_verdict"] == gates.LINK
    assert out["gate_fires"] == []


def test_enrich_clean_unanimous_links():
    index, read_entry = _idx()
    item, pick = _item_pick()
    out = new_enrich.enrich_item(
        item, pick, index, read_entry, {},
        gate_ctx=_clean_ctx())
    assert out["gate_verdict"] == gates.LINK
    assert out["gate_fires"] == []
    assert out["signal_quality_would_fire"] is False
