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


def test_anchor_parity_with_old_home():
    from factory.pipeline import precard_pipeline as old

    index, read_entry = _idx()
    item = {"kind": "word", "text": "apple", "pool_level": "A1"}
    new = anchor.anchor_rank_item(item, index, read_entry)
    before = old.anchor_rank_item(item, index, read_entry)
    assert [c["sense_id"] for c in new["candidates"]] == [
        c["sense_id"] for c in before["candidates"]]
    assert new["top"] == before["top"]
    assert new["anchor_pos"] == before["anchor_pos"]


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
    feb = anchor.preprocess_classify_item(
        {"kind": "word", "text": "FEB", "pool_level": "B1"},
        pos_sets, lambda t: 4.0, set(), {}, False,
        entry_fn=lambda t: view)
    assert feb["kept"] is False
    assert feb["reason"].startswith("g4-abbrev")


def test_stage_ids_are_real_words():
    assert anchor.STAGES == ("preprocess", "anchor_rank")
