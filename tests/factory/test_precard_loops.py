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
    batch = [{"kind": "word", "text": "apple", "pool_level": "A1"}]
    picks = {"w:apple": {"sense_id": "apple#9", "gloss": "a thing"}}
    out = topics.label_batch(
        batch, picks, None, "k", None, lambda s: None, {}, "/none",
        {}, lookup=lambda text, gloss: None)
    assert out["w:apple"]["label"] == "Other / Abstract"
    assert out["w:apple"]["topic_path"] == "fallback"
    # The R5 guard rewires a fallback Other on a telephone gloss.
    batch = [{"kind": "word", "text": "call", "pool_level": "A1"}]
    picks = {"w:call": {"sense_id": "call#0",
                        "gloss": "a telephone conversation"}}
    out = topics.label_batch(
        batch, picks, None, "k", None, lambda s: None, {}, "/none",
        {}, lookup=lambda text, gloss: None)
    assert out["w:call"]["label"] == "Science & Technology"


def test_inflection_review_failure_keeps():
    items = [{"key": "w:forced", "text": "forced",
              "gloss": "past of force"}]

    def boom(api_key, model, sys_text, user_text):
        raise urllib.error.HTTPError("u", 500, "x", {}, None)

    out = judge.inflection_review(items, boom)
    assert out["w:forced"]["keep"] is True
    assert out["w:forced"]["uncertain"] is True


def test_live_labels_match_archive_registry():
    from factory.archive.v14_v16 import run_v16b_topup as topup
    assert topics.LABELS == topup.LABELS16
    assert transport.RETRY_PREFIX  # shared retry line present
    assert topics.LABEL_BATCH == 16
    assert judge.JUDGE_BATCH == 12
