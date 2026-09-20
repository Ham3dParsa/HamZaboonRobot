"""R-acro acronym/expression pack (locked 2026-09-20, R1-R6 + amendments).

Focused pins per locked rule — mechanical, stdlib-only, zero AI cost:
R1 G4-abbrev two-leg gate (dead-tag drop / wordfreq pass / fail-open),
R2 OTHER/unmapped quota survival, R3 zipf->CEFR fallback (bands +
min-formula + method tag + distribution log), R4 EVP coverage DROP,
R5 pack scope (origin_pack_id + pack_memberships.jsonl + FSRS
invariant), R6 contract addendum. Existing G4 bulk-drop expectations
are obsolete (see test_precard_anchor.py) — updated, never silently
deleted.
"""

import json
from pathlib import Path

from factory.precard import anchor
from factory.precard import cefr as cefr_home
from factory.precard import enrich as enrich_home
from factory.precard import pipeline as pipeline_home
from factory.precard import selector

ROOT = Path(__file__).parents[2]


def _view(tags, gloss="Abbreviation of February."):
    return {"poss": {"noun"},
            "senses": [{"gloss": gloss, "tags": list(tags)}]}


# --- R1: G4-abbrev two-leg mechanical gate ---

def test_r1_threshold_provisional_value():
    assert anchor.G4_ZIPF_PASS == 3.2
    assert anchor.G4_DEAD_TAGS == frozenset({
        "calendar", "unit_of_measure", "chemical_element", "currency"})


def test_r1_dead_tag_drops():
    for dead in ("calendar", "unit_of_measure", "chemical_element",
                 "currency"):
        reason, _ = anchor._preprocess_input_gates(
            "FEB", _view(["abbreviation", dead]), zipf_fn=lambda t: 9.0)
        assert reason == "g4-abbrev", dead


def test_r1_dead_tag_casefolded():
    reason, _ = anchor._preprocess_input_gates(
        "feb", _view(["Abbreviation", "Unit_of_Measure"]),
        zipf_fn=lambda t: 9.0)
    assert reason == "g4-abbrev"


def test_r1_wordfreq_pass_ge_threshold():
    reason, quar = anchor._preprocess_input_gates(
        "FEB", _view(["abbreviation"]), zipf_fn=lambda t: 3.2)
    assert reason is None  # multi? single -> quarantine below
    assert quar == "g4-abbrev"  # lone single-abbrev sense: review flag


def test_r1_wordfreq_pass_multi_sense_no_quarantine():
    view = {"poss": {"noun"},
            "senses": [{"gloss": "Abbreviation of February.",
                        "tags": ["abbreviation"]},
                       {"gloss": "A kind of bean.",
                        "tags": []}]}
    reason, quar = anchor._preprocess_input_gates(
        "FEB", view, zipf_fn=lambda t: 5.0)
    assert reason is None
    assert quar is None


def test_r1_fail_open_no_wordfreq_entry_none():
    reason, _ = anchor._preprocess_input_gates(
        "ZZQ", _view(["abbreviation"]), zipf_fn=lambda t: None)
    assert reason is None  # missing data never drops


def test_r1_fail_open_no_wordfreq_entry_zero():
    # wordfreq 0.0 means OOV (no entry) — survives on this leg even
    # though R20 treats 0.0 as a real low score elsewhere.
    reason, _ = anchor._preprocess_input_gates(
        "ZZQ", _view(["abbreviation"]), zipf_fn=lambda t: 0.0)
    assert reason is None


def test_r1_fail_open_lookup_error():
    def _boom(term):
        raise RuntimeError("wordfreq down")

    reason, _ = anchor._preprocess_input_gates(
        "FEB", _view(["abbreviation"]), zipf_fn=_boom)
    assert reason is None


def test_r1_known_infrequent_drops():
    reason, _ = anchor._preprocess_input_gates(
        "FEB", _view(["abbreviation"]), zipf_fn=lambda t: 2.0)
    assert reason == "g4-abbrev"


def test_r1_caps_without_tag_never_drops():
    # Bulk all-caps drop REMOVED: BOOK/PLAY-shaped inputs with no
    # abbreviation tag pass G4 (other gates may still fire).
    reason, quar = anchor._preprocess_input_gates(
        "BOOK", {"poss": {"noun"},
                 "senses": [{"gloss": "A bound volume.", "tags": []}]},
        zipf_fn=lambda t: 5.0)
    assert reason is None
    assert quar is None


def test_r1_gate_inert_without_abbrev_tag():
    reason, quar = anchor._preprocess_input_gates(
        "led", {"poss": {"verb"},
                "senses": [{"gloss": "To guide.", "tags": []}]},
        zipf_fn=lambda t: 1.0)
    assert reason is None
    assert quar is None


# --- R2: unmapped/phrase rows survive stratification ---

def _other_row(key):
    return {"key": key, "sense_cefr": "", "sense_cefr_method": "unmapped",
            "zipf": 1.0}


