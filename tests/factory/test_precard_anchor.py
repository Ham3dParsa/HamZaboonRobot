"""Identity T4a: anchor + preprocess live in the new home, parity-pinned.

New-home anchor_rank_item must rank byte-identically to the old home on
the same fixtures (the scorer is vendored frozen, not reinterpreted).
Preprocess verdicts keep their structured reasons (Rundle/Telemark/FEB/
FDR never silent).
"""

from factory.precard import anchor


def _idx():
    def rows(glosses, ipa, pos="noun"):
        return [{"pos": pos,
                 "entry": {"pos": pos, "sounds": [{"ipa": ipa}],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": []} for g in glosses]}}]
    index = {
        "apple": rows(["a round fruit", "a tech company"], "/aɪpa/"),
        "rundle": rows(["A surname."], "", pos="propn"),
        "feb": rows(["Abbreviation of February."], ""),
    }

    def read_entry(row):
        return row["entry"]

    return index, read_entry


def test_anchor_apple_baseline():
    """Cutover baseline (ex-parity): the apple fixture anchors
    deterministically. Full-order parity vs the old home was proven by
    the passing old-vs-new run before the old module was deleted
    (PR #697); the pin stays set-based here because ranking rides
    live wordfreq."""
    index, read_entry = _idx()
    item = {"kind": "word", "text": "apple", "pool_level": "A1"}
    ranked = anchor.anchor_rank_item(item, index, read_entry)
    assert {c["sense_id"] for c in ranked["candidates"]} == {
        "apple#0", "apple#1"}
    assert ranked["top"] == {"sense_id": "apple#0",
                             "gloss": "a round fruit"}
    assert ranked["anchor_pos"] == "noun"


def test_preprocess_structured_verdicts():
    index, _ = _idx()
    pos_sets = {"rundle": {"propn"}, "feb": {"noun"},
                "apple": {"noun"}}
    rundle = anchor.preprocess_classify_item(
        {"kind": "word", "text": "Rundle", "pool_level": "C2"},
        pos_sets, lambda t: 4.0, set(), {}, False, entry_fn=lambda t: None)
    assert rundle["kept"] is False and rundle["reason"].strip() != ""
    view = {"poss": {"noun"},
            "senses": [{"gloss": "Abbreviation of February.",
                        "tags": ["abbreviation"]}]}
    # R-acro (locked 2026-09-20): the bulk all-caps drop is REMOVED —
    # the old "FEB drops as g4-abbrev" expectation is OBSOLETE (bulk
    # caps-drop deleted, never silently kept). FEB is a tagged abbrev
    # with stub zipf 4.0 >= G4_ZIPF_PASS 3.2, so the wordfreq leg
    # passes it as a real-word reading; the lone single-abbrev sense
    # rides quarantine for owner review (item is NOT dropped).
    feb = anchor.preprocess_classify_item(
        {"kind": "word", "text": "FEB", "pool_level": "B1"},
        pos_sets, lambda t: 4.0, set(), {}, False,
        entry_fn=lambda t: view)
    assert feb["kept"] is True
    assert feb.get("quarantine") == "g4-abbrev"


def test_stage_ids_are_real_words():
    assert anchor.ANCHOR_STAGES == ("preprocess", "anchor_rank")
