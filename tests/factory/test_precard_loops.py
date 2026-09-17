"""Identity T4b: network loops live in the new home, parity-pinned.

judge_batch/vectors_batch/label_batch/inflection_review run from
factory.precard with injected transports; archive validators agree
byte-for-byte with the new copies.
"""

import json
import re
import urllib.error

from factory.precard import judge, topics, transport


def _anchor(*senses):
    return {"w:call": {"candidates": [
        {"sense_id": sid, "gloss": gloss} for sid, gloss in senses]}}


def fake_judge(api_key, model, user_text):
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


def test_judge_batch_fallback_shape_in_new_home():
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = _anchor(("call#0", "a telephone conversation"))

    def boom(api_key, model, text):
        raise urllib.error.HTTPError(
            "u", 500, "x", {}, None)

    out = judge.judge_batch(batch, amap, "k", boom, lambda s: None, {})
    assert out["w:call"]["model"] == "s1-fallback"
    assert out["w:call"]["sense_id"] == "call#0"


def test_judge_batch_model_shape_in_new_home():
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    amap = _anchor(("call#0", "a telephone conversation"))
    out = judge.judge_batch(batch, amap, "k", fake_judge,
                            lambda s: None, {})
    assert out["w:call"]["sense_id"] == "call#0"
    assert not out["w:call"]["model"].startswith("s1-")


def test_validators_agree_with_archive():
    from factory.archive.v14_v16 import run_v15_topics as v15
    from factory.archive.v14_v16 import run_v16b_topup as topup
    vecs = [{"sense_id": "call#0",
             "vector": [{"topic_id": 16,
                         "topic_label": "Other / Abstract",
                         "weight": 1.0}]}]
    assert topics.validate_vectors(
        vecs, {"lemma": "call",
               "ranked_senses": [{"sense_id": "call#0"}]}) == \
        v15.validate_vectors(
            vecs, {"lemma": "call",
                   "ranked_senses": [{"sense_id": "call#0"}]})
    rows = [{"sense_id": "call#0", "topic_id": 16,
             "topic_label": "Other / Abstract", "confidence": 0.9,
             "vector": [{"topic_id": 16,
                         "topic_label": "Other / Abstract",
                         "weight": 1.0}]}]
    assert topics.validate_senses(rows, ["call#0"]) == \
        topup.validate_senses(rows, ["call#0"])


def test_label_batch_basic_in_new_home():
    """R3 locked: LLM-only — transport=None leaves rows UNLABELLED."""
    batch = [{"kind": "word", "text": "apple", "pool_level": "A1"}]
    picks = {"w:apple": {"sense_id": "apple#9", "gloss": "a thing"}}
    out = topics.label_batch(
        batch, picks, None, "k", None, lambda s: None, {}, "/none",
        {})
    assert out["w:apple"]["label"] is None
    assert out["w:apple"]["topic_path"] == "unlabelled"
    # The 5-lemma guard is a post-correction on LLM output only: with
    # no LLM leg there is no label to re-anchor (stays unlabelled).
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    picks = {"w:call": {"sense_id": "call#0",
                        "gloss": "a telephone conversation"}}
    out = topics.label_batch(
        batch, picks, None, "k", None, lambda s: None, {}, "/none",
        {})
    assert out["w:call"]["label"] is None
    assert out["w:call"]["topic_path"] == "unlabelled"


def test_inflection_review_failure_keeps():
    items = [{"key": "w:forced", "text": "forced",
              "gloss": "past of force"}]

    def boom(api_key, model, sys_text, user_text):
        raise urllib.error.HTTPError("u", 500, "x", {}, None)

    out = judge.inflection_review(items, boom, "k",
                                  sleep_fn=lambda s: None, state={})
    assert out["w:forced"]["keep"] is True
    assert out["w:forced"]["uncertain"] is True


# ---------------- R8: s0b every-gloss pre-check ----------------

def _r8_review_transport(calls, verdicts=None):
    """Fake verdict leg: records prompts, answers keep per key."""
    verdicts = verdicts or {}

    def fake(api_key, model, sys_text, user_text):
        calls.append(user_text)
        keys = re.findall(r"^KEY (\S+)", user_text, re.M)
        return json.dumps({"results": [
            {"key": k, "keep": verdicts.get(k, (True, ""))[0],
             "reason": verdicts.get(k, (True, ""))[1]} for k in keys]})
    return fake


