"""Identity T4c: enrich + pipeline in the new home, equivalence-pinned.

New-home enrich matches old-home enrich field-for-field on fixtures;
the new pipeline reproduces the old precard rows (plus additive v14.1
fields) on a hermetic run with fake transports.
"""

import json
import re

from factory.precard import enrich as new_enrich


def _idx():
    def rows(glosses, ipa):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": [{"text": (
                                           "She eats a fresh red apple "
                                           "every single morning "
                                           "with her family")}]}
                                      for g in glosses]}}]
    index = {"apple": rows(["a round fruit", "a tech company"], "/aɪpa/")}

    def read_entry(row):
        return row["entry"]

    return index, read_entry


def test_enrich_apple_baseline():
    """Cutover baseline (ex-parity): the apple pick enriches
    deterministically from the committed packs. Field-by-field parity
    vs the old home was proven by the passing old-vs-new run before
    the old module was deleted (PR #697)."""
    index, read_entry = _idx()
    item = {"kind": "word", "text": "apple", "pool_level": "A1"}
    pick = {"sense_id": "apple#0", "gloss": "a round fruit"}
    out = new_enrich.enrich_item(item, pick, index, read_entry, {})
    assert out["sense_id"] == "apple#0"
    assert out["en_def"] == "a round fruit"
    assert (out["ipa"], out["ipa_src"]) == ("/aɪpa/", "dataset")
    assert out["abbrev_expansion"] == ""
    assert out["pos"] == ["noun"] and out["pos_src"] == "dataset"
    assert out["lexical_type"] == "word" and out["register"] == "neutral"
    assert (out["sense_cefr"], out["sense_cefr_method"]) == ("A1",
                                                             "wn-single")
    assert out["enrich_path"] == "partial"
    assert out["dataset_examples"] == [
        "She eats a fresh red apple every single morning with her family"]
    assert len(out["pre_card_id"]) == 16


def _fake_judge(api_key, model, user_text):
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


def _fake_topics(api_key, model, user_text):
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


def _fake_inflect(api_key, model, sys_text, user_text):
    """S0b-shape reply: keep every KEY section (no inflection drops)."""
    keys, cur = [], None
    for line in user_text.splitlines():
        hit = re.match(r"^KEY (\S+)", line)
        if hit:
            cur = hit.group(1)
            keys.append(cur)
    return json.dumps({"results": [
        {"key": k, "keep": True, "reason": "test keep"} for k in keys]})


def test_pipeline_apple_row_baseline(tmp_path):
    """Cutover baseline (ex-parity): the hermetic single-apple run pins
    the row. Old-vs-new row equality was proven by the passing parity
    run before the old module was deleted (PR #697)."""
    from factory.precard import pipeline as new

    items = [{"kind": "word", "text": "apple", "pos": "noun",
              "pool_level": "A1"}]
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(items), encoding="utf-8")
    index, read_entry = _idx()
    kwargs = dict(
        _judge_transport=_fake_judge, _topic_transport=_fake_topics,
        _assign_transport=None, _inflect_transport=_fake_inflect,
        _sleep_fn=lambda s: None,
        _index=index, _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0, _awl_set=set(), _type_map={},
        _type_log_available=False)
    out_new = str(tmp_path / "new.jsonl")
    prog_new = str(tmp_path / "prog_new")
    assert new.main(["--sample", str(sample), "--out", out_new,
                     "--progress-dir", prog_new], **kwargs) == 0

    def rows(path):
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    new_rows = rows(out_new)
    assert len(new_rows) == 1
    row = new_rows[0]
    assert row["key"] == "w:apple"
    assert row["sense_id"] == "apple#0"  # fake judge picks 1st candidate
    assert row["en_def"] == "a round fruit"
    assert row["topic_vector"] == [{"label": "Other / Abstract",
                                    "weight": 1.0}]
    assert row["topic_method"] == "v16b-exact"
    assert row["ipa_src"] == "dataset"
    assert row["drop_reason"] is None
    assert row["pos"] == ["noun"] and row["pos_src"] == "dataset"
    assert row["sense_cefr"] == "A1"
    assert len(row["pre_card_id"]) == 16