def test_r2_default_keeps_all_other_rows():
    rows = [_other_row("w:x"), _other_row("w:y"),
            {"key": "w:z", "sense_cefr": "B1",
             "sense_cefr_method": "pool-fallback", "zipf": 5.0}]
    selected, summary = selector.sample(
        rows, quotas={"B1": 5}, drop_tags=frozenset())
    assert {r["key"] for r in selected} == {"w:x", "w:y", "w:z"}
    assert summary["per_level"]["OTHER"]["selected"] == 2
    assert summary["per_level"]["OTHER"]["shortfall"] == 0


def test_r2_phrase_rows_survive_default():
    rows = [{"key": "p:too much", "kind": "phrase", "sense_cefr": "",
             "sense_cefr_method": "unmapped", "zipf": 4.0}]
    selected, _ = selector.sample(
        rows, quotas={"B1": 5}, drop_tags=frozenset())
    assert [r["key"] for r in selected] == ["p:too much"]


def test_r2_explicit_other_quota_still_caps():
    rows = [_other_row("w:x"), _other_row("w:y")]
    selected, summary = selector.sample(
        rows, quotas={"B1": 5}, drop_tags=frozenset(), other_quota=1)
    assert len(selected) == 1
    assert summary["per_level"]["OTHER"]["selected"] == 1


# --- R3: zipf->CEFR fallback (acronym/phrase only) ---

def setup_function(_):
    cefr_home.reset_zipf_heuristic_dist()


def test_r3_method_tag_never_official():
    assert cefr_home.METHOD_ZIPF_HEURISTIC == "zipf-heuristic"
    cefr, method = cefr_home.zipf_heuristic_cefr(
        "hot wheels", "phrase", zipf_fn=lambda t: 4.5)
    assert (cefr, method) == ("B1", "zipf-heuristic")


def test_r3_bands_and_boundaries():
    cases = [(5.5, "B1"), (4.2, "B1"), (4.19, "B2"), (3.5, "B2"),
             (3.2, "B2"), (3.19, "C1"), (1.0, "C1")]
    for value, want in cases:
        cefr, method = cefr_home.zipf_heuristic_cefr(
            "hot wheels", "phrase", zipf_fn=lambda t: value)
        assert cefr == want, value
        assert method == "zipf-heuristic"


def test_r3_acronym_kind_on_path_word_off_path():
    cefr, method = cefr_home.zipf_heuristic_cefr(
        "DNA", "acronym", zipf_fn=lambda t: 3.5)
    assert (cefr, method) == ("B2", "zipf-heuristic")
    assert cefr_home.zipf_heuristic_cefr(
        "apple", "word", zipf_fn=lambda t: 6.0) == (None, "unmapped")


def test_r3_whole_phrase_lookup_first():
    seen = []

    def _fn(term):
        seen.append(term)
        return 5.0 if term == "hot wheels" else 1.0

    assert cefr_home.phrase_zipf("hot wheels", _fn) == 5.0


def test_r3_zero_whole_falls_to_min_tokens():
    def _fn(term):
        return 0.0 if term == "hot wheels" else {"hot": 4.0,
                                                "wheels": 3.0}[term]

    assert cefr_home.phrase_zipf("hot wheels", _fn) == 3.0


def test_r3_unknown_tokens_skip_not_zero_filled():
    def _fn(term):
        return {"hot": 4.0}.get(term, 0.0)

    # Only "hot" known -> min over known, never dragged to 0 by OOV.
    assert cefr_home.phrase_zipf("hot wheels", _fn) == 4.0
    assert cefr_home.phrase_zipf("zzq qqq", lambda t: 0.0) is None


def test_r3_missing_data_stays_unmapped():
    assert cefr_home.zipf_heuristic_cefr(
        "zzq qqq", "phrase", zipf_fn=lambda t: None) == (None, "unmapped")
    assert cefr_home.zipf_heuristic_cefr(
        "zzq qqq", "phrase", zipf_fn=lambda t: 0.0) == (None, "unmapped")


def test_r3_distribution_logged_per_band():
    cefr_home.zipf_heuristic_cefr("a", "phrase", lambda t: 5.0)
    cefr_home.zipf_heuristic_cefr("b", "phrase", lambda t: 3.5)
    cefr_home.zipf_heuristic_cefr("c", "phrase", lambda t: 1.0)
    cefr_home.zipf_heuristic_cefr("d", "phrase", lambda t: None)
    dist = dict(cefr_home.ZIPF_HEURISTIC_DIST)
    assert dist == {"A2/B1": 1, "B2": 1, "C1/C2": 1, "missing": 1}


def test_r3_enrich_bridge_miss_falls_to_heuristic(monkeypatch):
    monkeypatch.setattr(enrich_home, "sense_cefr_for",
                        lambda *a, **k: (None, "unmapped"))
    cefr, method = enrich_home._sense_cefr_or_unmapped(
        "hot wheels", "noun", "a wager on wheels", kind="phrase",
        text="hot wheels", zipf_fn=lambda t: 3.5)
    assert (cefr, method) == ("B2", "zipf-heuristic")