def _r8_listed_map():
    # "listed" died although its adjective sense is real B2 vocabulary.
    return {"w:listed": {"candidates": [
        {"sense_id": "listed#0", "gloss": "past of list"},
        {"sense_id": "listed#1",
         "gloss": "recorded on an official list, as a listed building"}]}}


def test_r8_listed_like_skips_llm():
    items = [{"key": "w:listed", "text": "listed",
              "gloss": "past of list"}]
    calls = []
    out = judge.inflection_review(
        items, _r8_review_transport(calls), "k",
        sleep_fn=lambda s: None, state={},
        anchor_map=_r8_listed_map())
    assert out["w:listed"] == {
        "keep": True, "reason": "review-has-independent-sense",
        "model": "review-precheck", "uncertain": False}
    assert calls == []  # no model call burned


def test_r8_all_stub_still_llm_drop():
    items = [{"key": "w:cats", "text": "cats",
              "gloss": "plural of cat"}]
    amap = {"w:cats": {"candidates": [
        {"sense_id": "cats#0", "gloss": "plural of cat"}]}}
    calls = []
    out = judge.inflection_review(
        items, _r8_review_transport(
            calls, {"w:cats": (False, "regular plural, use cat")}),
        "k", sleep_fn=lambda s: None, state={}, anchor_map=amap)
    assert out["w:cats"]["keep"] is False
    assert out["w:cats"]["uncertain"] is False
    assert len(calls) == 1  # LLM verdict path preserved


def test_r8_name_rows_excluded():
    # Stub + name-only: no independent sense -> still reviewed (R2: R4
    # keeps sole ownership of name-only entries).
    items = [{"key": "w:streets", "text": "streets",
              "gloss": "plural of street"}]
    amap = {"w:streets": {"candidates": [
        {"sense_id": "streets#0", "gloss": "plural of street"},
        {"sense_id": "streets#1", "gloss": "A surname"}]}}
    calls = []
    out = judge.inflection_review(
        items, _r8_review_transport(calls), "k",
        sleep_fn=lambda s: None, state={}, anchor_map=amap)
    assert out["w:streets"]["keep"] is True
    assert out["w:streets"]["model"] != "review-precheck"
    assert len(calls) == 1
    # Stub + name + one real sense -> the name is ignored, the real
    # sense keeps without a call.
    amap["w:streets"]["candidates"].append(
        {"sense_id": "streets#2",
         "gloss": "a public road in a town"})
    calls2 = []
    out = judge.inflection_review(
        items, _r8_review_transport(calls2), "k",
        sleep_fn=lambda s: None, state={}, anchor_map=amap)
    assert out["w:streets"]["reason"] == "review-has-independent-sense"
    assert calls2 == []


def test_r8_mixed_stubs_plus_real_keeps():
    # Verb stub + plural-noun stub + one real sense ("plants"/"briefs").
    items = [{"key": "w:plants", "text": "plants",
              "gloss": "plural of plant"}]
    amap = {"w:plants": {"candidates": [
        {"sense_id": "plants#0",
         "gloss": "third person singular of plant"},
        {"sense_id": "plants#1", "gloss": "plural of plant"},
        {"sense_id": "plants#2",
         "gloss": "a living organism growing in soil"}]}}
    calls = []
    out = judge.inflection_review(
        items, _r8_review_transport(calls), "k",
        sleep_fn=lambda s: None, state={}, anchor_map=amap)
    assert out["w:plants"]["keep"] is True
    assert out["w:plants"]["reason"] == "review-has-independent-sense"
    assert calls == []


