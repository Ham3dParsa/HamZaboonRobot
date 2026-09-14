"""Identity T2: judge logic lives in the new home, byte-parity with old.

Every test here mirrors an old-home behavior (including a parity probe
against the archive fallback on scoreless inputs). The old module keeps
working untouched until T5 deletes it.
"""

from factory.precard import ids, judge


def _anchor(*senses):
    return {"w:call": {"candidates": [
        {"sense_id": sid, "gloss": gloss} for sid, gloss in senses]}}


def test_prompt_keeps_hierarchy_and_tags():
    batch = [{"kind": "word", "text": "boil", "pool_level": "B1"}]
    anchor_map = {"w:boil": {"candidates": [
        {"sense_id": "boil#2", "gloss": "to heat liquid",
         "tags": ["colloquial"]},
        {"sense_id": "boil#5", "gloss": "a swelling", "tags": []}]}}
    prompt = judge.judge_prompt(batch, anchor_map)
    assert "- boil#2 [colloquial] to heat liquid" in prompt
    assert "UNLESS the item's pool_level is C1/C2" in prompt
    assert "absolute precedence" in judge.judge_prompt(
        [{"kind": "word", "text": "would", "pool_level": "A1"}],
        {"w:would": {"candidates": [
            {"sense_id": "would#0", "gloss": "past of will",
             "tags": []}]}})


def test_validate_multi_and_legacy_shapes():
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = _anchor(("call#0", "a telephone conversation"),
                   ("call#1", "to shout loudly"))
    out = judge.judge_validate_multi(
        {"results": [{"key": "w:call", "picks": ["call#1", "call#0"]}]},
        batch, amap)
    assert [p["sense_id"] for p in out["w:call"]["picks"]] == [
        "call#1", "call#0"]
    legacy = judge.judge_validate_multi(
        {"results": [{"key": "w:call", "pick": "call#0"}]}, batch, amap)
    assert legacy["w:call"]["sense_id"] == "call#0"
    assert len(legacy["w:call"]["picks"]) == 1


def test_gloss_dupes_collapse():
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = _anchor(("call#2", "To reach out with one's voice."),
                   ("call#0", "To reach out with one's voice."))
    out = judge.judge_validate_multi(
        {"results": [{"key": "w:call", "picks": ["call#2", "call#0"]}]},
        batch, amap)
    assert [p["sense_id"] for p in out["w:call"]["picks"]] == ["call#2"]


def test_fallback_matches_archive_first_candidate():
    from factory.archive.v14_v16.run_v14_phase3_judge import (
        deterministic_picks)
    cands = [{"sense_id": "call#%d" % i, "gloss": "sense %d" % i}
             for i in range(4)]
    anchor_res = {"candidates": cands}
    item = {"kind": "word", "text": "call", "pool_level": "A1"}
    got = judge.judge_fallback(item, anchor_res)
    pseudo = {"ranked_senses": [{"sense_id": c["sense_id"]} for c in cands]}
    want = (deterministic_picks(pseudo).get("beginner") or [cands[0][
        "sense_id"]])[0]
    assert got["sense_id"] == want == "call#0"
    assert got["picks"] == [{"sense_id": "call#0", "gloss": "sense 0"}]


def test_ids_stable_and_shaped():
    first = ids.compute_pre_card_id("Call", "noun", "a telephone  call")
    assert first == ids.compute_pre_card_id("call", "NOUN",
                                            "A Telephone Call")
    assert len(first) == 16
