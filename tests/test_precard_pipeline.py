"""Hermetic tests for factory/precard_pipeline.py (R22-R25) + the
card_pilot --from-precard wire.

No network, no W:, no real keys: kaikki index/read_entry, judge/topic
transports, and sleeps are all injected fakes. The S1/S4/S5 owner paths
(card_pilot) and the S2/S3 judge paths (run_v14_phase3_judge /
run_v15_topics) run for real through their imports.
"""

import json
import os
import pathlib
import re
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "factory"))
import card_pilot
import precard_pipeline
from precard_pipeline import main as precard_main

ITEMS = [
    {"kind": "word", "text": "apple", "pos": "noun", "pool_level": "A1"},
    {"kind": "phrase", "text": "give up", "pool_level": "B1"},
]

LONG_EXAMPLE = ("She eats a fresh red apple every single morning "
                "with her family")


def make_index():
    def rows(word, glosses, ipa):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": [{"text": LONG_EXAMPLE}]}
                                      for g in glosses]}}]
    return {
        "apple": rows("apple", ["a round fruit", "a tech company"], "/aɪpa/"),
        "give": rows("give", ["to hand over"], "/ɡɪv/"),
        "up": rows("up", ["toward the sky"], "/ʌp/"),
    }


def read_entry(row):
    return row["entry"]


def fake_judge(api_key, model, user_text):
    """S2-shape reply: first candidate id per KEY section."""
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
    """v15-shape reply: every sense -> Other / Abstract @1.0."""
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


def write_sample(tmp_path, items=ITEMS):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(items), encoding="utf-8")
    return str(sample)


def run_pipeline(tmp_path, monkeypatch, judge=fake_judge,
                 topics=fake_topics, extra=(), items=ITEMS,
                 zipf_fn=None, awl_set=None, type_map=None):
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path, items)
    out = str(tmp_path / "precard.jsonl")
    prog = str(tmp_path / "prog")
    sleeps = []
    kwargs = {}
    if zipf_fn is not None:
        kwargs["_zipf_fn"] = zipf_fn
    if awl_set is not None:
        kwargs["_awl_set"] = awl_set
    if type_map is not None:
        kwargs["_type_map"] = type_map
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog,
         *extra],
        _judge_transport=judge, _topic_transport=topics,
        _assign_transport=None, _sleep_fn=sleeps.append,
        _index=make_index(), _read_entry=read_entry, _tatoeba={},
        **kwargs)
    return rc, out, prog, sleeps


def load_out(out):
    with open(out, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_full_run_writes_precard_shape(tmp_path, monkeypatch):
    rc, out, prog, _ = run_pipeline(tmp_path, monkeypatch)
    assert rc == 0
    rows = load_out(out)
    assert len(rows) == 2
    for rec in rows:
        assert rec["key"] in ("w:apple", "p:give up")
        assert rec["sense_id"]  # S2 picked a real candidate
        assert rec["en_def"]
        assert rec["ipa_src"] in ("dataset", "model")
        assert isinstance(rec["dataset_examples"], list)
        assert rec["topic_vector"]  # S3/S4 vector present
        assert rec["topic_method"]  # S4 method tag
        assert rec["stage_calls"]["s2"]
        assert rec["stage_calls"]["s0"] in ("kept", "kept:type-pending")
        assert rec["drop_reason"] is None  # survivors carry no drop reason
        assert rec["abbrev_expansion"] == ""  # R29: plain glosses, no match
        assert isinstance(rec["pos"], list)  # R32: anchored tag list
        assert rec["pos_src"] in ("dataset", "none")
    apple = next(r for r in rows if r["key"] == "w:apple")
    assert apple["pos"] and apple["pos"][0] == "noun"  # anchored first
    assert apple["pos_src"] == "dataset"
    for stage in ("s0", "s1", "s2", "s3", "s4", "s5"):
        state = json.loads(
            (pathlib.Path(prog) / (stage + ".json")).read_text(
                encoding="utf-8"))
        assert len(state["done"]) == 2


def test_s5_enrich_pos_and_abbrev(tmp_path, monkeypatch):
    """R29/R32: S5 returns abbrev_expansion + pos/pos_src from the pick."""
    from precard_pipeline import s5_enrich_item
    index = {"dvd": [{"pos": "noun",
                      "entry": {"pos": "noun", "sounds": [{"ipa": "/x/"}],
                                "senses": [{"glosses": [
                                    "Initialism of digital video disc"],
                                    "tags": [],
                                    "examples": [{"text": LONG_EXAMPLE}]}]}}]}
    item = {"kind": "word", "text": "dvd", "pos": "noun",
            "pool_level": "B1"}
    enriched = s5_enrich_item(
        item, {"sense_id": "dvd#0",
               "gloss": "Initialism of digital video disc"},
        index, read_entry, {})
    assert enriched["abbrev_expansion"] == "digital video disc"
    assert enriched["pos"] == ["noun"]
    assert enriched["pos_src"] == "dataset"
    empty = s5_enrich_item(item, {"sense_id": "", "gloss": ""},
                           index, read_entry, {})
    assert empty["abbrev_expansion"] == ""
    assert empty["pos"] == [] and empty["pos_src"] == "none"


def _word_rows(word, glosses=("a thing",), ipa="/x/"):
    return [{"pos": "noun",
             "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                       "senses": [{"glosses": [g], "tags": [],
                                   "examples": [{"text": LONG_EXAMPLE}]}
                                  for g in glosses]}}]


