"""v14.1 blocker resolution + P1 fan-out (R1-R6), hermetic.

No network, no W:, no real keys. Covers:
- R1: sense-judge multi-pick (1-4) validation + fan-out into N precard rows.
- R2: Rundle/Telemark/FEB/FDR shapes never vanish silently; accounting audit.
- R3: example fallback chain (sense -> lemma -> pool -> synthetic flag).
- R4: inflection-review reason strictly concise English (max 12 words).
- R5: topic post-guard (abstract re-anchor + gender never Animals).
- R6: diff reporter renders N precards per lemma side-by-side.
"""

import json
import re

from factory.pipeline import card_pilot
from factory.pipeline import precard_pipeline

LONG_EXAMPLE = ("She eats a fresh red apple every single morning "
                "with her family")


def _idx(entries):
    def read_entry(row):
        return row["entry"]
    return entries, read_entry


def make_multi_index():
    """Two-sense lemma entries: sense 0 has examples, sense 1 has none."""
    def rows(glosses_examples, ipa):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                           "senses": [
                               {"glosses": [g], "tags": [],
                                "examples": ([{"text": e}] if e else [])}
                               for g, e in glosses_examples]}}]
    return {
        "call": rows([("a telephone conversation", ""),
                      ("to shout loudly", LONG_EXAMPLE)], "/kɔːl/"),
        "for": rows([("intended for a purpose", ""),
                     ("in favor of something", LONG_EXAMPLE)], "/fɔːr/"),
    }


# ---------------- R1: multi-pick judge + fan-out ----------------

def test_r1_judge_validate_accepts_multi_picks():
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    anchor_map = {"w:call": {"candidates": [
        {"sense_id": "call#0", "gloss": "a telephone conversation"},
        {"sense_id": "call#1", "gloss": "to shout loudly"}]}}
    data = {"results": [{"key": "w:call",
                         "picks": ["call#1", "call#0"]}]}
    out = precard_pipeline.judge_validate_multi(data, batch, anchor_map)
    assert set(out) == {"w:call"}
    got = [p["sense_id"] for p in out["w:call"]["picks"]]
    assert got == ["call#1", "call#0"]


def test_r1_judge_validate_rejects_unknown_and_caps_at_four():
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    cands = [{"sense_id": "call#%d" % i, "gloss": "sense %d" % i}
             for i in range(6)]
    anchor_map = {"w:call": {"candidates": cands}}
    data = {"results": [{"key": "w:call", "picks": [
        "call#0", "call#9", "call#1", "call#1", "call#2",
        "call#3", "call#4", "call#5"]}]}
    out = precard_pipeline.judge_validate_multi(data, batch, anchor_map)
    got = [p["sense_id"] for p in out["w:call"]["picks"]]
    assert got == ["call#0", "call#1", "call#2", "call#3"]
    assert len(got) <= 4


def test_r1_fanout_picks_returns_ordered_picks():
    pick_entry = {"sense_id": "call#1", "gloss": "to shout loudly",
                  "model": "m",
                  "picks": [{"sense_id": "call#1",
                             "gloss": "to shout loudly"},
                            {"sense_id": "call#0",
                             "gloss": "a telephone conversation"}]}
    rows = precard_pipeline.fanout_picks(
        {"kind": "word", "text": "call", "pool_level": "A1"}, pick_entry)
    assert [r["sense_id"] for r in rows] == ["call#1", "call#0"]
    # Distinct senses hash to distinct stable card ids.
    ids = {precard_pipeline.compute_pre_card_id(
        "call", "noun", r["gloss"]) for r in rows}
    assert len(ids) == 2
    assert all(len(i) == 16 for i in ids)


def _two_pick_judge(api_key, model, user_text):
    """S2-shape reply: two picks per KEY section (v14.1 multi-pick)."""
    keys, cands, cur = [], {}, None
    for line in user_text.splitlines():
        hit = re.match(r"^KEY (\S+)", line)
        if hit:
            cur = hit.group(1)
            keys.append(cur)
            cands[cur] = []
        pick = re.match(r"^- (\S+#\d+)", line)
        if pick and cur:
            cands[cur].append(pick.group(1))
    return json.dumps({"results": [
        {"key": k, "picks": cands[k][:2]} for k in keys]})


