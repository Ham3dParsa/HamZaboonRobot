"""Mechanical runner tests (R1–R4 mapping, stubs only, no I/O).

Locked: best_key = first candidate in table index order (R1); fires =
row evidence "+"-split unioned for best key (R2); twin-suspect +
ultra-short -> deferred (R3); LINK:*->approved, MANUAL-NONE /
quarantined-known-false->rejected, else deferred (R4).
"""

from __future__ import annotations

from factory.linking import mechanical_runner as _mech


def _index(rows):
    from factory.linking import build_link_index

    return build_link_index(rows)


def _sense(sid="run#1", full="en-run-en-verb-X", definition="move fast on foot",
           lemma="run", cands=None):
    if cands is None:
        cands = [{"synset_id": "run%2:38:00::"}]
    return {"sense_id": sid, "full_id": full, "lemma": lemma,
            "definition": definition, "example": "", "tags": [],
            "candidates": cands}


def test_r1_best_key_is_first_candidate_in_order():
    index = _index([
        {"kaikki_sense_id": "run#1",
         "wordnet_sensekey": "run%2:38:00::",
         "method": "LINK:2-sig", "evidence": "Sa:j=0.40+Sb:run"},
        {"kaikki_sense_id": "run#1",
         "wordnet_sensekey": "run%2:38:01::",
         "method": "JUDGE-PENDING", "evidence": "Sa:j=0.20"},
    ])
    sense = _sense(cands=[{"synset_id": "run%2:38:00::"},
                          {"synset_id": "run%2:38:01::"}])
    (rec,) = _mech.run_mechanical([sense], index)
    assert rec["best_key"] == "run%2:38:00::"


def test_r2_fires_unioned_across_rows_for_best_key():
    index = _index([
        {"kaikki_sense_id": "run#1",
         "wordnet_sensekey": "run%2:38:00::",
         "method": "LINK:2-sig", "evidence": "Sa:j=0.40+Sb:run"},
        {"kaikki_sense_id": "run#1",
         "wordnet_sensekey": "run%2:38:00::",
         "method": "LINK:2-sig", "evidence": "Sd:hyp=move+Sb:run"},
        {"kaikki_sense_id": "run#1",
         "wordnet_sensekey": "run%2:38:01::",
         "method": "LINK:2-sig", "evidence": "Sa:j=0.90"},
    ])
    assert _mech._fires_for_key(
        index["run#1"], "run%2:38:00::") == [
        "Sa:j=0.40", "Sb:run", "Sd:hyp=move"]


def test_r4_link_maps_approved():
    index = _index([
        {"kaikki_sense_id": "run#1",
         "wordnet_sensekey": "run%2:38:00::",
         "method": "LINK:2-sig",
         "evidence": "Sa:j=0.40+Sb:fast"},
    ])
    (rec,) = _mech.run_mechanical(
        [_sense(definition="move fast on foot quickly")], index)
    assert rec["method"].startswith("LINK")
    assert rec["verdict"] == "approved"


def test_r4_manual_none_maps_rejected():
    index = _index([
        {"kaikki_sense_id": "k",
         "wordnet_sensekey": "-",
         "method": "MANUAL-NONE", "evidence": "owner-locked:x"},
    ])
    assert _mech.map_verdict("MANUAL-NONE") == "rejected"
    assert _mech.map_verdict("quarantined-known-false") == "rejected"
    assert _mech.map_verdict("LINK:2-sig") == "approved"
    assert _mech.map_verdict("JUDGE-PENDING") == "deferred"
    assert _mech.map_verdict("UNMAPPED") == "deferred"
    assert _mech.map_verdict("twin-pending") == "deferred"


def test_r3_ultra_short_forces_deferred():
    index = _index([
        {"kaikki_sense_id": "run#1",
         "wordnet_sensekey": "run%2:38:00::",
         "method": "LINK:2-sig", "evidence": "Sa:j=0.40+Sb:fast"},
    ])
    (rec,) = _mech.run_mechanical(
        [_sense(definition="An error.")], index)
    assert rec["verdict"] == "deferred"
    assert rec["deferred_reason"] == "ultra-short"


def test_r3_twin_suspect_forces_deferred():
    index = _index([
        {"kaikki_sense_id": "run#1",
         "wordnet_sensekey": "run%2:38:00::",
         "method": "LINK:2-sig", "evidence": "Sa:j=0.40+Sb:fast"},
        {"kaikki_sense_id": "run#1",
         "wordnet_sensekey": "run%2:38:01::",
         "method": "LINK:2-sig", "evidence": "Sa:j=0.41+Sb:fast"},
    ])
    sense = _sense(definition="move fast on foot quickly",
                   cands=[{"synset_id": "run%2:38:00::"},
                          {"synset_id": "run%2:38:01::"}])
    (rec,) = _mech.run_mechanical([sense], index)
    assert rec["verdict"] == "deferred"
    assert rec["deferred_reason"] == "twin-suspect"


def test_no_candidates_defers_without_invention():
    (rec,) = _mech.run_mechanical([_sense(cands=[])], _index([]))
    assert rec["best_key"] == ""
    assert rec["verdict"] == "deferred"


def test_summarize_counts():
    rows = [{"verdict": "approved"}, {"verdict": "deferred"},
            {"verdict": "deferred"}, {"verdict": "rejected"}]
    assert _mech.summarize(rows) == {"approved": 1, "rejected": 1,
                                     "deferred": 2, "total": 4}