def _run_s0_only(tmp_path, monkeypatch, items, index, **kwargs):
    """Run the pipeline with LLM legs stubbed; return (rows, s0_state)."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path, items)
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index=index, _read_entry=read_entry, _tatoeba={}, **kwargs)
    assert rc == 0
    rows = load_out(out)
    s0 = json.loads(
        (pathlib.Path(prog) / "s0.json").read_text(encoding="utf-8"))
    return rows, s0


def test_s0_drops_name_only_word(tmp_path, monkeypatch):
    """R4: single-token word whose kaikki POS set is {name} drops."""
    items = [{"kind": "word", "text": "Xyzztown", "pos": "noun",
              "pool_level": "B1"}]
    index = {"xyzztown": [{"pos": "name",
                           "entry": {"pos": "name", "sounds": [],
                                     "senses": [{"glosses": ["A place."],
                                                 "tags": [],
                                                 "examples": []}]}}]}
    rows, s0 = _run_s0_only(tmp_path, monkeypatch, items, index,
                            _zipf_fn=lambda t: 5.0)
    assert rows == []  # dropped items never reach precard.jsonl
    assert s0["done"]["w:Xyzztown"]["kept"] is False
    assert s0["done"]["w:Xyzztown"]["reason"] == "r4-name-only"
    assert "w:Xyzztown" in s0["failed"]


def test_s0_zipf_low_drops_unless_academic(tmp_path, monkeypatch):
    """R20: zipf < 3.0 drops, unless the lemma is academic-tagged (AWL)."""
    items = [{"kind": "word", "text": "rarewd", "pos": "noun",
              "pool_level": "C1"},
             {"kind": "word", "text": "analyzwd", "pos": "verb",
              "pool_level": "C1"}]
    index = {"rarewd": _word_rows("rarewd", ("an obscure thing",)),
             "analyzwd": _word_rows("analyzwd", ("to study closely",))}
    rows, s0 = _run_s0_only(tmp_path, monkeypatch, items, index,
                            _zipf_fn=lambda t: 1.5,
                            _awl_set={"analyzwd"})
    assert [r["key"] for r in rows] == ["w:analyzwd"]  # academic kept
    assert s0["done"]["w:rarewd"]["kept"] is False
    assert s0["done"]["w:rarewd"]["reason"].startswith("r20-zipf-low")
    assert "w:rarewd" in s0["failed"]
    assert s0["done"]["w:analyzwd"]["kept"] is True


def test_s0_phrase_applied_keep_false_drops(tmp_path, monkeypatch):
    """Phrase with applied_keep==False drops with its type in the reason."""
    items = [{"kind": "phrase", "text": "give up", "pool_level": "B1"}]
    rows, s0 = _run_s0_only(
        tmp_path, monkeypatch, items, make_index(),
        _type_map={"give up": {"phrase_type": "other",
                               "applied_keep": False}},
        _type_log_available=True)
    assert rows == []
    assert s0["done"]["p:give up"]["kept"] is False
    assert s0["done"]["p:give up"]["reason"] == "applied-keep-false:other"
    assert "p:give up" in s0["failed"]


def test_s0_phrase_type_pending_when_no_log(tmp_path, monkeypatch):
    """No type log -> phrase kept with the type-pending flag (never fails)."""
    items = [{"kind": "phrase", "text": "give up", "pool_level": "B1"}]
    rows, s0 = _run_s0_only(
        tmp_path, monkeypatch, items, make_index(),
        _type_map={}, _type_log_available=False)
    assert len(rows) == 1
    assert rows[0]["key"] == "p:give up"
    assert rows[0]["type_pending"] is True
    assert rows[0]["stage_calls"]["s0"] == "kept:type-pending"
    assert s0["done"]["p:give up"] == {
        "kept": True, "reason": None, "type_pending": True}


def test_s1_anchor_proper_noun_drop(tmp_path, monkeypatch):
    """V7: anchored entry POS in {name, propn} drops with reason
    anchor-proper-noun (deterministic, no name lists); a normal anchor
    passes through to precard.jsonl."""
    items = [{"kind": "word", "text": "Apple", "pos": "noun",
              "pool_level": "A1"},
             {"kind": "word", "text": "Banana", "pos": "noun",
              "pool_level": "A1"}]

    def name_rows():
        return [
            {"pos": "noun",
             "entry": {"pos": "noun", "sounds": [],
                       "senses": [{"glosses": ["Alternative spelling of xyz"],
                                   "tags": [],
                                   "examples": [{"text": LONG_EXAMPLE}]}]}},
            {"pos": "name",
             "entry": {"pos": "name", "sounds": [],
                       "senses": [{"glosses": ["A tech company"], "tags": [],
                                   "examples": [{"text": LONG_EXAMPLE}]}]}},
        ]

    index = {"apple": name_rows(),
             "banana": _word_rows("banana", ("a long fruit",))}
    rows, s0 = _run_s0_only(tmp_path, monkeypatch, items, index,
                            _zipf_fn=lambda t: 5.0)
    # S0 keeps both (POS set {noun, name} is not name-only).
    assert s0["done"]["w:Apple"]["kept"] is True
    assert [r["key"] for r in rows] == ["w:Banana"]  # Apple dropped in S1
    s1 = json.loads(
        (pathlib.Path(str(tmp_path / "prog")) / "s1.json").read_text(
            encoding="utf-8"))
    assert s1["done"]["w:Apple"]["dropped"] == "anchor-proper-noun"
    assert s1["done"]["w:Apple"]["anchor_pos"] == "name"
    assert "w:Apple" in s1["failed"]
    assert "dropped" not in s1["done"]["w:Banana"]
    assert s1["done"]["w:Banana"]["anchor_pos"] == "noun"


def test_run_log_and_batch_lines(tmp_path, monkeypatch, capsys):
    """V7: every batch prints ONE SsN line; run.log has stage start/end."""
    rc, out, prog, _ = run_pipeline(tmp_path, monkeypatch)
    assert rc == 0
    logged = (tmp_path / "run.log").read_text(encoding="utf-8")
    for stage in ("s0", "s1", "s2", "s3", "s4", "s5"):
        assert ("stage %s start" % stage) in logged
        assert ("stage %s end" % stage) in logged
    captured = capsys.readouterr()
    assert "Ss0 batch 1/1 ok=2 fail=0 model=0" in captured.out
    assert "Ss1 batch 1/1 ok=2 fail=0 model=0" in captured.out
    assert "Ss5 batch 1/1 ok=" in captured.out


def test_stage_skip_on_resume(tmp_path, monkeypatch):
    rc, out, _prog, _ = run_pipeline(tmp_path, monkeypatch)
    assert rc == 0
    before = open(out, encoding="utf-8").read()

    def boom(*args, **kwargs):
        raise AssertionError("must be skipped on resume")

    monkeypatch.setattr(card_pilot, "anchor_item_en", boom)
    monkeypatch.setattr(card_pilot, "assign_topic", boom)
    monkeypatch.setattr(card_pilot, "resolve_dataset_examples", boom)
    calls = []
    prog = str(tmp_path / "prog")
    sample = str(tmp_path / "sample.json")
    out2 = str(tmp_path / "precard2.jsonl")
    rc = precard_main(
        ["--sample", sample, "--out", out2, "--progress-dir", prog],
        _judge_transport=lambda *a: (calls.append("judge"), "{}")[1],
        _topic_transport=lambda *a: (calls.append("topic"), "{}")[1],
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index={}, _read_entry=read_entry, _tatoeba={})
    assert rc == 0
    assert calls == []  # no LLM transport touched on full resume
    assert open(out2, encoding="utf-8").read() == before


def _http_429():
    return urllib.error.HTTPError("http://x", 429, "Too Many Requests",
                                  {}, None)


def test_429_rotates_across_keys_then_succeeds(tmp_path, monkeypatch):
    """S2 429 on key1 rotates to key2 (5s pause) and retries the SAME call."""
    import pytest
    from phrase_judge import KeyRing
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path, ITEMS[:1])
    prog_state = {"done": {}, "failed": [], "backoffs": []}
    sleeps = []
    seen_keys = []

    def flaky(api_key, model, user_text):
        seen_keys.append(api_key)
        if len(seen_keys) == 1:
            raise _http_429()
        return fake_judge(api_key, model, user_text)

    from precard_pipeline import s1_rank_item
    index = make_index()
    ranked = s1_rank_item(
        {"kind": "word", "text": "apple", "pos": "noun",
         "pool_level": "A1"}, index, read_entry)
    s1map = {"w:apple": ranked}
    batch = [{"kind": "word", "text": "apple", "pos": "noun",
              "pool_level": "A1"}]
    ring = KeyRing(["k1", "k2"])
    tele = []
    from precard_pipeline import s2_judge_batch
    out = s2_judge_batch(batch, s1map, "k1", flaky, sleeps.append,
                         prog_state, telemetry=tele, tele_batch=1,
                         ring=ring)
    assert out["w:apple"]["sense_id"] == "apple#0"
    assert out["w:apple"]["model"] not in ("s1-fallback",
                                           "s1-fallback-empty")
    assert seen_keys == ["k1", "k2"]  # same call retried on next key
    assert sleeps == [5.0]  # brief pause, no 60s/300s waits
    assert any(e["outcome"] == "rotating"
               for e in prog_state["backoffs"])
    assert any(r.get("outcome") == "ok" for r in tele)


def test_all_keys_429_stops_fast_with_flush(tmp_path, monkeypatch):
    """All-keys-429 STOPS (SystemExit, VPN message) — no 6-min wait."""
    import pytest
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path, ITEMS[:1])
    out, prog, sleeps = (str(tmp_path / "precard.jsonl"),
                         str(tmp_path / "prog"), [])

    def always_429(api_key, model, user_text):
        raise _http_429()

    with pytest.raises(SystemExit) as excinfo:
        precard_main(
            ["--sample", sample, "--out", out, "--progress-dir", prog],
            _judge_transport=always_429, _topic_transport=fake_topics,
            _assign_transport=None, _sleep_fn=sleeps.append,
            _index=make_index(), _read_entry=read_entry, _tatoeba={})
    assert "VPN" in str(excinfo.value) or "server" in str(excinfo.value)
    assert sum(sleeps) < 60.0  # 5s rotation pause, never 60+300
    assert 60.0 not in sleeps and 300.0 not in sleeps
    # Progress flushed before exit (per-batch + finally): s2.json on disk
    # with the stop event recorded.
    state = json.loads(open(prog + "/s2.json", encoding="utf-8").read())
    assert any(e["outcome"] == "all-keys-429-stop"
               for e in state["backoffs"])


def test_s3_429_rotates_across_keys(tmp_path, monkeypatch):
    """S3 429 rotates keys with a 5s pause and retries the same call."""
    from phrase_judge import KeyRing
    from precard_pipeline import s1_rank_item, s3_vector_batch
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    ranked = s1_rank_item(item, index, read_entry)
    s1map = {"w:apple": ranked}
    s2map = {"w:apple": {"sense_id": "apple#0", "gloss": "a round fruit"}}
    sleeps, seen = [], []
    state = {"done": {}, "failed": [], "backoffs": []}

    def flaky(api_key, model, user_text):
        seen.append(api_key)
        if len(seen) == 1:
            raise _http_429()
        return fake_topics(api_key, model, user_text)

    out = s3_vector_batch([item], s2map, s1map, "k1", flaky,
                          sleeps.append, state, tele_batch=1,
                          ring=KeyRing(["k1", "k2"]))
    assert out["apple#0"]["vector"]
    # First call 429s on k1, same call retried on k2 (later calls stay on
    # k2 while the chain exhausts the fake's invalid vectors to the
    # deterministic fallback — rotation is proven by the first two keys).
    assert seen[:2] == ["k1", "k2"]
    assert sleeps[0] == 5.0
    assert 60.0 not in sleeps and 300.0 not in sleeps


def test_s4_429_rotates_and_all_keys_stop(tmp_path, monkeypatch):
    """S4 wrapper rotates on 429; all-keys-429 raises RateLimited with a
    provider-neutral message (per-stage STOP wrappers add VPN/quota hints)."""
    import pytest
    from phrase_judge import KeyRing
    from precard_pipeline import _rotating_llm_transport
    # Rotate-then-succeed.
    sleeps, seen = [], []
    state = {"done": {}, "failed": [], "backoffs": []}

    def flaky(api_key, model, user_text):
        seen.append(api_key)
        if len(seen) == 1:
            raise _http_429()
        return "ok"

    wrap = _rotating_llm_transport(flaky, sleeps.append, state,
                                   KeyRing(["k1", "k2"]))
    assert wrap("ignored", "m", "prompt") == "ok"
    assert seen == ["k1", "k2"] and sleeps == [5.0]
    # All keys 429 -> RateLimited (the S4 caller converts to SystemExit
    # AFTER flushing progress; raising SystemExit here bypassed the flush).
    def always_429(api_key, model, user_text):
        raise _http_429()

    from phrase_judge import RateLimited
    wrap2 = _rotating_llm_transport(always_429, sleeps.append,
                                    {"done": {}, "failed": [],
                                     "backoffs": []},
                                    KeyRing(["k1", "k2"]))
    with pytest.raises(RateLimited) as excinfo:
        wrap2("ignored", "m", "prompt")
    assert "quotas exhausted" in str(excinfo.value)
    assert "VPN" not in str(excinfo.value)


def test_resume_continues_after_429_stop(tmp_path, monkeypatch):
    """After an all-keys-429 STOP, re-running with good transports resumes
    to a full precard (progress format unchanged, done work kept)."""
    import pytest
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path, ITEMS[:1])
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")

    def always_429(api_key, model, user_text):
        raise _http_429()

    with pytest.raises(SystemExit):
        precard_main(
            ["--sample", sample, "--out", out, "--progress-dir", prog],
            _judge_transport=always_429, _topic_transport=fake_topics,
            _assign_transport=None, _sleep_fn=lambda s: None,
            _index=make_index(), _read_entry=read_entry, _tatoeba={})
    # Resume with healthy transports completes the run.
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index=make_index(), _read_entry=read_entry, _tatoeba={})
    assert rc == 0
    rows = load_out(out)
    assert len(rows) == 1 and rows[0]["sense_id"] == "apple#0"


def test_fail_closed_to_s1_pick(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path, ITEMS[:1])
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")

    def garbage(api_key, model, user_text):
        return "this is not json {{{"

    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=garbage, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index=make_index(), _read_entry=read_entry, _tatoeba={})
    assert rc == 0
    rows = load_out(out)
    assert rows[0]["sense_id"] == "apple#0"
    assert rows[0]["en_def"] == "a round fruit"
    state = json.loads(open(prog + "/s2.json", encoding="utf-8").read())
    assert "w:apple" in state["failed"]


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path)
    out = str(tmp_path / "nope" / "precard.jsonl")
    prog = str(tmp_path / "nope" / "prog")
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog,
         "--dry-run"],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index=make_index(), _read_entry=read_entry, _tatoeba={})
    assert rc == 0
    assert not (tmp_path / "nope").exists()


def _mock_rec(item):
    # Mirrors generate_card: topic/topic_method ride from the item (the
    # --from-precard items carry topic_method "pipeline-v6").
    return {"key": ("w:" if item["kind"] == "word" else "p:") + item["text"],
            "kind": item["kind"], "text": item["text"],
            "pool_level": item.get("pool_level", ""),
            "topic": item.get("topic", ""),
            "topic_method": item.get("topic_method", ""),
            "bot_level": "beginner", "model_used": "mock",
            "card": None, "valid": False, "reason": "mock",
            "error": "mock"}


def test_from_precard_bypasses_anchor(tmp_path, monkeypatch):
    """card_pilot --from-precard skips sampling/anchor/topic/enrichment."""
    for name in ("anchor_item_en", "pick_anchor_sense_full",
                 "score_senses", "assign_topic",
                 "resolve_dataset_examples"):
        monkeypatch.setattr(
            card_pilot, name,
            (lambda n: (lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("%s must be skipped" % n))))(name))
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    monkeypatch.setattr(card_pilot, "CALL_SLEEP", 0)
    monkeypatch.setattr(card_pilot, "generate_card",
                        lambda item, api_key, **kw: _mock_rec(item))

    precard = tmp_path / "precard.jsonl"
    with open(precard, "w", encoding="utf-8") as handle:
        for rec in (
                {"key": "w:apple", "kind": "word", "text": "apple",
                 "pool_level": "A1", "sense_id": "apple#0",
                 "en_def": "a round fruit", "ipa": "/aɪpa/",
                 "ipa_src": "dataset", "dataset_examples": ["She eats."],
                 "topic_vector": [{"label": "Food & Drink",
                                   "weight": 1.0}],
                 "topic_method": "v16b-exact", "stage_calls": {}},
                {"key": "p:give up", "kind": "phrase", "text": "give up",
                 "pool_level": "B1", "sense_id": "give up#0",
                 "en_def": "to surrender", "ipa": "",
                 "ipa_src": "model", "dataset_examples": [],
                 "topic_vector": [{"label": "Other / Abstract",
                                   "weight": 1.0}],
                 "topic_method": "v16b-exact", "stage_calls": {}}):
            handle.write(json.dumps(rec) + "\n")
    pool = tmp_path / "lemmas.csv"
    pool.write_text("lemma,pos,cefr\napple,noun,A1\n", encoding="utf-8")
    plog = tmp_path / "judge.jsonl"
    plog.write_text("", encoding="utf-8")
    out_dir, report = str(tmp_path / "pilot"), str(tmp_path / "r.html")
    rc = card_pilot.main(["--from-precard", str(precard),
                          "--out-dir", out_dir, "--report", report,
                          "--word-pool", str(pool),
                          "--phrase-log", str(plog)],
                         _content_transport=None, _grammar_transport=None)
    assert rc == 0
    cards = card_pilot.load_cards_jsonl(out_dir + "/cards.jsonl")
    assert len(cards) == 2
    assert {c["text"] for c in cards} == {"apple", "give up"}
    assert {c["topic_method"] for c in cards} == {"pipeline-v6"}


# ---------------- v9 R35: level-aware R20 floors ----------------

def test_s0_level_floors(tmp_path, monkeypatch):
    """R35: C2 2.0 kept (floor 1.5), C2 1.2 dropped, B1 2.9 dropped
    (floor 3.0); academic bypass kept at any level."""
    items = [
        {"kind": "word", "text": "c2keep", "pos": "noun",
         "pool_level": "C2"},
        {"kind": "word", "text": "c2drop", "pos": "noun",
         "pool_level": "C2"},
        {"kind": "word", "text": "b1drop", "pos": "noun",
         "pool_level": "B1"},
        {"kind": "word", "text": "b1acad", "pos": "noun",
         "pool_level": "B1"},
    ]
    index = {t: _word_rows(t, ("a thing here",)) for t in
             ("c2keep", "c2drop", "b1drop", "b1acad")}
    by_text = {"c2keep": 2.0, "c2drop": 1.2, "b1drop": 2.9, "b1acad": 1.0}
    rows, s0 = _run_s0_only(
        tmp_path, monkeypatch, items, index,
        _zipf_fn=lambda t: by_text[t], _awl_set={"b1acad"})
    assert [r["key"] for r in rows] == ["w:c2keep", "w:b1acad"]
    assert s0["done"]["w:c2keep"]["kept"] is True
    assert s0["done"]["w:c2drop"]["reason"].startswith("r20-zipf-low")
    assert s0["done"]["w:b1drop"]["reason"].startswith("r20-zipf-low")
    assert s0["done"]["w:b1acad"]["kept"] is True  # academic bypass


def test_s0_phrase_has_no_zipf_gate(tmp_path, monkeypatch):
    """R35: phrases stay on the phrase-type path even with a low zipf."""
    items = [{"kind": "phrase", "text": "give up", "pool_level": "C2"}]
    rows, s0 = _run_s0_only(
        tmp_path, monkeypatch, items, make_index(),
        _zipf_fn=lambda t: 1.0, _type_map={}, _type_log_available=False)
    assert len(rows) == 1  # kept with type-pending, never zipf-dropped
    assert s0["done"]["p:give up"]["type_pending"] is True


# ---------------- v9 R34: xref S1 drop ----------------

def test_s1_xref_unresolvable_drop(tmp_path, monkeypatch):
    """R34: bare-xref anchor with no target entry drops as no-real-def;
    a resolved xref survives with the target sense."""
    items = [{"kind": "word", "text": "Ghost", "pos": "noun",
              "pool_level": "A1"},
             {"kind": "word", "text": "Color", "pos": "noun",
              "pool_level": "A1"}]
    index = {
        "ghost": [{"pos": "noun",
                   "entry": {"pos": "noun", "sounds": [],
                             "senses": [{"glosses": ["See specter."],
                                         "tags": [], "examples": []}]}}],
        "color": [{"pos": "noun",
                   "entry": {"pos": "noun", "sounds": [],
                             "senses": [{"glosses": [
                                 "Alternative spelling of colour."],
                                 "tags": [], "examples": []}]}}],
        "colour": [{"pos": "noun",
                    "entry": {"pos": "noun", "sounds": [],
                              "senses": [{"glosses": [
                                  "a hue such as red or blue"],
                                  "tags": [], "examples": []}]}}],
    }
    rows, _s0 = _run_s0_only(tmp_path, monkeypatch, items, index,
                             _zipf_fn=lambda t: 5.0)
    assert [r["key"] for r in rows] == ["w:Color"]  # Ghost: no-real-def
    s1 = json.loads(
        (pathlib.Path(str(tmp_path / "prog")) / "s1.json").read_text(
            encoding="utf-8"))
    assert s1["done"]["w:Ghost"]["dropped"] == "no-real-def"
    assert s1["done"]["w:Ghost"]["xref_unresolvable"] is True
    assert "w:Ghost" in s1["failed"]
    assert s1["done"]["w:Color"]["xref_method"] == "xref-resolved"
    assert s1["done"]["w:Color"]["resolved_from"] == "color#0"
    color = rows[0]
    assert color["sense_id"] == "colour#0"
    assert color["en_def"] == "a hue such as red or blue"


# ---------------- v9 R36: S0b inflection stage ----------------

def _inflect_index():
    def rows(gloss):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [],
                           "senses": [{"glosses": [gloss], "tags": [],
                                       "examples": []}]}}]
    return {"cats": rows("plural of cat"),
            "went": rows("past of go"),
            "apple": rows("a round fruit")}


def test_s0b_inflection_keep_and_drop(tmp_path, monkeypatch):
    """R36: explicit keep-false drops (inflection-drop), keep passes;
    non-inflection items skip review; own progress key s0b.json."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    items = [{"kind": "word", "text": "cats", "pos": "noun",
              "pool_level": "A1"},
             {"kind": "word", "text": "went", "pos": "noun",
              "pool_level": "A1"},
             {"kind": "word", "text": "apple", "pos": "noun",
              "pool_level": "A1"}]
    sample = write_sample(tmp_path, items)
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")

    def inflect(api_key, model, sys_text, user_text):
        return json.dumps({"results": [
            {"key": "w:cats", "keep": False,
             "reason": "regular plural, use cat"},
            {"key": "w:went", "keep": True,
             "reason": "irregular, own value"}]})

    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _inflect_transport=inflect,
        _sleep_fn=lambda s: None, _index=_inflect_index(),
        _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0)
    assert rc == 0
    rows = load_out(out)
    assert {r["key"] for r in rows} == {"w:went", "w:apple"}
    s0b = json.loads(
        (pathlib.Path(prog) / "s0b.json").read_text(encoding="utf-8"))
    assert s0b["done"]["w:cats"]["kept"] is False
    assert s0b["done"]["w:cats"]["reason"].startswith("inflection-drop")
    assert "w:cats" in s0b["failed"]
    assert s0b["done"]["w:went"]["reason"] == "inflection-keep"
    assert s0b["done"]["w:apple"]["reason"] == "not-inflection"