def test_r8_pos_carrying_name_row_excluded_pipeline_shape():
    # Pipeline-built shape {gloss, pos} (no sense_id): a proper-noun
    # sense with a non-name-pattern gloss is still a name row via the
    # POS leg (live in prod now that the projection threads per-sense
    # pos) — stub + pos-name only still reviews via LLM.
    items = [{"key": "w:deutsch", "text": "deutsch",
              "gloss": "plural of deutsch"}]
    amap = {"w:deutsch": {"candidates": [
        {"gloss": "plural of deutsch", "pos": "noun"},
        {"gloss": "the German language", "pos": "propn"}]}}
    calls = []
    out = judge.inflection_review(
        items, _r8_review_transport(calls), "k",
        sleep_fn=lambda s: None, state={}, anchor_map=amap)
    assert out["w:deutsch"]["model"] != "review-precheck"
    assert len(calls) == 1
    # Same map plus one real non-name sense -> precheck keeps, no call.
    amap["w:deutsch"]["candidates"].append(
        {"gloss": "a living organism growing in soil", "pos": "noun"})
    calls2 = []
    out = judge.inflection_review(
        items, _r8_review_transport(calls2), "k",
        sleep_fn=lambda s: None, state={}, anchor_map=amap)
    assert out["w:deutsch"]["reason"] == "review-has-independent-sense"
    assert calls2 == []


def test_r8_blank_gloss_fails_open_to_review():
    # A blank gloss never counts as independent — stub + empty still
    # reviews via LLM (empties fail open, never skip review).
    items = [{"key": "w:listed", "text": "listed",
              "gloss": "past of list"}]
    amap = {"w:listed": {"candidates": [
        {"sense_id": "listed#0", "gloss": "past of list"},
        {"sense_id": "listed#1", "gloss": ""}]}}
    calls = []
    out = judge.inflection_review(
        items, _r8_review_transport(calls), "k",
        sleep_fn=lambda s: None, state={}, anchor_map=amap)
    assert out["w:listed"]["model"] != "review-precheck"
    assert len(calls) == 1


def test_r8_fail_open_without_map():
    # No map (or unknown key / empty candidates): current behavior —
    # the item reviews via LLM.
    items = [{"key": "w:listed", "text": "listed",
              "gloss": "past of list"}]
    for amap in (None, {}, {"w:other": {"candidates": []}},
                 {"w:listed": {"candidates": []}}):
        calls = []
        out = judge.inflection_review(
            items, _r8_review_transport(calls), "k",
            sleep_fn=lambda s: None, state={}, anchor_map=amap)
        assert out["w:listed"]["keep"] is True
        assert out["w:listed"]["model"] != "review-precheck"
        assert len(calls) == 1


def test_r8_savings_all_skip_no_batch():
    # Fixture: 3 review items, each with an independent sense — before
    # (no map) 1 prompt batch burns; after (map) 0 calls.
    items = [
        {"key": "w:listed", "text": "listed", "gloss": "past of list"},
        {"key": "w:plants", "text": "plants", "gloss": "plural of plant"},
        {"key": "w:briefs", "text": "briefs", "gloss": "plural of brief"}]
    amap = {
        "w:listed": {"candidates": [
            {"sense_id": "listed#0", "gloss": "past of list"},
            {"sense_id": "listed#1", "gloss": "officially recorded"}]},
        "w:plants": {"candidates": [
            {"sense_id": "plants#0", "gloss": "plural of plant"},
            {"sense_id": "plants#1",
             "gloss": "a living organism growing in soil"}]},
        "w:briefs": {"candidates": [
            {"sense_id": "briefs#0", "gloss": "plural of brief"},
            {"sense_id": "briefs#1",
             "gloss": "short underpants"}]}}
    before_calls, after_calls = [], []
    judge.inflection_review(items, _r8_review_transport(before_calls), "k",
                            sleep_fn=lambda s: None, state={})
    out = judge.inflection_review(
        items, _r8_review_transport(after_calls), "k",
        sleep_fn=lambda s: None, state={}, anchor_map=amap)
    assert len(before_calls) == 1
    assert after_calls == []
    assert all(v["keep"] is True for v in out.values())
    assert {v["reason"] for v in out.values()} == \
        {"review-has-independent-sense"}


def test_live_labels_match_archive_registry():
    from factory.archive.v14_v16 import run_v16b_topup as topup
    assert topics.LABELS == topup.LABELS16
    assert transport.RETRY_PREFIX  # shared retry line present
    assert topics.LABEL_BATCH == 16
    assert judge.JUDGE_BATCH == 12