def test_r1_pipeline_fans_out_two_rows_per_lemma(tmp_path, monkeypatch):
    import pathlib
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(
        [{"kind": "word", "text": "call", "pool_level": "A1"}]),
        encoding="utf-8")
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    index, read_entry = _idx(make_multi_index())
    rc = precard_pipeline.main(
        ["--sample", str(sample), "--out", out, "--progress-dir", prog],
        _judge_transport=_two_pick_judge, _topic_transport=None,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index=index, _read_entry=read_entry, _tatoeba={})
    assert rc == 0
    with open(out, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    assert len(rows) == 2
    assert {r["sense_id"] for r in rows} == {"call#0", "call#1"}
    assert len({r["pre_card_id"] for r in rows}) == 2
    assert {r["pick_index"] for r in rows} == {0, 1}
    assert all(r["fanout_n"] == 2 for r in rows)


def test_pacing_flag_defaults_and_parses_zero():
    assert precard_pipeline.parse_args([]).sleep_secs == 2.5
    assert precard_pipeline.parse_args(["--sleep-secs", "0"]).sleep_secs == 0


# ---------------- R2: no silent dropout ----------------

def test_r2_proper_names_drop_with_verdict_not_silently():
    for text in ("Rundle", "Telemark"):
        item = {"kind": "word", "text": text, "pool_level": "C2"}
        verdict = precard_pipeline.preprocess_classify_item(
            item, {text.lower(): {"propn"}}, lambda t: 4.0, set(), {},
            False, entry_fn=lambda t: None)
        assert verdict["kept"] is False
        assert (verdict["reason"] or "").strip() != ""


def test_r2_abbrevs_drop_with_structured_g4_verdict():
    for text in ("FEB", "FDR"):
        item = {"kind": "word", "text": text, "pool_level": "B1"}
        view = {"poss": {"noun"},
                "senses": [{"gloss": "abbreviation of something",
                            "tags": ["abbreviation"]}]}
        verdict = precard_pipeline.preprocess_classify_item(
            item, {text.lower(): {"noun"}}, lambda t: 4.0, set(), {},
            False, entry_fn=lambda t: view)
        assert verdict["kept"] is False
        assert (verdict["reason"] or "").startswith("g4-abbrev")


def test_r2_accounting_audit_flags_unaccounted_keys():
    items = [{"kind": "word", "text": "FEB", "pool_level": "B1"},
             {"kind": "word", "text": "apple", "pool_level": "A1"}]
    precards = {"w:apple": {"key": "w:apple"}}
    states = {"s0": {"done": {
        "w:FEB": {"kept": False, "reason": "g4-abbrev"},
        "w:apple": {"kept": True, "reason": None}}, "failed": ["w:FEB"]}}
    missing = precard_pipeline.audit_sample_accounting(
        items, precards, states)
    assert missing == []
    missing = precard_pipeline.audit_sample_accounting(items, {}, states)
    assert missing == ["w:apple"]


# ---------------- R3: example fallback ----------------

def test_r3_picked_sense_without_examples_falls_back_to_lemma():
    index, read_entry = _idx(make_multi_index())
    item = {"kind": "word", "text": "call", "pool_level": "A1"}
    pick = {"sense_id": "call#0", "gloss": "a telephone conversation"}
    out = precard_pipeline.enrich_item(
        item, pick, index, read_entry, {}, phrase_entry=None)
    assert out["dataset_examples"] != []
    assert any("apple" in e and "morning" in e
               for e in out["dataset_examples"])
    assert out.get("example_synthetic_needed") in (False, None)


def test_r3_no_examples_anywhere_flags_synthetic_for_a1():
    index = {"zzq": [{"pos": "noun",
                      "entry": {"pos": "noun", "sounds": [],
                                "senses": [{"glosses": ["a thing"],
                                            "tags": [],
                                            "examples": []}]}}]}

    def read_entry(row):
        return row["entry"]

    item = {"kind": "word", "text": "zzq", "pool_level": "A1"}
    pick = {"sense_id": "zzq#0", "gloss": "a thing"}
    out = precard_pipeline.enrich_item(
        item, pick, index, read_entry, {}, phrase_entry=None)
    assert out.get("example_synthetic_needed") is True


# ---------------- R4: strict English rationale ----------------

def test_r4_inflection_review_reason_strict_english():
    sys_text = card_pilot.INFLECTION_REVIEW_SYS
    assert "Persian may be used" not in sys_text
    assert re.search(r"12 words", sys_text) is not None
    assert "English" in sys_text


# ---------------- R5: topic guardrails ----------------

def test_r5_gender_never_maps_to_animals():
    for gloss in ("the biological sex of a person",
                  "the socially constructed roles of men and women"):
        label = card_pilot.topic_post_guard(
            "gender", gloss, "Animals & Living Beings")
        assert label in ("Society & Culture", "Health & Body"), gloss


def test_r5_functional_concepts_not_dumped_to_abstract():
    cases = [("call", "a telephone conversation", "Science & Technology"),
             ("working", "paid employment", "Work & Education"),
             ("spectacle", "a public performance", "Society & Culture"),
             ("accrue", "to accumulate money", "Business & Economy"),
             ("elevate", "to lift something up", "Daily Life & Home")]
    for lemma, gloss, want in cases:
        assert card_pilot.topic_post_guard(
            lemma, gloss, "Other / Abstract") == want


def test_r5_guard_passes_through_real_abstracts():
    assert card_pilot.topic_post_guard(
        "about", "on the subject of", "Other / Abstract") == \
        "Other / Abstract"


# ---------------- R6: side-by-side diff ----------------

def test_r6_diff_renders_all_fanout_cards_side_by_side():
    recs = [
        {"key": "w:call", "text": "call", "sense_id": "call#1",
         "en_def": "to shout loudly", "pre_card_id": "a" * 16,
         "topic_vector": [{"label": "Society & Culture",
                           "weight": 1.0}]},
        {"key": "w:call", "text": "call", "sense_id": "call#0",
         "en_def": "a telephone conversation", "pre_card_id": "b" * 16,
         "topic_vector": [{"label": "Science & Technology",
                           "weight": 1.0}]},
    ]
    html = card_pilot.render_lemma_fanout(recs)
    assert "call#1" in html and "call#0" in html
    assert "fanout-side-by-side" in html