def test_s0b_uncertain_keeps(tmp_path, monkeypatch):
    """R36 fail-closed: review errors keep the item flagged
    review-uncertain (never drop on uncertainty)."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    items = [{"kind": "word", "text": "cats", "pos": "noun",
              "pool_level": "A1"}]
    sample = write_sample(tmp_path, items)
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")

    def broken(api_key, model, sys_text, user_text):
        raise urllib.error.HTTPError("http://x", 500, "boom", {}, None)

    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _inflect_transport=broken,
        _sleep_fn=lambda s: None, _index=_inflect_index(),
        _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0)
    assert rc == 0
    assert [r["key"] for r in load_out(out)] == ["w:cats"]  # kept
    s0b = json.loads(
        (pathlib.Path(prog) / "s0b.json").read_text(encoding="utf-8"))
    assert s0b["done"]["w:cats"] == {
        "kept": True, "reason": "review-uncertain", "uncertain": True}

def test_s1_drops_vulgar_anchor():
    from precard_pipeline import s1_rank_item
    import card_pilot
    probe = {"kind": "word", "text": "mf", "pool_level": "B2"}
    out = s1_rank_item(probe, {"mf": [{"pos": "noun", "offset": 0, "length": 10}]},
                       lambda row: {"pos": "noun", "sounds": [],
                                    "senses": [{"glosses": ["Initialism of motherfucker."],
                                                "tags": ["vulgar"], "examples": []}]})
    assert "vulgar" in (out.get("anchor_tags") or [])


def test_coherence_stem_overlap():
    from card_pilot import sense_coherence_check
    assert sense_coherence_check(
        "Coming or characterized by torrents",
        {"examples": ["Torrential rain fell all night."], "fa_meaning": "",
         "fa_explanation": "", "example_translations": [], "synonyms": []}) is True
    assert sense_coherence_check(
        "An X mark placed at the end of a letter",
        {"examples": ["I want to kiss her."], "fa_meaning": "",
         "fa_explanation": "", "example_translations": [], "synonyms": []}) is None
    # R41b tri-state: no token overlap -> undecided (micro-pass decides).


# ---------------- v12 R44: superlative redirect (S0b verdict variant) ---

def _superlative_index():
    def rows(gloss):
        return [{"pos": "adj",
                 "entry": {"pos": "adj", "sounds": [],
                           "senses": [{"glosses": [gloss], "tags": [],
                                       "examples": []}]}}]
    return {"best": rows("superlative of good"),
            "better": rows("comparative of good"),
            "good": rows("having good qualities")}


def _super_items():
    return [{"kind": "word", "text": "best", "pos": "adjective",
             "pool_level": "A1"},
            {"kind": "word", "text": "better", "pos": "adjective",
             "pool_level": "A1"}]


def test_s0b_superlative_redirects_on_plain_drop(tmp_path, monkeypatch):
    """R44 mocked: plain superlative/comparative keep-false verdicts
    redirect (kept, reason superlative-redirect, redirect_to base)."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path, _super_items())
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")

    def inflect(api_key, model, sys_text, user_text):
        return json.dumps({"results": [
            {"key": "w:best", "keep": False, "reason": "plain superlative"},
            {"key": "w:better", "keep": False,
             "reason": "plain comparative"}]})

    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _inflect_transport=inflect,
        _sleep_fn=lambda s: None, _index=_superlative_index(),
        _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0)
    assert rc == 0
    s0b = json.loads(
        (pathlib.Path(prog) / "s0b.json").read_text(encoding="utf-8"))
    assert s0b["done"]["w:best"] == {
        "kept": True, "reason": "superlative-redirect",
        "redirect_to": "good", "uncertain": False}
    assert s0b["done"]["w:better"]["redirect_to"] == "good"
    assert "w:best" not in s0b["failed"]  # redirect keeps, never drops
    rows = {r["key"]: r for r in load_out(out)}
    # R44 merge (Gemini): the item becomes the base lemma in the output.
    # best+better both target good: first emitted wins, second is a
    # duplicate-redirect drop (no FSRS fragmentation, no silent overwrite).
    assert rows["w:good"]["redirect_to"] == "good"
    # F2 first-wins: the first item in sample order (best) owns the
    # merged key — order-indifferent membership is NOT enough.
    assert rows["w:good"]["redirected_from"] == "best"
    s5 = json.loads(
        (pathlib.Path(prog) / "s5.json").read_text(encoding="utf-8"))
    assert rows["w:good"]["sense_id"] == s5["done"]["w:good"]["sense_id"]
    assert rows["w:good"]["sense_id"] == "good#0"  # base-lemma S5 pick
    assert len(rows) == 1