def test_r3_enrich_word_bridge_miss_stays_unmapped(monkeypatch):
    monkeypatch.setattr(enrich_home, "sense_cefr_for",
                        lambda *a, **k: (None, "unmapped"))
    assert enrich_home._sense_cefr_or_unmapped(
        "apple", "noun", "a round fruit", kind="word",
        text="apple", zipf_fn=lambda t: 6.0) == ("", "unmapped")


# --- R4: EVP direct-mapping DROP (check first, evidence wins) ---

def _real_evp():
    path = ROOT / "factory" / "packs" / "en" / "evp_sense.json"
    return json.loads(path.read_text(encoding="utf-8")).get("entries", {})


def _real_phrases():
    import csv

    path = ROOT / "factory" / "packs" / "en" / "phrases.csv"
    with open(path, encoding="utf-8", newline="") as handle:
        return [row["phrase"] for row in csv.DictReader(handle)
                if row.get("phrase")]


def _evp_map(entries):
    # Loader-shaped map (cf. load_evp_guidewords): lemma-keyed, so the
    # coverage check exercises the same grain as the real consumer.
    out = {}
    for key, val in entries.items():
        if not isinstance(val, dict):
            continue
        lemma = str(key).split("|")[0]
        out.setdefault(lemma, []).append(
            (str(val.get("guideword") or "").lower(),
             str(val.get("cefr") or "")))
    return out


def test_r4_synthetic_hit_detected():
    evp = {"hot wheels": [("wheels", "B2")]}
    rep = cefr_home.evp_phrase_acronym_coverage(
        evp, ["hot wheels", "ice cream"])
    assert rep["pack_hits"] == 1
    assert rep["pack_hit_sample"] == ["hot wheels"]


def test_r4_real_pack_zero_hits_mapping_dropped():
    # The check is real, not vacuous: the pack HAS multiword entries,
    # but NONE of the live 500-phrase pool hits — so no mapping ships.
    raw = _real_evp()
    rep = cefr_home.evp_phrase_acronym_coverage(
        _evp_map(raw), _real_phrases())
    assert len(raw) == 2000  # raw pack rows (multi rows per lemma)
    assert rep["evp_entries"] == len(_evp_map(raw))  # lemma grain
    assert rep["evp_multiword_entries"] > 0
    assert rep["pack_phrases"] == 500
    assert rep["pack_hits"] == 0  # DROP: a mapping would serve zero rows


# --- R5: factory-side pack scope ---

def test_r5_row_stamps_origin_pack_id():
    row = pipeline_home._build_precard_row(
        {"kind": "phrase", "text": "hot wheels"}, "p:hot wheels",
        {"sense_id": ""}, {}, {}, [], {}, {}, {}, {}, {}, 0, 1,
        pack_id="core-500")
    assert row["origin_pack_id"] == "core-500"
    legacy = pipeline_home._build_precard_row(
        {"kind": "word", "text": "apple"}, "w:apple",
        {"sense_id": "apple#0"}, {}, {},
        [{"label": "Food & Drink", "weight": 1.0}],
        {}, {}, {}, {}, {}, 0, 1)
    assert legacy["origin_pack_id"] == ""  # old shape compatible


def test_r5_membership_emission_shape(tmp_path):
    recs = [{"pre_card_id": "c1"}, {"pre_card_id": ""},
            {"pre_card_id": "c2"}]
    rows = pipeline_home.build_pack_memberships(
        recs, "core-500", "Unit 1", "2026-09-20T00:00:00Z")
    assert rows == [
        {"card_id": "c1", "pack_id": "core-500", "priority": 0,
         "section": "Unit 1", "added_at": "2026-09-20T00:00:00Z"},
        {"card_id": "c2", "pack_id": "core-500", "priority": 1,
         "section": "Unit 1", "added_at": "2026-09-20T00:00:00Z"}]
    out = tmp_path / "precard.jsonl"
    out.write_text("", encoding="utf-8")
    written = pipeline_home.write_pack_memberships(out, rows)
    assert written.endswith("pack_memberships.jsonl")
    back = [json.loads(line) for line in
            Path(written).read_text(encoding="utf-8").splitlines()]
    assert back == rows


def test_r5_fsrs_invariant_documented():
    doc = (ROOT / "factory" / "CARD_SCHEMA_V1.md").read_text(
        encoding="utf-8")
    assert "pack_memberships.jsonl" in doc
    assert "NEVER affects scheduling" in doc
    assert "(user_id, card_id)" in doc


# --- R6: contract addendum ---

def test_r6_addendum_lists_exact_keys():
    doc = (ROOT / ".opencode" / "plans" / "lexicon" / "CONTRACT-linker.md"
           ).read_text(encoding="utf-8")
    assert "Deterministic tags travel with row" in doc
    for key in ("sense_cefr", "sense_cefr_method", "pos", "pos_src",
                "register", "lexical_type", "pre_card_id",
                "abbrev_expansion", "circular_def", "topic_vector",
                "topic_method", "topic_path", "topic_guarded"):
        assert key in doc, key
