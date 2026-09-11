"""Red-first tests for the form-of-driven anchor fixes (one PR).

Items (factory/ only, zero LLM):
1. form-of weight ZERO in S1 scorer: tagged form-of senses sort below
   every real sense (going drops, charming verb-sense buried, adj wins).
2. Regex fix: "present participle and gerund of X" + "comparative /
   superlative degree of X" detected as inflection stubs.
3. Stub-free S2 window: stub senses excluded from the judge candidate
   window (fail-closed to full list when all-stub); prompt unchanged.
4. mother_lemma emission in S1 from sense form_of[].word (singleton ->
   string, multi -> list + flag); precard row carries it (additive).
5. Country blocklist untouched (covered by existing tests; asserted here
   as a tripwire on the reason slug).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "factory"))
import card_pilot
import precard_pipeline
from precard_pipeline import anchor_rank_item
from precard_pipeline import main as precard_main

ZIPF = lambda w: 5.0  # noqa: E731 (hermetic: never touch wordfreq live)


def read_entry(row):
    return row["entry"]


def _sense(gloss, tags=(), form_of=None):
    d = {"glosses": [gloss], "tags": list(tags), "examples": []}
    if form_of is not None:
        d["form_of"] = form_of
    return d


def _rows(pos, senses):
    return [{"pos": pos,
             "entry": {"pos": pos, "sounds": [],
                       "senses": senses}}]


# --- Item 1: form-of weight ZERO in score_senses -------------------------


def test_going_stub_drops_below_real():
    """going#0 (form-of stub, file-first) must not anchor: a real sense
    later in file order wins."""
    entries = _rows("verb", [
        _sense("present participle and gerund of go",
               tags=["form-of", "present", "participle"],
               form_of=[{"word": "go"}]),
        _sense("the act of leaving", tags=[]),
    ])
    scored = card_pilot.score_senses("going", entries, "", read_entry,
                                     zipf_fn=ZIPF)
    assert scored[0][4] == "the act of leaving"


def test_charming_verb_stub_buried_adj_wins():
    """charming verb form-of sense (file-first) buries below the real
    adjective block."""
    entries = (
        _rows("verb", [
            _sense("present participle of charm", tags=["form-of"],
                   form_of=[{"word": "charm"}]),
        ]) + _rows("adjective", [
            _sense("pleasant and attractive", tags=[]),
        ])
    )
    scored = card_pilot.score_senses("charming", entries, "", read_entry,
                                     zipf_fn=ZIPF)
    assert scored[0][4] == "pleasant and attractive"


def test_s1_anchor_top_is_real_for_going():
    ranked = anchor_rank_item(
        {"kind": "word", "text": "going", "pos": "", "pool_level": "A1"},
        {"going": _rows("verb", [
            _sense("present participle and gerund of go",
                   tags=["form-of"],
                   form_of=[{"word": "go"}]),
            _sense("the act of leaving", tags=[]),
        ])},
        read_entry)
    assert ranked["top"]["gloss"] == "the act of leaving"


# --- Item 2: inflection-stub regex ---------------------------------------


def test_inflection_regex_covers_participle_gerund_and_degree():
    assert card_pilot.is_inflection_gloss(
        "present participle and gerund of force") is True
    assert card_pilot.is_inflection_gloss(
        "comparative degree of good") is True
    assert card_pilot.is_inflection_gloss(
        "superlative degree of bad") is True
    # Regression: previously covered shapes still match ...
    assert card_pilot.is_inflection_gloss(
        "present participle of force") is True
    assert card_pilot.is_inflection_gloss("plural of cat") is True
    # ... and real prose still does not.
    assert card_pilot.is_inflection_gloss("a comparative study") is False


def test_s0b_and_f4_veto_share_new_shapes():
    """S0b verdict path and the F4 veto inherit the shared predicate."""
    assert precard_pipeline._is_veto_stub_gloss(
        "present participle and gerund of force") is True
    assert precard_pipeline._is_veto_stub_gloss(
        "comparative degree of good") is True


# --- Item 3: stub-free S2 window ------------------------------------------


def test_judge_window_excludes_stub_senses():
    entries = _rows("noun", [
        _sense("the act of compelling", tags=[]),
        _sense("present participle of force", tags=["form-of"],
               form_of=[{"word": "force"}]),
    ])
    scored = card_pilot.score_senses("forcing", entries, "noun",
                                     read_entry, zipf_fn=ZIPF)
    window = card_pilot.select_candidate_window(scored, "noun", "B1",
                                                cap=10)
    assert [t[4] for t in window] == ["the act of compelling"]
    cands = card_pilot.top_sense_candidates(
        "forcing", entries, "noun", read_entry, k=3, zipf_fn=ZIPF,
        pool_level="B1", window_cap=10)
    assert [c["gloss"] for c in cands] == ["the act of compelling"]


def test_judge_window_gloss_only_stub_excluded():
    """A stub gloss with NO tags is still excluded (gloss leg)."""
    entries = _rows("verb", [
        _sense("to think about", tags=[]),
        _sense("present participle of wonder", tags=[]),
    ])
    scored = card_pilot.score_senses("wondering", entries, "verb",
                                     read_entry, zipf_fn=ZIPF)
    window = card_pilot.select_candidate_window(scored, "verb", "B1",
                                                cap=10)
    assert [t[4] for t in window] == ["to think about"]


def test_judge_window_all_stub_keeps():
    """Fail-closed: an all-stub window keeps every candidate."""
    entries = _rows("verb", [
        _sense("past of go", tags=["form-of"],
               form_of=[{"word": "go"}]),
        _sense("past participle of go", tags=["form-of"],
               form_of=[{"word": "go"}]),
    ])
    scored = card_pilot.score_senses("went", entries, "verb",
                                     read_entry, zipf_fn=ZIPF)
    window = card_pilot.select_candidate_window(scored, "verb", "A1",
                                                cap=10)
    assert len(window) == 2


def test_judge_prompt_template_unchanged():
    import inspect
    src = inspect.getsource(precard_pipeline._judge_prompt)
    assert "PICK the single most useful sense per item" in src
    assert "candidate ids" in src


# --- Item 4: mother_lemma emission ----------------------------------------


def test_mother_singleton_is_string():
    mother, mothers, multi = card_pilot.parse_mother_lemma(
        {"form_of": [{"word": "go"}]})
    assert mother == "go"
    assert mothers == ["go"]
    assert multi is False


def test_mother_multi_is_list_plus_flag():
    mother, mothers, multi = card_pilot.parse_mother_lemma(
        {"form_of": [{"word": "good"}, {"word": "well"}]})
    assert mother == "good"
    assert mothers == ["good", "well"]
    assert multi is True


def test_mother_missing_is_empty():
    mother, mothers, multi = card_pilot.parse_mother_lemma({})
    assert mother == ""
    assert mothers == []
    assert multi is False


def test_mother_cleans_like_superlative_parser():
    mother, mothers, multi = card_pilot.parse_mother_lemma(
        {"form_of": [{"word": '"Go."'}]})
    assert mother == "Go"
    assert mothers == ["Go"]
    assert multi is False
    # Dataset multi-target shape (better#0 form_of=[{word:
    # "good and well"}]): one string splits into a mothers list.
    mother, mothers, multi = card_pilot.parse_mother_lemma(
        {"form_of": [{"word": "good and well"}]})
    assert (mother, mothers, multi) == ("good", ["good", "well"], True)


def test_s1_ranked_carries_mother_fields():
    ranked = anchor_rank_item(
        {"kind": "word", "text": "went", "pos": "verb",
         "pool_level": "A1"},
        {"went": _rows("verb", [
            _sense("past of go", tags=["form-of"],
                   form_of=[{"word": "go"}]),
        ])},
        read_entry)
    assert ranked["mother_lemma"] == "go"
    assert ranked["mother_lemmas"] == ["go"]
    assert ranked["mother_multi"] is False


def test_precard_row_carries_mother_lemma(tmp_path, monkeypatch):
    """End-to-end (no LLM): the precard row for a tag-only form-of
    lemma (form-of tag, non-stub gloss — survives G2/S0b on its tags)
    carries the additive mother fields."""
    import re
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    items = [{"kind": "word", "text": "went", "pos": "verb",
              "pool_level": "A1"}]
    index = {"went": _rows("verb", [
        _sense("to leave", tags=["form-of"],
               form_of=[{"word": "go"}]),
    ])}
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(items), encoding="utf-8")
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")

    def stub_judge(api_key, model, user_text):
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
            {"key": k, "pick": (cands[k][0] if cands[k] else "")}
            for k in keys]})

    def fake_topics(api_key, model, user_text):
        lemmas, cur = {}, None
        for line in user_text.splitlines():
            hit = re.match(r"^LEMMA (.+):$", line)
            if hit:
                cur = hit.group(1)
                lemmas[cur] = []
            pick = re.match(r"^- (\S+)", line)
            if pick and cur is not None:
                lemmas[cur].append(pick.group(1))
        return json.dumps({"results": [
            {"lemma": lemma,
             "vectors": [{"sense_id": sid,
                          "vector": [{"topic_id": 16,
                                      "topic_label": "Other / Abstract",
                                      "weight": 1.0}]}
                         for sid in sids]}
            for lemma, sids in lemmas.items()]})

    rc = precard_main(
        ["--sample", str(sample), "--out", out, "--progress-dir", prog],
        _judge_transport=stub_judge, _topic_transport=fake_topics,
        _assign_transport=None, _inflect_transport=None,
        _sleep_fn=lambda s: None, _index=index, _read_entry=read_entry,
        _tatoeba={}, _zipf_fn=lambda t: 5.0)
    assert rc == 0
    with open(out, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    assert len(rows) == 1
    assert rows[0]["mother_lemma"] == "go"
    assert rows[0]["mother_lemmas"] == ["go"]
    assert rows[0]["mother_multi"] is False


# --- Item 5: country blocklist untouched ----------------------------------


def test_country_blocklist_reason_still_wired():
    from precard_pipeline import COUNTRY_NAMES
    assert "france" in COUNTRY_NAMES
    from stage_glossary import REASON_SLUGS
    assert "r4-country-blocklist" in REASON_SLUGS