def test_s0b_superlative_base_missing_from_index_is_not_inflection():
    # F4: a superlative-pattern gloss whose base is absent from the
    # index is not-inflection (no review); base present -> review.
    from precard_pipeline import s0b_needs_review

    def rows(gloss):
        return [{"pos": "adj",
                 "entry": {"pos": "adj", "sounds": [],
                           "senses": [{"glosses": [gloss], "tags": [],
                                       "examples": []}]}}]
    index = {"biggest": rows("superlative of big"),
             "best": rows("superlative of good"),
             "good": rows("having good qualities")}
    needs, _gloss = s0b_needs_review(
        {"kind": "word", "text": "biggest", "pos": "adj"}, index,
        read_entry)
    assert needs is False  # base "big" not in index
    needs, gloss = s0b_needs_review(
        {"kind": "word", "text": "best", "pos": "adj"}, index, read_entry)
    assert needs is True
    assert gloss == "superlative of good"


def test_s0b_superlative_idiomatic_kept(tmp_path, monkeypatch):
    """R44 mocked: an established idiomatic keep verdict stays kept
    (inflection-keep, no redirect)."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path, _super_items()[:1])
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")

    def inflect(api_key, model, sys_text, user_text):
        return json.dumps({"results": [
            {"key": "w:best", "keep": True,
             "reason": "idiom: do one's best"}]})

    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _inflect_transport=inflect,
        _sleep_fn=lambda s: None, _index=_superlative_index(),
        _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0)
    assert rc == 0
    s0b = json.loads(
        (pathlib.Path(prog) / "s0b.json").read_text(encoding="utf-8"))
    assert s0b["done"]["w:best"]["reason"] == "inflection-keep"
    assert s0b["done"]["w:best"].get("redirect_to", "") == ""
    assert [r["key"] for r in load_out(out)] == ["w:best"]


def test_telemetry_history_uses_card_pilot_seam(tmp_path, monkeypatch):
    # F7: precard reuses card_pilot.append_telemetry_history BY IMPORT
    # (no second copy of the history logic) and each run appends to
    # the cumulative telemetry_records.jsonl.
    assert precard_pipeline.append_telemetry_history is \
        card_pilot.append_telemetry_history
    rc, out, _prog, _sleeps = run_pipeline(
        tmp_path, monkeypatch, zipf_fn=lambda t: 5.0)
    assert rc == 0
    hist = pathlib.Path(out).parent / "telemetry_records.jsonl"
    assert hist.exists()
    assert sum(1 for line in hist.read_text(encoding="utf-8").splitlines()
               if line.strip()) > 0


def test_s2_tuple_usage_recorded():
    """T1: tuple (text, usage) judge transports surface tokens (None-tolerated)."""
    from phrase_judge import KeyRing
    from precard_pipeline import s1_rank_item, s2_judge_batch
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    s1map = {"w:apple": s1_rank_item(item, index, read_entry)}

    def tuple_judge(api_key, model, user_text):
        return (fake_judge(api_key, model, user_text),
                {"input_tokens": 11, "output_tokens": 5})

    tele = []
    out = s2_judge_batch([item], s1map, "k", tuple_judge, lambda s: None,
                         {"done": {}, "failed": [], "backoffs": []},
                         telemetry=tele, tele_batch=1, ring=KeyRing(["k"]))
    assert out["w:apple"]["sense_id"] == "apple#0"
    ok = [r for r in tele if r.get("outcome") == "ok"]
    assert ok and ok[0]["prompt_tokens"] == 11
    assert ok[0]["completion_tokens"] == 5
    # Plain-text transports record None tokens without failing.
    tele2 = []
    s2_judge_batch([item], s1map, "k", fake_judge, lambda s: None,
                   {"done": {}, "failed": [], "backoffs": []},
                   telemetry=tele2, tele_batch=1, ring=KeyRing(["k"]))
    ok2 = [r for r in tele2 if r.get("outcome") == "ok"]
    assert ok2 and ok2[0]["prompt_tokens"] is None
    assert ok2[0]["completion_tokens"] is None


def test_s3_tuple_usage_recorded():
    """T1: tuple (text, usage) topic transports surface tokens."""
    from phrase_judge import KeyRing
    from precard_pipeline import s1_rank_item, s3_vector_batch
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    s1map = {"w:apple": s1_rank_item(item, index, read_entry)}
    s2map = {"w:apple": {"sense_id": "apple#0", "gloss": "a round fruit"}}

    def tuple_topics(api_key, model, user_text):
        return (json.dumps({"results": [{"lemma": "apple", "vectors": [
            {"sense_id": "apple#0",
             "vector": [{"topic_id": 13,
                         "topic_label": "Other / Abstract",
                         "weight": 1.0}]}]}]}),
                {"input_tokens": 13, "output_tokens": 7})

    tele = []
    out = s3_vector_batch([item], s2map, s1map, "k", tuple_topics,
                          lambda s: None,
                          {"done": {}, "failed": [], "backoffs": []},
                          telemetry=tele, tele_batch=1, ring=KeyRing(["k"]))
    assert out["apple#0"]["model"] != "deterministic"
    ok = [r for r in tele if r.get("outcome") == "ok"]
    assert ok and ok[0]["prompt_tokens"] == 13
    assert ok[0]["completion_tokens"] == 7


def test_s4_fallback_path_counted(tmp_path):
    """T1: S4 deterministic fallback carries topic_path + fallback telemetry."""
    from phrase_judge import KeyRing
    from precard_pipeline import s4_label_item
    state = {"done": {}, "failed": [], "backoffs": []}
    item = {"kind": "word", "text": "zzqx", "pool_level": "B1"}

    def garbage(api_key, model, user_text):
        return "not json {{{"

    tele = []
    assigned = s4_label_item(
        item, "plural of zzqx", "zzqx#0", None, "k", garbage,
        lambda s: None, state, str(tmp_path / "s4.json"), {},
        telemetry=tele, tele_batch=1, ring=KeyRing(["k"]))
    assert assigned["label"] == "Other / Abstract"
    assert assigned["topic_path"] == "fallback"
    assert any(r.get("stage") == "s4" and r.get("outcome") == "fallback"
               for r in tele)


def test_s5_enrich_path_full_and_partial():
    """T1: S5 marks full carriers vs partial (model must fill gaps)."""
    from precard_pipeline import s5_enrich_item
    full_ex = ["The dvd player sits on the wooden shelf today",
               "She bought a new dvd for the long family trip"]
    index = {"dvd": [{"pos": "noun",
                      "entry": {"pos": "noun", "sounds": [{"ipa": "/x/"}],
                                "senses": [{"glosses": ["a disc"],
                                            "tags": [],
                                            "examples": [{"text": e}
                                                         for e in full_ex]}]}}]}
    item = {"kind": "word", "text": "dvd", "pos": "noun",
            "pool_level": "B1"}
    full = s5_enrich_item(item, {"sense_id": "dvd#0", "gloss": "a disc"},
                          index, read_entry, {})
    assert full["enrich_path"] == "full"
    assert len(full["dataset_examples"]) == 2
    partial = s5_enrich_item(item, {"sense_id": "", "gloss": ""},
                             index, read_entry, {})
    assert partial["enrich_path"] == "partial"

def test_precard_output_atomic_no_partial(tmp_path, monkeypatch):
    """OC must-fix: crash mid-write must not truncate precard.jsonl."""
    from precard_pipeline import main as precard_main
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(
        [{"kind": "word", "text": "apple", "pool_level": "A1"},
         {"kind": "word", "text": "pear", "pool_level": "A1"}]),
        encoding="utf-8")
    out = tmp_path / "precard.jsonl"
    out.write_text("SENTINEL-OLD-CONTENT\n", encoding="utf-8")
    real_dumps = json.dumps
    calls = {"n": 0}

    def flaky_dumps(obj, **kw):
        # Crash on a record serialization (mid-write).
        if isinstance(obj, dict) and str(obj.get("key", "")).startswith("w:"):
            calls["n"] += 1
            if calls["n"] >= 1:
                raise RuntimeError("simulated crash mid-write")
        return real_dumps(obj, **kw)

    import precard_pipeline
    monkeypatch.setattr(precard_pipeline.json, "dumps", flaky_dumps)
    with __import__("pytest").raises(RuntimeError):
        precard_main(
            ["--sample", str(sample), "--out", str(out),
             "--progress-dir", str(tmp_path / "prog")],
            _judge_transport=None, _topic_transport=None,
            _assign_transport=None, _sleep_fn=lambda s: None,
            _index={}, _read_entry=lambda row: (_ for _ in ()).throw(
                RuntimeError("unreachable")),
            _tatoeba={}, _zipf_fn=lambda t: 5.0)
    # Original file intact (tmp write never replaced it).
    assert out.read_text(encoding="utf-8") == "SENTINEL-OLD-CONTENT\n"

def test_s4_ratelimited_flushes_not_swallowed(monkeypatch):
    """OC must-fix: all-keys-429 in S4 must flush via RateLimited (not a
    SystemExit that bypasses the caller flush)."""
    import urllib.error
    from precard_pipeline import _rotating_llm_transport
    from phrase_judge import KeyRing, RateLimited
    import pytest

    def transport_429(api_key, model, user_text):
        raise urllib.error.HTTPError("http://x", 429, "throttled", {}, None)

    ring = KeyRing(["k1", "k2"])
    wrap = _rotating_llm_transport(transport_429, lambda s: None, {}, ring)
    with pytest.raises(RateLimited):
        wrap("k1", "m", "u")

def test_s4_label_item_reraises_ratelimited():
    """OC must-fix: s4_label_item must not swallow RateLimited into fallback."""
    import urllib.error
    import pytest
    from precard_pipeline import s4_label_item
    from phrase_judge import KeyRing, RateLimited

    def transport_429(api_key, model, user_text):
        raise urllib.error.HTTPError("http://x", 429, "throttled", {}, None)

    with pytest.raises(RateLimited):
        s4_label_item(
            {"kind": "word", "text": "x", "pool_level": "A1"}, "gloss",
            "x#0", None, "k", transport_429, lambda s: None,
            {"done": {}, "failed": [], "backoffs": []}, None, {},
            ring=KeyRing(["k1", "k2"]))


def test_avalai_transport_shape(monkeypatch):
    """AvalAI chain: effort-low posted, model honored, usage surfaced."""
    import io as _io
    import precard_pipeline
    seen = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4,
                          "completion_tokens_details": {
                              "reasoning_tokens": 0}}}).encode("utf-8")

    def fake_urlopen(req, timeout=120):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr(precard_pipeline.urllib.request, "urlopen",
                        fake_urlopen)
    text, usage = precard_pipeline._avalai_chat_transport(
        "k-test", "glm-5.3-flash", "hello")
    assert text == '{"ok": true}'
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 4
    assert seen["url"] == precard_pipeline.AVALAI_CHAT_URL
    assert seen["auth"] == "Bearer k-test"
    assert seen["body"]["model"] == "glm-5.3-flash"
    assert seen["body"]["extra_body"] == {"reasoning_effort": "low"}


def test_avalai_transport_http_error_propagates(monkeypatch):
    """AvalAI chain: 429/401 reach the caller untouched (rotation/auth)."""
    import urllib.error
    import pytest
    import precard_pipeline

    def boom(req, timeout=120):
        raise urllib.error.HTTPError("http://x", 429, "throttled", {},
                                     None)

    monkeypatch.setattr(precard_pipeline.urllib.request, "urlopen", boom)
    with pytest.raises(urllib.error.HTTPError):
        precard_pipeline._avalai_chat_transport("k", "m", "u")


def test_s2_models_override_used():
    """AvalAI chain: explicit models list replaces the Zen chain."""
    from phrase_judge import KeyRing
    from precard_pipeline import s1_rank_item, s2_judge_batch
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    s1map = {"w:apple": s1_rank_item(item, index, read_entry)}
    seen = []

    def rec(api_key, model, user_text):
        seen.append(model)
        return fake_judge(api_key, model, user_text)

    out = s2_judge_batch([item], s1map, "k", rec, lambda s: None,
                         {"done": {}, "failed": [], "backoffs": []},
                         ring=KeyRing(["k"]), models=["glm-5.3-flash"])
    assert out["w:apple"]["model"] == "glm-5.3-flash"
    assert seen == ["glm-5.3-flash"]


def test_judge_provider_defaults_zen():
    """Default provider stays zen (zero behavior change without the flag)."""
    from precard_pipeline import parse_args
    args = parse_args(["--sample", "s"])
    assert args.judge_provider == "zen"
    assert args.llm_provider == "zen"
    assert args.judge_model == ""
    assert args.precard_model == ""
    assert parse_args(["--sample", "s", "--judge-provider",
                       "avalai"]).judge_provider == "avalai"
    assert parse_args(["--sample", "s", "--llm-provider",
                       "avalai",
                       "--precard-model",
                       "deepseek-v4-flash"]).precard_model == \
        "deepseek-v4-flash"


def test_avalai_key_scoped_to_s2(tmp_path, monkeypatch):
    """F1: --judge-provider avalai routes only the S2 call; Zen key/ring
    keep feeding every other stage (here: s1 deterministic, s2 recorded)."""
    import precard_pipeline
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "zen-key")
    monkeypatch.setenv("AVALAI_API_KEY", "avalai-key")
    sample = write_sample(tmp_path, ITEMS[:1])
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    seen = []

    def rec_judge(api_key, model, user_text):
        seen.append((api_key, model))
        return fake_judge(api_key, model, user_text)

    monkeypatch.setattr(precard_pipeline, "_avalai_chat_transport",
                        rec_judge)
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog,
         "--stages", "s0,s1,s2", "--judge-provider", "avalai"],
        _topic_transport=None, _assign_transport=None,
        _sleep_fn=lambda s: None, _index=make_index(),
        _read_entry=read_entry, _tatoeba={}, _zipf_fn=lambda t: 5.0)
    assert rc == 0
    assert seen and seen[0][0] == "avalai-key"
    assert seen[0][1] == "glm-5.3-flash"
    s2 = json.loads(
        (pathlib.Path(prog) / "s2.json").read_text(encoding="utf-8"))
    assert s2["done"]["w:apple"]["model"] == "glm-5.3-flash"


def test_full_llm_provider_wires_precard_model(tmp_path, monkeypatch):
    """#5: --llm-provider avalai routes the S2 call to --precard-model
    end to end (flag -> override connection, not just the unit)."""
    import precard_pipeline
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "zen-key")
    monkeypatch.setenv("AVALAI_API_KEY", "avalai-key")
    sample = write_sample(tmp_path, ITEMS[:1])
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    seen = []

    def rec_judge(api_key, model, user_text):
        seen.append((api_key, model))
        return fake_judge(api_key, model, user_text)

    monkeypatch.setattr(precard_pipeline, "_avalai_chat_transport",
                        rec_judge)
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog,
         "--stages", "s0,s1,s2", "--llm-provider", "avalai",
         "--precard-model", "deepseek-v4-flash"],
        _topic_transport=None, _assign_transport=None,
        _sleep_fn=lambda s: None, _index=make_index(),
        _read_entry=read_entry, _tatoeba={}, _zipf_fn=lambda t: 5.0)
    assert rc == 0
    assert seen and seen[0] == ("avalai-key", "deepseek-v4-flash")
    s2 = json.loads(
        (pathlib.Path(prog) / "s2.json").read_text(encoding="utf-8"))
    assert s2["done"]["w:apple"]["model"] == "deepseek-v4-flash"


def test_avalai_remap_substitutes_model():
    """Full-line mode: Zen loop names are replaced by the precard model;
    extra sys text is prepended, never dropped."""
    import precard_pipeline
    seen = {}

    def rec(api_key, model, user_text):
        seen["key"] = api_key
        seen["model"] = model
        seen["text"] = user_text
        return ("{}", {"prompt_tokens": 1, "completion_tokens": 1})

    import unittest.mock as mock
    with mock.patch.object(precard_pipeline, "_avalai_chat_transport",
                           side_effect=rec):
        wrap = precard_pipeline._avalai_remap_transport("glm-5.3-flash")
        wrap("k-av", "some-zen-model", "SYS", "USER")
    assert seen["key"] == "k-av"
    assert seen["model"] == "glm-5.3-flash"
    assert seen["text"] == "SYS\n\nUSER"


def test_full_avalai_s3_uses_precard_model(tmp_path, monkeypatch):
    """Full-line mode: S3 vector batch calls the precard model (override),
    not the Zen V15 chain."""
    import precard_pipeline
    from phrase_judge import KeyRing
    from precard_pipeline import s1_rank_item, s3_vector_batch
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    s1map = {"w:apple": s1_rank_item(item, index, read_entry)}
    s2map = {"w:apple": {"sense_id": "apple#0", "gloss": "a round fruit"}}
    seen = []

    def rec(api_key, model, user_text):
        seen.append(model)
        return (json.dumps({"results": [{"lemma": "apple", "vectors": [
            {"sense_id": "apple#0",
             "vector": [{"topic_id": 13, "topic_label": "Other / Abstract",
                         "weight": 1.0}]}]}]}), None)

    out = s3_vector_batch([item], s2map, s1map, "k", rec, lambda s: None,
                          {"done": {}, "failed": [], "backoffs": []},
                          ring=KeyRing(["k"]),
                          models=["deepseek-v4-flash"])
    assert out["apple#0"]["model"] == "deepseek-v4-flash"
    assert seen == ["deepseek-v4-flash"]
