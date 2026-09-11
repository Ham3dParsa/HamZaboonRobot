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


def test_enrich_pos_and_abbrev(tmp_path, monkeypatch):
    """R29/R32: S5 returns abbrev_expansion + pos/pos_src from the pick."""
    from precard_pipeline import enrich_item
    index = {"dvd": [{"pos": "noun",
                      "entry": {"pos": "noun", "sounds": [{"ipa": "/x/"}],
                                "senses": [{"glosses": [
                                    "Initialism of digital video disc"],
                                    "tags": [],
                                    "examples": [{"text": LONG_EXAMPLE}]}]}}]}
    item = {"kind": "word", "text": "dvd", "pos": "noun",
            "pool_level": "B1"}
    enriched = enrich_item(
        item, {"sense_id": "dvd#0",
               "gloss": "Initialism of digital video disc"},
        index, read_entry, {})
    assert enriched["abbrev_expansion"] == "digital video disc"
    assert enriched["pos"] == ["noun"]
    assert enriched["pos_src"] == "dataset"
    empty = enrich_item(item, {"sense_id": "", "gloss": ""},
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
    """V7+act-fix: a proper-topped anchor with a common sense lower in the
    window re-anchors (kept); all-proper anchors still drop with reason
    anchor-proper-noun (deterministic, no name lists)."""
    items = [{"kind": "word", "text": "Apple", "pos": "noun",
              "pool_level": "A1"},
             {"kind": "word", "text": "Banana", "pos": "noun",
              "pool_level": "A1"},
             {"kind": "word", "text": "Zambia", "pos": "noun",
              "pool_level": "A1"}]

    def name_rows():
        # name entry FIRST in file order (like real "act"): file-decay
        # crowns the proper sense, so the test exercises the reroute.
        return [
            {"pos": "name",
             "entry": {"pos": "name", "sounds": [],
                       "senses": [{"glosses": ["A tech company"], "tags": [],
                                   "examples": [{"text": LONG_EXAMPLE}]}]}},
            {"pos": "noun",
             "entry": {"pos": "noun", "sounds": [],
                       "senses": [{"glosses": ["Alternative spelling of xyz"],
                                   "tags": [],
                                   "examples": [{"text": LONG_EXAMPLE}]}]}},
        ]

    def all_name_rows():
        return [
            {"pos": "name",
             "entry": {"pos": "name", "sounds": [],
                       "senses": [{"glosses": ["A country in Africa"],
                                   "tags": [],
                                   "examples": [{"text": LONG_EXAMPLE}]}]}},
        ]

    index = {"apple": name_rows(),
             "banana": _word_rows("banana", ("a long fruit",)),
             "zambia": all_name_rows()}
    rows, s0 = _run_s0_only(tmp_path, monkeypatch, items, index,
                            _zipf_fn=lambda t: 5.0)
    # S0 keeps all (POS sets are not name-only).
    assert s0["done"]["w:Apple"]["kept"] is True
    # Apple re-anchored to the noun sense (kept, not dropped).
    assert [r["key"] for r in rows] == ["w:Apple", "w:Banana"]
    s1 = json.loads(
        (pathlib.Path(str(tmp_path / "prog")) / "s1.json").read_text(
            encoding="utf-8"))
    assert "dropped" not in s1["done"]["w:Apple"]
    assert s1["done"]["w:Apple"]["anchor_pos"] == "noun"
    assert s1["done"]["w:Apple"].get("rerouted_from_proper") is True
    assert "w:Apple" not in s1["failed"]
    # Zambia (a country) drops at S0 via the R4 country blocklist
    # (#606 — casefolded, no POS data needed), never reaching S1.
    assert s0["done"]["w:Zambia"]["kept"] is False
    assert s0["done"]["w:Zambia"]["reason"] == "r4-country-blocklist"
    assert "dropped" not in s1["done"]["w:Banana"]
    assert s1["done"]["w:Banana"]["anchor_pos"] == "noun"


def test_run_log_and_batch_lines(tmp_path, monkeypatch, capsys):
    """V7: live one-line progress per batch; run.log has stage start/end;
    each stage prints one English summary box."""
    rc, out, prog, _ = run_pipeline(tmp_path, monkeypatch)
    assert rc == 0
    logged = (tmp_path / "run.log").read_text(encoding="utf-8")
    for stage in ("s0", "s1", "s2", "s3", "s4", "s5"):
        assert ("stage %s start" % stage) in logged
        assert ("stage %s end" % stage) in logged
    captured = capsys.readouterr()
    assert "[preprocess (pishpardazesh)]" in captured.out \
        and "ok=2 fail=0" in captured.out
    assert "[STAGE preprocess" in captured.out
    assert "[STAGE enrich" in captured.out


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

    from precard_pipeline import anchor_rank_item
    index = make_index()
    ranked = anchor_rank_item(
        {"kind": "word", "text": "apple", "pos": "noun",
         "pool_level": "A1"}, index, read_entry)
    anchor_map = {"w:apple": ranked}
    batch = [{"kind": "word", "text": "apple", "pos": "noun",
              "pool_level": "A1"}]
    ring = KeyRing(["k1", "k2"])
    tele = []
    from precard_pipeline import judge_batch
    out = judge_batch(batch, anchor_map, "k1", flaky, sleeps.append,
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
    from precard_pipeline import anchor_rank_item, vectors_batch
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    ranked = anchor_rank_item(item, index, read_entry)
    anchor_map = {"w:apple": ranked}
    judge_map = {"w:apple": {"sense_id": "apple#0", "gloss": "a round fruit"}}
    sleeps, seen = [], []
    state = {"done": {}, "failed": [], "backoffs": []}

    def flaky(api_key, model, user_text):
        seen.append(api_key)
        if len(seen) == 1:
            raise _http_429()
        return fake_topics(api_key, model, user_text)

    out = vectors_batch([item], judge_map, anchor_map, "k1", flaky,
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
    # Mixed entries (stub top + one real sense) so items pass the G2
    # all-form S0 gate and reach the S0b review under test. Pure-form
    # entries die at S0 (see test_g2_*); S0b owns mixed tops.
    def rows(*glosses):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": []} for g in glosses]}}]
    return {"cats": rows("plural of cat", "feline companions"),
            "went": rows("past of go", "to move along"),
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
    from precard_pipeline import anchor_rank_item
    import card_pilot
    probe = {"kind": "word", "text": "mf", "pool_level": "B2"}
    out = anchor_rank_item(probe, {"mf": [{"pos": "noun", "offset": 0, "length": 10}]},
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
    # Mixed entries (stub top + one real sense) so items pass the G2
    # all-form S0 gate and reach the S0b review under test.
    def rows(*glosses):
        return [{"pos": "adj",
                 "entry": {"pos": "adj", "sounds": [],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": []} for g in glosses]}}]
    return {"best": rows("superlative of good", "of the highest quality"),
            "better": rows("comparative of good", "of higher quality"),
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
    from precard_pipeline import inflection_needs_review

    def rows(gloss):
        return [{"pos": "adj",
                 "entry": {"pos": "adj", "sounds": [],
                           "senses": [{"glosses": [gloss], "tags": [],
                                       "examples": []}]}}]
    index = {"biggest": rows("superlative of big"),
             "best": rows("superlative of good"),
             "good": rows("having good qualities")}
    needs, _gloss = inflection_needs_review(
        {"kind": "word", "text": "biggest", "pos": "adj"}, index,
        read_entry)
    assert needs is False  # base "big" not in index
    needs, gloss = inflection_needs_review(
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
    from precard_pipeline import anchor_rank_item, judge_batch
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    anchor_map = {"w:apple": anchor_rank_item(item, index, read_entry)}

    def tuple_judge(api_key, model, user_text):
        return (fake_judge(api_key, model, user_text),
                {"input_tokens": 11, "output_tokens": 5})

    tele = []
    out = judge_batch([item], anchor_map, "k", tuple_judge, lambda s: None,
                         {"done": {}, "failed": [], "backoffs": []},
                         telemetry=tele, tele_batch=1, ring=KeyRing(["k"]))
    assert out["w:apple"]["sense_id"] == "apple#0"
    ok = [r for r in tele if r.get("outcome") == "ok"]
    assert ok and ok[0]["prompt_tokens"] == 11
    assert ok[0]["completion_tokens"] == 5
    # Plain-text transports record None tokens without failing.
    tele2 = []
    judge_batch([item], anchor_map, "k", fake_judge, lambda s: None,
                   {"done": {}, "failed": [], "backoffs": []},
                   telemetry=tele2, tele_batch=1, ring=KeyRing(["k"]))
    ok2 = [r for r in tele2 if r.get("outcome") == "ok"]
    assert ok2 and ok2[0]["prompt_tokens"] is None
    assert ok2[0]["completion_tokens"] is None


def test_s3_tuple_usage_recorded():
    """T1: tuple (text, usage) topic transports surface tokens."""
    from phrase_judge import KeyRing
    from precard_pipeline import anchor_rank_item, vectors_batch
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    anchor_map = {"w:apple": anchor_rank_item(item, index, read_entry)}
    judge_map = {"w:apple": {"sense_id": "apple#0", "gloss": "a round fruit"}}

    def tuple_topics(api_key, model, user_text):
        return (json.dumps({"results": [{"lemma": "apple", "vectors": [
            {"sense_id": "apple#0",
             "vector": [{"topic_id": 13,
                         "topic_label": "Other / Abstract",
                         "weight": 1.0}]}]}]}),
                {"input_tokens": 13, "output_tokens": 7})

    tele = []
    out = vectors_batch([item], judge_map, anchor_map, "k", tuple_topics,
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
    from precard_pipeline import label_item
    state = {"done": {}, "failed": [], "backoffs": []}
    item = {"kind": "word", "text": "zzqx", "pool_level": "B1"}

    def garbage(api_key, model, user_text):
        return "not json {{{"

    tele = []
    assigned = label_item(
        item, "plural of zzqx", "zzqx#0", None, "k", garbage,
        lambda s: None, state, str(tmp_path / "s4.json"), {},
        telemetry=tele, tele_batch=1, ring=KeyRing(["k"]))
    assert assigned["label"] == "Other / Abstract"
    assert assigned["topic_path"] == "fallback"
    assert any(r.get("stage") == "s4" and r.get("outcome") == "fallback"
               for r in tele)


def test_enrich_path_full_and_partial():
    """T1: S5 marks full carriers vs partial (model must fill gaps)."""
    from precard_pipeline import enrich_item
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
    full = enrich_item(item, {"sense_id": "dvd#0", "gloss": "a disc"},
                          index, read_entry, {})
    assert full["enrich_path"] == "full"
    assert len(full["dataset_examples"]) == 2
    partial = enrich_item(item, {"sense_id": "", "gloss": ""},
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

def test_label_item_reraises_ratelimited():
    """OC must-fix: label_item must not swallow RateLimited into fallback."""
    import urllib.error
    import pytest
    from precard_pipeline import label_item
    from phrase_judge import KeyRing, RateLimited

    def transport_429(api_key, model, user_text):
        raise urllib.error.HTTPError("http://x", 429, "throttled", {}, None)

    with pytest.raises(RateLimited):
        label_item(
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
    assert seen["body"]["reasoning_effort"] == "low"


def test_avalai_transport_http_error_propagates(monkeypatch):
    """AvalAI chain: HTTP errors (429 rotation fuel, 401 auth) reach the
    caller untouched (rotation/auth mapping owned by shared seams)."""
    import urllib.error
    import pytest
    import precard_pipeline

    def boom_429(req, timeout=120):
        raise urllib.error.HTTPError("http://x", 429, "throttled", {},
                                     None)

    def boom_401(req, timeout=120):
        raise urllib.error.HTTPError("http://x", 401, "denied", {}, None)

    monkeypatch.setattr(precard_pipeline.urllib.request, "urlopen",
                        boom_429)
    with pytest.raises(urllib.error.HTTPError) as e429:
        precard_pipeline._avalai_chat_transport("k", "m", "u")
    assert e429.value.code == 429
    monkeypatch.setattr(precard_pipeline.urllib.request, "urlopen",
                        boom_401)
    with pytest.raises(urllib.error.HTTPError) as e401:
        precard_pipeline._avalai_chat_transport("k", "m", "u")
    assert e401.value.code == 401


def test_s2_models_override_used():
    """AvalAI chain: explicit models list replaces the Zen chain."""
    from phrase_judge import KeyRing
    from precard_pipeline import anchor_rank_item, judge_batch
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    anchor_map = {"w:apple": anchor_rank_item(item, index, read_entry)}
    seen = []

    def rec(api_key, model, user_text):
        seen.append(model)
        return fake_judge(api_key, model, user_text)

    out = judge_batch([item], anchor_map, "k", rec, lambda s: None,
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


def test_full_avalai_needs_no_zen_key(tmp_path, monkeypatch):
    """Review: --llm-provider avalai must not demand the unused Zen key.

    All transports at default (true full-line mode) + a strict loader
    with no factory/.env file fallback, so the test proves the Zen path
    is never touched — not that a local .env rescued it.
    """
    import os as _os
    import precard_pipeline
    import env_loader
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY_2", raising=False)
    monkeypatch.setenv("AVALAI_API_KEY", "avalai-key")

    def strict_loader(required=()):
        missing = [k for k in required if not _os.environ.get(k)]
        if missing:
            raise KeyError("missing: " + ", ".join(missing))
        return {k: _os.environ.get(k, "") for k in env_loader.KEYS}

    monkeypatch.setattr(env_loader, "load_factory_env", strict_loader)
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
         "--stages", "s0,s1,s2", "--llm-provider", "avalai"],
        _sleep_fn=lambda s: None, _index=make_index(),
        _read_entry=read_entry, _tatoeba={}, _zipf_fn=lambda t: 5.0)
    assert rc == 0
    assert seen and seen[0] == ("avalai-key", "glm-5.3-flash")
    s2 = json.loads(
        (pathlib.Path(prog) / "s2.json").read_text(encoding="utf-8"))
    assert s2["done"]["w:apple"]["model"] == "glm-5.3-flash"


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
    from precard_pipeline import anchor_rank_item, vectors_batch
    index = make_index()
    item = {"kind": "word", "text": "apple", "pos": "noun",
            "pool_level": "A1"}
    anchor_map = {"w:apple": anchor_rank_item(item, index, read_entry)}
    judge_map = {"w:apple": {"sense_id": "apple#0", "gloss": "a round fruit"}}
    seen = []

    def rec(api_key, model, user_text):
        seen.append(model)
        return (json.dumps({"results": [{"lemma": "apple", "vectors": [
            {"sense_id": "apple#0",
             "vector": [{"topic_id": 13, "topic_label": "Other / Abstract",
                         "weight": 1.0}]}]}]}), None)

    out = vectors_batch([item], judge_map, anchor_map, "k", rec, lambda s: None,
                          {"done": {}, "failed": [], "backoffs": []},
                          ring=KeyRing(["k"]),
                          models=["deepseek-v4-flash"])
    assert out["apple#0"]["model"] == "deepseek-v4-flash"
    assert seen == ["deepseek-v4-flash"]


def test_telemetry_flush_incremental_no_dup(tmp_path):
    """Kill-safe telemetry: stage flushes append only new records; a
    second flush is a no-op; the summary always covers the run so far."""
    import json as _json
    from telemetry import record_call
    from precard_pipeline import _flush_telemetry
    store, outdir = [], str(tmp_path / "run")
    record_call(store, stage="s2", batch_id=1, key_idx=0, model="m",
                prompt_tokens=10, completion_tokens=5)
    n = _flush_telemetry(outdir, store, 0)
    assert n == 1
    record_call(store, stage="s2", batch_id=2, key_idx=0, model="m",
                prompt_tokens=7, completion_tokens=3)
    n = _flush_telemetry(outdir, store, n)
    assert n == 2
    n = _flush_telemetry(outdir, store, n)
    assert n == 2  # nothing new: no rewrite storm
    lines = (pathlib.Path(outdir) / "telemetry_records.jsonl"
             ).read_text(encoding="utf-8").splitlines()
    assert len([l for l in lines if l.strip()]) == 2
    summary = _json.loads((pathlib.Path(outdir) / "telemetry_summary.json"
                           ).read_text(encoding="utf-8"))
    assert summary["by_stage"]["s2"]["prompt_tokens"] == 17
    assert summary["records"] == 2


def test_s1_proper_anchor_reroutes_to_common_sense():
    """act-fix: a proper-topped anchor with common senses lower in the
    window re-anchors instead of dropping; all-proper still drops."""
    from precard_pipeline import _reroute_proper_anchor, anchor_rank_item

    def rows(pos, glosses):
        return [{"pos": pos,
                 "entry": {"pos": pos, "sounds": [],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": []} for g in glosses]}}]

    index = {"act": rows("name", ["Initialism of X", "Initialism of Y"])
             + rows("noun", ["Something done, a deed"])
             + rows("verb", ["To take action"])}

    def read_entry(row):
        return row["entry"]

    item = {"kind": "word", "text": "act", "pos": "",
            "pool_level": "A1"}
    ranked = anchor_rank_item(item, index, read_entry)
    assert ranked["anchor_pos"] in card_pilot.PROPER_NOUN_POS
    rerouted = _reroute_proper_anchor(item, ranked, index, read_entry)
    assert rerouted is not None
    top, en_def, pos = rerouted
    assert pos not in card_pilot.PROPER_NOUN_POS
    assert "deed" in en_def or "action" in en_def

    # All-proper window: no reroute (true propers still drop).
    index2 = {"zambia": rows("name", ["A country in Africa"])}
    item2 = {"kind": "word", "text": "zambia", "pos": "",
             "pool_level": "A1"}
    ranked2 = anchor_rank_item(item2, index2, read_entry)
    assert _reroute_proper_anchor(item2, ranked2, index2,
                                  read_entry) is None


def _g_view(senses, poss=None):
    return {"senses": [{"gloss": g, "tags": t} for g, t in senses],
            "poss": set(poss or [])}


def _g_item(text, level="B1"):
    return {"kind": "word", "text": text, "pos": "", "pool_level": level}


def _g_classify(text, view, level="B1"):
    from precard_pipeline import preprocess_classify_item
    return preprocess_classify_item(
        _g_item(text, level), {}, lambda t: 5.0, set(), {}, False,
        entry_fn=lambda t: view)


def test_g2_drops_all_form_entries():
    v = _g_classify("arrives", _g_view(
        [("third-person singular simple present of arrive", [])]))
    assert v == {"kept": False, "reason": "g2-inflection-form",
                 "type_pending": False}


def test_g2_keeps_with_independent_sense():
    v = _g_classify("accusing", _g_view(
        [("third-person singular simple present of accuse", []),
         ("making accusations; blaming", [])]))
    assert v["kept"] is True and v.get("reason") is None


def test_g3_drops_interjections():
    v = _g_classify("ahem", _g_view(
        [("used to attract attention", [])], poss=["interj"]))
    assert v["reason"] == "g3-interjection" and v["kept"] is False


def test_g4_drops_allcaps_and_multi_abbrev():
    v = _g_classify("FEB", _g_view([("February", ["abbreviation"])]))
    assert v["reason"] == "g4-abbrev" and v["kept"] is False
    v2 = _g_classify("comp", _g_view(
        [("complimentary", ["abbreviation"]),
         ("composition", ["abbreviation"])]))
    assert v2["reason"] == "g4-abbrev" and v2["kept"] is False


def test_g4_quarantines_single_suspect():
    v = _g_classify("led", _g_view([("light-emitting diode",
                                     ["abbreviation"])]))
    assert v["kept"] is True
    assert v.get("quarantine") == "g4-abbrev"


def test_g4_keeps_real_words_with_abbrev_sense():
    v = _g_classify("think", _g_view(
        [("to believe", []), ("Think (band)", ["abbreviation"])]))
    assert v["kept"] is True and "quarantine" not in v


def test_g5_drops_demonyms():
    v = _g_classify("American", _g_view(
        [("a person from the United States; nationality American", [])]))
    assert v["reason"] == "g5-demonym" and v["kept"] is False


def test_g6_drops_obsolete_only():
    v = _g_classify("los", _g_view([("a lynx", ["obsolete"])]))
    assert v["reason"] == "g6-obsolete" and v["kept"] is False


def test_g_gates_skipped_without_entry_fn():
    from precard_pipeline import preprocess_classify_item
    v = preprocess_classify_item(_g_item("arrives"), {}, lambda t: 5.0, set(),
                         {}, False)
    assert v == {"kept": True, "reason": None, "type_pending": False}


def test_r4_country_blocklist_drops_lowercase():
    """#606: lowercase country names leak past R4 (no POS data) — the
    casefolded blocklist drops them before every other gate."""
    from precard_pipeline import preprocess_classify_item
    v = preprocess_classify_item(_g_item("bolivia", "B2"), {},
                                 lambda t: 5.0, set(), {}, False)
    assert v == {"kept": False, "reason": "r4-country-blocklist",
                 "type_pending": False}


def test_r4_capitalised_country_still_drops():
    """Bolivia still drops (now via the blocklist, which runs before the
    proper-noun gate); a non-country proper noun keeps the old
    r4-name-only path."""
    from precard_pipeline import preprocess_classify_item
    v = preprocess_classify_item(_g_item("Bolivia", "B2"),
                                 {"bolivia": {"name"}}, lambda t: 5.0,
                                 set(), {}, False)
    assert v == {"kept": False, "reason": "r4-country-blocklist",
                 "type_pending": False}
    v2 = preprocess_classify_item(_g_item("Xyzztown", "B2"),
                                  {"xyzztown": {"name"}}, lambda t: 5.0,
                                  set(), {}, False)
    assert v2 == {"kept": False, "reason": "r4-name-only",
                  "type_pending": False}


def test_f1_country_blocklist_absolute_noun_pos():
    """F1: the country blocklist is ABSOLUTE for single tokens — the old
    #606 POS-aware exemption is gone. bolivia/china/Jersey drop even when
    kaikki knows them as common nouns (china-porcelain loss accepted,
    rare); the turkey bird (ISO spelling turkiye, not in the list) stays
    keepable as the control."""
    from precard_pipeline import preprocess_classify_item
    for text, pos in (("bolivia", {"noun"}), ("china", {"noun"}),
                      ("Jersey", {"noun"})):
        v = preprocess_classify_item(
            _g_item(text, "B2"), {text.lower(): pos}, lambda t: 5.0,
            set(), {}, False)
        assert v == {"kept": False, "reason": "r4-country-blocklist",
                     "type_pending": False}, text
    bird = preprocess_classify_item(_g_item("turkey", "B2"),
                                    {"turkey": {"noun"}}, lambda t: 5.0,
                                    set(), {}, False)
    assert bird == {"kept": True, "reason": None, "type_pending": False}


def test_r4_country_blocklist_ascii_aliases():
    """#606 review: ASCII/diacritic spellings (turkiye, vietnam,
    cote d'ivoire, curacao, reunion, aland islands, são tomé and
    príncipe), separator variants (guinea-bissau/guinea bissau,
    timor-leste/timor leste, curly-apostrophe côte d’ivoire), plus a
    multi-word hit (united states of america) drop via the blocklist
    on empty POS."""
    from precard_pipeline import preprocess_classify_item
    for alias in ("turkiye", "vietnam", "cote d'ivoire", "curacao",
                  "reunion", "aland islands", "são tomé and príncipe",
                  "guinea-bissau", "guinea bissau", "timor-leste",
                  "timor leste", "côte d’ivoire",
                  "united states of america"):
        v = preprocess_classify_item(_g_item(alias, "B2"), {},
                                     lambda t: 5.0, set(), {}, False)
        assert v == {"kept": False, "reason": "r4-country-blocklist",
                     "type_pending": False}, alias


def test_r4_country_blocklist_multiword_proper_pos_drops():
    """#606 review round 4: a multi-word hit with proper-noun-only POS
    drops via the blocklist (subset test, not the single-token helper,
    which is False for any text with a space)."""
    from precard_pipeline import preprocess_classify_item
    v = preprocess_classify_item(
        _g_item("United States of America", "B2"),
        {"united states of america": {"name"}},
        lambda t: 5.0, set(), {}, False)
    assert v == {"kept": False, "reason": "r4-country-blocklist",
                 "type_pending": False}


def test_r4_country_blocklist_keeps_non_country():
    """Control: an ordinary word is untouched by the blocklist."""
    from precard_pipeline import preprocess_classify_item
    v = preprocess_classify_item(_g_item("handel", "B2"), {},
                                 lambda t: 5.0, set(), {}, False)
    assert v == {"kept": True, "reason": None, "type_pending": False}


def test_preprocess_entry_view_merges_rows_and_fails_open():
    from precard_pipeline import _preprocess_entry_view

    def rows(pos, senses):
        return [{"pos": pos,
                 "entry": {"pos": pos, "sounds": [],
                           "senses": [{"glosses": [g], "tags": t}
                                      for g, t in senses]}}]

    index = {"w": rows("noun", [("a thing", [])])
             + rows("verb", [("to want", [])])}

    def read_entry(row):
        return row["entry"]

    view = _preprocess_entry_view({"kind": "word", "text": "w"}, index,
                          read_entry)
    assert view is not None
    assert view["poss"] == {"noun", "verb"}
    assert [s["gloss"] for s in view["senses"]] == ["a thing", "to want"]

    # read_entry raising -> None (keep, never drop on uncertainty).
    def boom(row):
        raise OSError("disk gone")

    assert _preprocess_entry_view({"kind": "word", "text": "w"}, index,
                          boom) is None
    # unknown lemma -> None.
    assert _preprocess_entry_view({"kind": "word", "text": "nope"}, {}, read_entry) \
        is None
    # senseless entry -> None.
    assert _preprocess_entry_view(
        {"kind": "word", "text": "w"},
        {"w": [{"pos": "noun", "entry": {"pos": "noun"}}]},
        read_entry) is None


def test_g2_pure_form_drops_end_to_end(tmp_path, monkeypatch):
    """Coverage: pure-form entries die at S0 (g2) via the real main
    wiring (fixture index + fixture read_entry), never reaching S0b."""
    from precard_pipeline import _preprocess_entry_view  # noqa: F401 (seam ref)
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    items = [{"kind": "word", "text": "cats", "pos": "noun",
              "pool_level": "A1"}]

    def rows(*glosses):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": []} for g in glosses]}}]

    index = {"cats": rows("plural of cat")}
    sample = write_sample(tmp_path, items)
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog,
         "--stages", "s0"],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index=index, _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0)
    assert rc == 0
    s0 = json.loads(
        (pathlib.Path(prog) / "s0.json").read_text(encoding="utf-8"))
    assert s0["done"]["w:cats"]["reason"] == "g2-inflection-form"
    assert "w:cats" in s0["failed"]


def test_quarantine_surfaces_in_summary_and_log(tmp_path, monkeypatch,
                                                capsys):
    """Coverage: quarantine flag appears in the S0 box + dropped.log;
    the item itself stays live."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    items = [{"kind": "word", "text": "led", "pos": "noun",
              "pool_level": "A2"}]

    def rows():
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [],
                           "senses": [{"glosses": ["light-emitting diode"],
                                       "tags": ["abbreviation"],
                                       "examples": []}]}}]

    sample = write_sample(tmp_path, items)
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog,
         "--stages", "s0"],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index={"led": rows()}, _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0)
    assert rc == 0
    captured = capsys.readouterr()
    assert "quarantined=1" in captured.out
    drop_log = (pathlib.Path(out).parent / "dropped.log"
                ).read_text(encoding="utf-8")
    assert "w:led: quarantine-g4-abbrev" in drop_log
    s0 = json.loads(
        (pathlib.Path(prog) / "s0.json").read_text(encoding="utf-8"))
    assert s0["done"]["w:led"]["kept"] is True


def test_quarantine_reaches_precard_row(tmp_path, monkeypatch):
    """Emission: quarantine flag lands on the precard row + stage_calls."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    items = [{"kind": "word", "text": "led", "pos": "noun",
              "pool_level": "A2"}]

    def rows():
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [],
                           "senses": [{"glosses": ["light-emitting diode"],
                                       "tags": ["abbreviation"],
                                       "examples": [{"text": LONG_EXAMPLE}]}]}}]

    sample = write_sample(tmp_path, items)
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index={"led": rows()}, _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0)
    assert rc == 0
    rows_out = load_out(out)
    assert [r["key"] for r in rows_out] == ["w:led"]
    assert rows_out[0].get("quarantine") == "g4-abbrev"
    assert rows_out[0]["stage_calls"]["s0"] == "kept:quarantine-g4-abbrev"


def test_zipf_low_beats_quarantine():
    """Precedence: low-zipf suspect drops on frequency, never quarantines."""
    from precard_pipeline import preprocess_classify_item
    view = {"senses": [{"gloss": "light-emitting diode",
                        "tags": ["abbreviation"]}],
            "poss": {"noun"}}
    v = preprocess_classify_item(_g_item("led", "A1"), {}, lambda t: 1.0, set(),
                         {}, False, entry_fn=lambda t: view)
    assert v == {"kept": False, "reason": "r20-zipf-low:1.00",
                 "type_pending": False}


def test_entry_fn_exception_keeps_at_classify_level():
    """Fail-open: entry_fn raising keeps the item (no drop on error)."""
    from precard_pipeline import preprocess_classify_item

    def boom(t):
        raise OSError("gone")

    v = preprocess_classify_item(_g_item("arrives"), {}, lambda t: 5.0, set(),
                         {}, False, entry_fn=boom)
    assert v == {"kept": True, "reason": None, "type_pending": False}


def test_g4_lowercase_tags_path():
    """Calibration: lowercased multi-abbrev drops via tags (no caps);
    a lone lowercase abbrev quarantines (feb-like); zipf finishes the
    truly rare ones downstream."""
    v = _g_classify("comp", _g_view(
        [("complimentary", ["abbreviation"]),
         ("composition", ["abbreviation"])]))
    assert v["reason"] == "g4-abbrev" and v["kept"] is False
    v2 = _g_classify("feb", _g_view([("February", ["abbreviation"])]))
    assert v2["kept"] is True and v2.get("quarantine") == "g4-abbrev"


def test_g4_caps_without_tags_stays():
    """BOOK/PLAY: all-caps alone never drops (needs an abbrev tag)."""
    v = _g_classify("BOOK", _g_view([("a written work", [])]))
    assert v["kept"] is True and "quarantine" not in v


def test_g5_boundary_phrasings():
    """G5 hits canonical demonym phrasings, spares lookalikes."""
    for gloss in ("a native of France", "an inhabitant of Rome",
                  "a person from Spain",
                  "the country's national language is X",
                  "of or pertaining to Italy",
                  "Of or pertaining to Italy",
                  "OF OR PERTAINING TO Italy",
                  "of or Pertaining to Italy",
                  "of or pertaining to the United States"):
        v = _g_classify("t" + gloss[:3], _g_view([(gloss, [])]))
        assert v["reason"] == "g5-demonym", gloss
    for gloss in ("a national park", "an international treaty",
                  "a nice country walk",
                  "the country's national park is big",
                  "countryside language variety course",
                  "of or pertaining to words",
                  "of or pertaining to the words",
                  "a local custom"):
        v = _g_classify("t" + gloss[:3], _g_view([(gloss, [])]))
        assert v["kept"] is True, gloss


def test_gates_normalize_mixed_casing():
    """Caller-supplied casing (Abbreviation, Interj) still matches."""
    v = _g_classify("ahem", _g_view([("hey", [])], poss=["Interj"]))
    assert v["reason"] == "g3-interjection"
    v2 = _g_classify("comp", _g_view(
        [("x", ["Abbreviation"]), ("y", ["ABBREVIATION"])]))
    assert v2["reason"] == "g4-abbrev"


def test_g3_multi_pos_survives():
    """by/would/when: interjection among other POS rows is NOT a drop."""
    v = _g_classify("by", _g_view([("near", [])],
                                   poss=["prep", "interj"]))
    assert v["kept"] is True


def test_unknown_zipf_keeps_quarantine():
    """zipf-unknown keeps but preserves a computed quarantine flag."""

    def nozipf(t):
        return None

    from precard_pipeline import preprocess_classify_item
    view = {"senses": [{"gloss": "light-emitting diode",
                        "tags": ["abbreviation"]}],
            "poss": {"noun"}}
    v = preprocess_classify_item(_g_item("led", "A2"), {}, nozipf, set(), {},
                         False, entry_fn=lambda t: view)
    assert v["kept"] is True
    assert v["reason"] == "zipf-unknown-kept"
    assert v.get("quarantine") == "g4-abbrev"


def test_color_plain_when_piped(monkeypatch, capsys):
    """Console colors never leak into pipes/files (capsys is not a tty)."""
    from precard_pipeline import _color
    out = _color("hello", "green")
    assert out == "hello"
    assert "\x1b" not in out
    captured = capsys.readouterr()
    assert captured.out == ""


def test_parse_stage_map_validates():
    import pytest
    from precard_pipeline import _parse_stage_map, LLM_LEGS
    assert _parse_stage_map(["s2=avalai", "s4=zen"]) == {"s2": "avalai",
                                                        "s4": "zen"}
    assert _parse_stage_map([]) == {}
    assert _parse_stage_map(None) == {}
    assert set(LLM_LEGS) == {"s0b", "s2", "s3", "s4"}
    with pytest.raises(SystemExit):
        _parse_stage_map(["s9=avalai"])
    with pytest.raises(SystemExit):
        _parse_stage_map(["s2"])
    with pytest.raises(SystemExit):
        _parse_stage_map(["s2=bogus"], ("zen", "avalai"))
    with pytest.raises(SystemExit):
        _parse_stage_map(["s2="], ("zen", "avalai"))


def test_mixed_line_s2_zen_rest_avalai(tmp_path, monkeypatch):
    """Mixed providers: s2 stays Zen (default chain), s0b/s3/s4 go GLM."""
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
         "--stage-provider", "s2=zen"],
        _judge_transport=fake_judge, _topic_transport=None,
        _assign_transport=None,
        _sleep_fn=lambda s: None, _index=make_index(),
        _read_entry=read_entry, _tatoeba={}, _zipf_fn=lambda t: 5.0)
    assert rc == 0
    # s2 ran on the injected (Zen-stand-in) chain, never AvalAI...
    assert seen == []
    import json as _json
    import pathlib as _pl
    s2 = _json.loads(
        (_pl.Path(prog) / "s2.json").read_text(encoding="utf-8"))
    assert s2["done"]["w:apple"]["model"] != "glm-5.3-flash"
    # ...and the provider manifest records the mix.
    prov = _json.loads(
        (_pl.Path(out).parent / "provider_map.json").read_text(
            encoding="utf-8"))
    assert prov["s2"]["provider"] == "zen"
    assert prov["s3"]["provider"] == "avalai"
    assert prov["s3"]["model"] == "glm-5.3-flash"


def test_mixed_mode_s3_uses_avalai(tmp_path, monkeypatch):
    """Kilo: mixed mode must route S3 calls to AvalAI, not Zen default."""
    import precard_pipeline
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "zen-key")
    monkeypatch.setenv("AVALAI_API_KEY", "avalai-key")
    sample = write_sample(tmp_path, ITEMS[:1])
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    seen = []

    def rec_topic(api_key, model, user_text):
        seen.append((api_key, model))
        return (json.dumps({"results": [{"lemma": "apple", "vectors": [
            {"sense_id": "apple#0",
             "vector": [{"topic_id": 13, "topic_label": "Other / Abstract",
                         "weight": 1.0}]}]}]}), None)

    monkeypatch.setattr(precard_pipeline, "_avalai_chat_transport",
                        rec_topic)
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog,
         "--stages", "s0,s1,s2,s3", "--stage-provider", "s3=avalai",
         "--stage-model", "s3=deepseek-v4-flash"],
        _judge_transport=fake_judge, _assign_transport=None,
        _sleep_fn=lambda s: None, _index=make_index(),
        _read_entry=read_entry, _tatoeba={}, _zipf_fn=lambda t: 5.0)
    assert rc == 0
    assert seen and seen[0] == ("avalai-key", "deepseek-v4-flash")
    import json as _json
    import pathlib as _pl
    s3 = _json.loads(
        (_pl.Path(prog) / "s3.json").read_text(encoding="utf-8"))
    assert s3["done"]["w:apple"]["model"] == "deepseek-v4-flash"


def _style_rows():
    """'style' (real kaikki shape): meta bucket glosses at 0-1, fashion
    sense at 2. Pre-fix, file-decay crowns the meta bucket."""
    return [{"pos": "noun",
             "entry": {"pos": "noun", "sounds": [],
                       "senses": [
                           {"glosses": ["Senses relating to a thin, "
                                        "pointed object."],
                            "tags": ["countable", "uncountable"],
                            "examples": []},
                           {"glosses": ["Senses relating to a thin, "
                                        "pointed object."],
                            "tags": ["countable", "historical",
                                     "uncountable"],
                            "examples": []},
                           {"glosses": ["A particular manner of "
                                        "creating, doing, or presenting "
                                        "something, especially one that "
                                        "is typical of a person"],
                            "tags": ["countable", "uncountable"],
                            "examples": []}]}}]


def test_register_meta_penalty_prefers_fashion_over_bucket():
    """#607: kaikki grouped meta-glosses must not crown over a common
    sense (real style shape: bucket #0-1 vs fashion #2)."""
    scored = card_pilot.score_senses(
        "style", _style_rows(), "noun", read_entry,
        zipf_fn=lambda t: 5.0)
    top_gloss = scored[0][4]
    assert "particular manner" in top_gloss, scored[0][:2]


def test_register_meta_all_meta_still_anchors():
    """Pin the 'relative, never a drop' guarantee: an all-meta word
    still anchors (scored[0] + pick_anchor non-empty)."""
    rows = [{"pos": "noun",
             "entry": {"pos": "noun", "sounds": [],
                       "senses": [
                           {"glosses": ["Senses relating to X."],
                            "tags": ["countable"], "examples": []},
                           {"glosses": ["Senses relating to Y."],
                            "tags": ["uncountable"], "examples": []}]}}]
    scored = card_pilot.score_senses(
        "thing", rows, "noun", read_entry, zipf_fn=lambda t: 5.0)
    assert scored, "all-meta word must still anchor"
    assert card_pilot._is_meta_gloss(scored[0][4])
    sid, gloss = card_pilot.pick_anchor_sense(
        "thing", rows, "noun", read_entry)
    assert sid and gloss, (sid, gloss)


def test_register_meta_interleaved_deep_demotes():
    """Meta buckets interleaved at deeper file indices still sort
    strictly after every real sense (equal pre-scores)."""
    rows = [{"pos": "noun",
             "entry": {"pos": "noun", "sounds": [],
                       "senses": [
                           {"glosses": ["A real sense one."],
                            "tags": ["countable"], "examples": []},
                           {"glosses": ["Senses relating to Z."],
                            "tags": ["countable"], "examples": []},
                           {"glosses": ["A real sense two."],
                            "tags": ["countable"], "examples": []},
                           {"glosses": ["Senses relating to W."],
                            "tags": ["countable"], "examples": []}]}}]
    scored = card_pilot.score_senses(
        "thing", rows, "noun", read_entry, zipf_fn=lambda t: 5.0)
    flags = [card_pilot._is_meta_gloss(g) for _, _, _, _, g in scored]
    assert flags == [False, False, True, True], flags


def test_stage_labels_cover_all_ids_ascii_only():
    """v13 identity: every stable id has a name + Finglish tag; console
    labels stay plain ASCII (Windows terminal safe); unknown ids pass
    through both helpers unchanged."""
    for stage in precard_pipeline.STAGES:
        name = precard_pipeline.STAGE_NAMES[stage]
        tag = precard_pipeline.STAGE_FINGLESH[stage]
        label = precard_pipeline.stage_label(stage)
        assert name and tag and label.startswith(name)
        label.encode("ascii")
    assert precard_pipeline.stage_name("sx") == "sx"
    assert precard_pipeline.stage_label("sx") == "sx"


def test_stage_selection_accepts_names():
    """v13 identity: --only/--stages take ids or display names."""
    ns = precard_pipeline._normalize_stage
    assert ns("judge") == "s2"
    assert ns("S2") == "s2"
    assert ns("bogus") == "bogus"


def test_dropped_log_headers_use_stable_ids(tmp_path, monkeypatch):
    """v13 identity: dropped.log section headers carry the stable stage
    id (greppable on disk); the console label stays human-readable."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    items = [{"kind": "word", "text": "led", "pos": "noun",
              "pool_level": "A2"}]

    def rows():
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [],
                           "senses": [{"glosses": ["light-emitting diode"],
                                       "tags": ["abbreviation"],
                                       "examples": []}]}}]

    sample = write_sample(tmp_path, items)
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog,
         "--stages", "s0"],
        _judge_transport=fake_judge, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index={"led": rows()}, _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0)
    assert rc == 0
    drop_log = (pathlib.Path(out).parent / "dropped.log"
                ).read_text(encoding="utf-8")
    headers = [line for line in drop_log.splitlines()
               if line.startswith("===")]
    assert headers, drop_log
    assert any(line == "=== s0 drops ===" for line in headers), headers
    assert not any("langar" in line for line in headers), headers


# ---------------- C3 pack wirings: lexical_type / register / pre_card_id ---

def _tagged_rows(*gloss_tags, ipa="/x/"):
    """Fake kaikki rows with per-sense kaikki tags."""
    return [{"pos": "noun",
             "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                       "senses": [{"glosses": [gloss], "tags": list(tags),
                                   "examples": [{"text": LONG_EXAMPLE}]}
                                  for gloss, tags in gloss_tags]}}]


def test_c3a_word_lexical_type_from_kaikki_tags():
    """C3a: picked-sense kaikki tags drive lexical_type (word default)."""
    from precard_pipeline import enrich_item
    index = {
        "simp": _tagged_rows(("a silly person", ["slang"])),
        "chap": _tagged_rows(("a fellow", ["colloquial"])),
        "kicker": _tagged_rows(("an unexpected twist", ["idiomatic"])),
        "apple": _tagged_rows(("a round fruit", [])),
    }
    for text, gloss, want in (
            ("simp", "a silly person", "slang"),
            ("chap", "a fellow", "colloquial"),
            ("kicker", "an unexpected twist", "idiomatic"),
            ("apple", "a round fruit", "word")):
        item = {"kind": "word", "text": text, "pos": "noun",
                "pool_level": "B1"}
        out = enrich_item(item, {"sense_id": "%s#0" % text, "gloss": gloss},
                          index, read_entry, {})
        assert out["lexical_type"] == want, text


def test_c3b_register_from_kaikki_tags():
    """C3b: neutral default; informal tag; vulgar/offensive -> slang_vulgar
    (slang_vulgar wins over informal)."""
    from precard_pipeline import enrich_item
    cases = (
        ("plainwd", [], "neutral"),
        ("mate", ["informal"], "informal"),
        ("mfwd", ["vulgar"], "slang_vulgar"),
        ("slurwd", ["offensive"], "slang_vulgar"),
        ("bothwd", ["informal", "vulgar"], "slang_vulgar"),
    )
    for text, tags, want in cases:
        index = {text: _tagged_rows(("a gloss here", tags))}
        item = {"kind": "word", "text": text, "pos": "noun",
                "pool_level": "B1"}
        out = enrich_item(item, {"sense_id": "%s#0" % text,
                                 "gloss": "a gloss here"},
                          index, read_entry, {})
        assert out["register"] == want, text


def test_c3a_phrase_lexical_type_from_type_log():
    """C3a: phrases take lexical_type from the phrase-type log verbatim;
    without a log entry the kaikki/default fallback applies (type_pending
    flag path itself unchanged)."""
    from precard_pipeline import enrich_item
    index = {"nickel and dime": _tagged_rows(("a small sum", []))}
    item = {"kind": "phrase", "text": "nickel and dime", "pool_level": "B1"}
    pick = {"sense_id": "nickel and dime#0", "gloss": "a small sum"}
    logged = enrich_item(
        item, pick, index, read_entry, {},
        phrase_entry={"phrase_type": "idiom", "applied_keep": True})
    assert logged["lexical_type"] == "idiom"
    bare = enrich_item(item, pick, index, read_entry, {})
    assert bare["lexical_type"] == "word"


def test_c3c_pre_card_id_stable_and_en_sensitive():
    """C3c: sha1-hex16(lemma.lower|pos|en_def normalized); stable across
    case/whitespace variants, changes when EN gloss or POS changes."""
    from precard_pipeline import compute_pre_card_id
    base = compute_pre_card_id("Apple", "noun", "a round  fruit")
    assert base == compute_pre_card_id("apple", "noun", "a round fruit")
    assert base == compute_pre_card_id("  APPLE ", "NOUN", "A Round Fruit")
    assert len(base) == 16
    assert all(c in "0123456789abcdef" for c in base)
    assert compute_pre_card_id(
        "apple", "noun", "a tech company") != base
    assert compute_pre_card_id(
        "apple", "verb", "a round fruit") != base


def test_c3_rows_carry_new_fields(tmp_path, monkeypatch):
    """C3 end-to-end: precard rows carry lexical_type/register/pre_card_id
    (simp->slang, nickel and dime->idiom via log, plain word->word)."""
    from precard_pipeline import compute_pre_card_id
    items = [
        {"kind": "word", "text": "simp", "pos": "noun",
         "pool_level": "B1"},
        {"kind": "phrase", "text": "nickel and dime", "pool_level": "B1"},
        {"kind": "word", "text": "apple", "pos": "noun",
         "pool_level": "A1"},
    ]
    index = {
        "simp": _tagged_rows(("a silly person", ["slang"])),
        "nickel and dime": _tagged_rows(("a small sum", [])),
        "apple": _tagged_rows(("a round fruit", [])),
    }
    rows, _s0 = _run_s0_only(
        tmp_path, monkeypatch, items, index,
        _zipf_fn=lambda t: 5.0,
        _type_map={"nickel and dime": {"phrase_type": "idiom",
                                       "applied_keep": True}},
        _type_log_available=True)
    by_key = {r["key"]: r for r in rows}
    assert set(by_key) == {"w:simp", "p:nickel and dime", "w:apple"}
    assert by_key["w:simp"]["lexical_type"] == "slang"
    assert by_key["p:nickel and dime"]["lexical_type"] == "idiom"
    assert by_key["w:apple"]["lexical_type"] == "word"
    for rec in rows:
        assert rec["register"] in ("neutral", "informal", "slang_vulgar")
        assert len(rec["pre_card_id"]) == 16
    assert by_key["w:apple"]["register"] == "neutral"
    apple = by_key["w:apple"]
    assert apple["pre_card_id"] == compute_pre_card_id(
        "apple", apple["pos"][0], apple["en_def"])


def test_c3_helpers_normalize_messy_tags():
    """C3 review: public helpers normalize casing/whitespace themselves
    (a raw "Slang"/" Vulgar " tag must map, never fall to the default)."""
    from precard_pipeline import lexical_type_for, register_for
    assert lexical_type_for("word", ["Slang"]) == "slang"
    assert lexical_type_for("word", [" colloquial "]) == "colloquial"
    assert lexical_type_for("word", "IDIOMATIC") == "idiomatic"
    assert register_for(["INFORMAL"]) == "informal"
    assert register_for([" Vulgar "]) == "slang_vulgar"
    assert lexical_type_for(
        "phrase", [],
        {"phrase_type": "Idiom", "applied_keep": True}) == "idiom"


def test_c3_empty_pick_still_emits_fields():
    """C3 review: the empty-sid early-return path emits the three fields
    (word/neutral defaults + stable id; phrase keeps its log type)."""
    from precard_pipeline import compute_pre_card_id, enrich_item
    item = {"kind": "word", "text": "ghostwd", "pos": "noun",
            "pool_level": "A1"}
    out = enrich_item(item, {"sense_id": "", "gloss": ""},
                      {}, read_entry, {})
    assert out["lexical_type"] == "word"
    assert out["register"] == "neutral"
    assert out["pre_card_id"] == compute_pre_card_id(
        "ghostwd", "noun", "")
    phrase = enrich_item(
        {"kind": "phrase", "text": "x y", "pool_level": "B1"},
        {"sense_id": "", "gloss": ""}, {}, read_entry, {},
        phrase_entry={"phrase_type": "proverb", "applied_keep": True})
    assert phrase["lexical_type"] == "proverb"
    assert phrase["register"] == "neutral"


def test_c3_s5_resume_reenriches_legacy_entries(tmp_path, monkeypatch):
    """C3 review: pre-C3 s5 progress entries (no pre_card_id) re-enrich
    deterministically on resume instead of emitting default rows. F3:
    the slang-tagged simp re-enriches to informal (register floor)."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    items = [{"kind": "word", "text": "simp", "pos": "noun",
              "pool_level": "B1"}]
    sample = write_sample(tmp_path, items)
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")
    index = {"simp": _tagged_rows(("a silly person", ["slang"]))}
    argv = ["--sample", sample, "--out", out, "--progress-dir", prog]
    common = dict(_judge_transport=fake_judge,
                  _topic_transport=fake_topics, _assign_transport=None,
                  _sleep_fn=lambda s: None, _index=index,
                  _read_entry=read_entry, _tatoeba={},
                  _zipf_fn=lambda t: 5.0)
    assert precard_main(argv, **common) == 0
    # Simulate a pre-C3 resume state: strip the C3 keys from s5.
    s5_path = pathlib.Path(prog) / "s5.json"
    state = json.loads(s5_path.read_text(encoding="utf-8"))
    for entry in state["done"].values():
        for field in ("lexical_type", "register", "pre_card_id"):
            entry.pop(field, None)
    s5_path.write_text(json.dumps(state), encoding="utf-8")
    assert precard_main(argv, **common) == 0  # resume
    rows = load_out(out)
    assert rows[0]["lexical_type"] == "slang"
    assert rows[0]["register"] == "informal"  # F3 floor (was neutral pre-F3)
    assert len(rows[0]["pre_card_id"]) == 16


def test_default_tatoeba_pool_missing_warns_loud(tmp_path, capsys,
                                                     monkeypatch):
    """Namespace tooth: deleting the pinned default pool must scream,
    not silently disable examples."""
    missing = str(tmp_path / "gone.json")
    monkeypatch.setattr(card_pilot, "DEFAULT_TATOEBA_POOL", missing)
    assert card_pilot.load_tatoeba_pool(missing) == {}
    captured = capsys.readouterr()
    assert "WARNING: default Tatoeba pool missing" in \
        captured.out + captured.err


def test_custom_tatoeba_pool_missing_stays_silent(tmp_path, capsys):
    """Explicit custom paths keep fail-open silence (tests, runs)."""
    assert card_pilot.load_tatoeba_pool(
        str(tmp_path / "nope.json")) == {}
    captured = capsys.readouterr()
    assert "WARNING" not in captured.out + captured.err


def test_default_topic_vectors_missing_warns_loud(tmp_path, capsys,
                                                  monkeypatch):
    """Same tooth for the topic pool (pathlib spelling also matches)."""
    import pathlib
    missing = tmp_path / "gone.json"
    monkeypatch.setattr(card_pilot, "DEFAULT_TOPIC_VECTORS",
                        str(missing).replace("\\", "/"))
    assert card_pilot.load_topic_vectors(missing) == {}
    captured = capsys.readouterr()
    assert "WARNING: default topic vectors missing" in \
        captured.out + captured.err

def test_pinned_default_backslash_spelling_matches(tmp_path, capsys,
                                                   monkeypatch):
    """Either slash style names the pinned default (POSIX-safe fold)."""
    missing = str(tmp_path / "gone.json")
    monkeypatch.setattr(card_pilot, "DEFAULT_TATOEBA_POOL", missing)
    forward = missing.replace(chr(92), "/")
    backward = missing.replace("/", chr(92))
    assert card_pilot._is_pinned_default(forward, missing) is True
    assert card_pilot._is_pinned_default(backward, missing) is True
    assert card_pilot.load_tatoeba_pool(backward) == {}
    captured = capsys.readouterr()
    assert "WARNING: default Tatoeba pool missing" in (
        captured.out + captured.err)


def test_pinned_default_case_variant_matches(tmp_path, capsys,
                                               monkeypatch):
    """Windows spellings differing only by case still name the pinned
    default (normcase fold; simulated so the tooth holds on POSIX CI)."""
    pinned = str(tmp_path / "Pinned.json")
    monkeypatch.setattr(card_pilot, "DEFAULT_TATOEBA_POOL", pinned)
    monkeypatch.setattr(os.path, "normcase",
                        lambda s: os.path.normpath(s).lower())
    assert card_pilot._is_pinned_default(pinned.upper(), pinned) is True
    assert card_pilot.load_tatoeba_pool(pinned.upper()) == {}
    captured = capsys.readouterr()
    assert "WARNING: default Tatoeba pool missing" in (
        captured.out + captured.err)


def test_pinned_tatoeba_pool_corrupt_warns_loud(tmp_path, capsys,
                                                monkeypatch):
    """Unreadable-but-present pinned pool still screams (missing tooth
    covers the corrupt/wrong-shape branch too)."""
    pinned = tmp_path / "pool.json"
    pinned.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(card_pilot, "DEFAULT_TATOEBA_POOL", str(pinned))
    assert card_pilot.load_tatoeba_pool(str(pinned)) == {}
    captured = capsys.readouterr()
    assert "WARNING: default Tatoeba pool missing" in (
        captured.out + captured.err)


def test_pinned_topic_vectors_nonlist_warns_unreadable(tmp_path, capsys,
                                                       monkeypatch):
    """Present-but-wrong-shape pinned topic file warns unreadable."""
    pinned = tmp_path / "topics.json"
    pinned.write_text(json.dumps({"x": 1}), encoding="utf-8")
    monkeypatch.setattr(card_pilot, "DEFAULT_TOPIC_VECTORS", str(pinned))
    assert card_pilot.load_topic_vectors(str(pinned)) == {}
    captured = capsys.readouterr()
    assert "WARNING: default topic vectors unreadable" in (
        captured.out + captured.err)


# ---------------- F2: anchor name-gloss reroute-or-drop ----------------

def _name_rows(*glosses, pos="noun"):
    return [{"pos": pos,
             "entry": {"pos": pos, "sounds": [],
                       "senses": [{"glosses": [g], "tags": [],
                                   "examples": []} for g in glosses]}}]


def _name_rows_tagged(gloss_tags, pos="noun"):
    """Fake kaikki rows with per-sense (gloss, tags) pairs."""
    return [{"pos": pos,
             "entry": {"pos": pos, "sounds": [],
                       "senses": [{"glosses": [g], "tags": list(tags),
                                   "examples": []}
                                  for g, tags in gloss_tags]}}]


def test_f2_name_gloss_pattern():
    """F2: given/surname/place-name gloss heads match (incl. male/female
    variants); ordinary glosses and mid-sentence mentions do not."""
    from precard_pipeline import _is_name_gloss
    for gloss in ("A given name.", "A female given name.",
                  "A male given name.", "A surname.",
                  "A family name.", "A place name.",
                  "A unisex given name.", "A masculine given name.",
                  "A feminine given name.", "A first name.",
                  "A last name.", "A maiden name.", "A nickname.",
                  "An English surname.", "A Norman surname.",
                  "A German family name.", "A diminutive of Robert.",
                  "A pet form of Elizabeth.", "A short form of Thomas.",
                  "A French-Canadian surname.",
                  "A São Tomé surname."):
        assert _is_name_gloss(gloss) is True, gloss
    for gloss in ("a round fruit", "A dictionary of surnames.",
                  "a visible mark", "past of remove", "",
                  "A diminutive suffix.", "A variant of the plan."):
        # Boundary (review): bare "diminutive" is NOT a head — it would
        # collide with the real "diminutive suffix" linguistics sense;
        # bare "variant" is NOT a head either ("A variant of the plan"
        # is a real sense; bare "Variant of X" is owned by xref R34).
        assert _is_name_gloss(gloss) is False, gloss


def test_f2_name_top_reroutes_to_first_non_name():
    """F2 act-fix pattern: a name-gloss anchor top re-anchors onto the
    first non-name candidate (re-ranked first, POS follows the target)."""
    from precard_pipeline import (_reroute_name_gloss_anchor,
                                  anchor_rank_item)
    index = {"gillian": _name_rows("A female given name.",
                                   "a small songbird")}
    item = {"kind": "word", "text": "gillian", "pos": "",
            "pool_level": "B1"}
    ranked = anchor_rank_item(item, index, read_entry)
    assert ranked["top"]["gloss"] == "A female given name."
    rerouted = _reroute_name_gloss_anchor(item, ranked, index, read_entry)
    assert rerouted is not None
    top, en_def, pos = rerouted
    assert en_def == "a small songbird"
    assert top["sense_id"] == "gillian#1"
    assert ranked["candidates"][0]["sense_id"] == "gillian#1"
    # All-names window: no reroute (true names still drop).
    index2 = {"gillian": _name_rows("A female given name.")}
    ranked2 = anchor_rank_item(
        {"kind": "word", "text": "gillian", "pos": "",
         "pool_level": "B1"}, index2, read_entry)
    assert _reroute_name_gloss_anchor(
        {"kind": "word", "text": "gillian"}, ranked2, index2,
        read_entry) is None


def test_f2_reroute_keeps_on_unresolvable_pos():
    """Review W3: an unresolvable target POS ("") is uncertainty, not
    disqualification — the gloss signal already picked the target, so
    the item reroutes (anchor_pos "") instead of dropping."""
    from precard_pipeline import _reroute_name_gloss_anchor
    ranked = {"top": {"sense_id": "gillian#0",
                      "gloss": "A female given name."},
              "candidates": [
                  {"sense_id": "gillian#0",
                   "gloss": "A female given name."},
                  {"sense_id": "zzz#99", "gloss": "a small songbird"}]}
    rerouted = _reroute_name_gloss_anchor(
        {"kind": "word", "text": "gillian"}, ranked, {}, read_entry)
    assert rerouted is not None
    top, en_def, pos = rerouted
    assert (top["sense_id"], en_def, pos) == ("zzz#99",
                                             "a small songbird", "")


def test_f2_helper_error_keeps_input_top():
    """Review W-b: a lookup/structure error inside the helper keeps the
    input top (marked name_eval_error, no reroute flag) instead of
    returning None (which the caller would drop)."""
    from precard_pipeline import _reroute_name_gloss_anchor
    ranked = {"top": {"sense_id": "gillian#0",
                      "gloss": "A female given name."},
              "anchor_pos": "noun",
              "candidates": ["BOOM"]}  # str.get -> AttributeError
    out = _reroute_name_gloss_anchor(
        {"kind": "word", "text": "gillian"}, ranked, {}, read_entry)
    assert out is not None
    top, en_def, pos = out
    assert (top["sense_id"], en_def, pos) == (
        "gillian#0", "A female given name.", "noun")
    assert ranked.get("name_eval_error") is True
    assert "rerouted_from_name" not in ranked


def test_f2_s1_error_path_keeps_item(tmp_path, monkeypatch):
    """Review W-b end-to-end: a target-POS lookup failure in S1 keeps
    the item on its anchor top (marked, unflagged, undropped) instead
    of dropping it as anchor-name-gloss."""
    import precard_pipeline as pp
    real_picked = pp._picked_entry_pos

    def flaky(item, sense_id, index, read_entry):
        if (sense_id or "") == "gillianx#1":
            raise AttributeError("simulated lookup failure")
        return real_picked(item, sense_id, index, read_entry)

    monkeypatch.setattr(pp, "_picked_entry_pos", flaky)
    items = [{"kind": "word", "text": "gillianx", "pos": "noun",
              "pool_level": "B1"}]
    index = {"gillianx": _name_rows("A female given name.",
                                    "a small songbird")}
    rows, _s0 = _run_s0_only(tmp_path, monkeypatch, items, index,
                             _zipf_fn=lambda t: 5.0)
    assert [r["key"] for r in rows] == ["w:gillianx"]  # kept, not dropped
    s1 = json.loads(
        (pathlib.Path(str(tmp_path / "prog")) / "s1.json").read_text(
            encoding="utf-8"))
    done = s1["done"]["w:gillianx"]
    assert "dropped" not in done
    assert done.get("rerouted_from_name") is not True
    assert done["top"]["gloss"] == "A female given name."
    assert done.get("name_eval_error") is True


def test_f2_reroute_onto_vulgar_target_drops(tmp_path, monkeypatch):
    """Review OC-W1: a name-top rerouting onto a vulgar-tagged sense must
    not leak a vulgar card on stale anchor_tags — S1 drops it as
    vulgar-anchor with the target's tags on the entry."""
    items = [{"kind": "word", "text": "gillianv", "pos": "noun",
              "pool_level": "B1"}]
    index = {"gillianv": _name_rows_tagged(
        [("A female given name.", []), ("a crude insult", ["vulgar"])])}
    rows, _s0 = _run_s0_only(tmp_path, monkeypatch, items, index,
                             _zipf_fn=lambda t: 5.0)
    assert rows == []  # dropped items never reach precard.jsonl
    s1 = json.loads(
        (pathlib.Path(str(tmp_path / "prog")) / "s1.json").read_text(
            encoding="utf-8"))
    done = s1["done"]["w:gillianv"]
    assert done["dropped"] == "vulgar-anchor"
    assert "vulgar" in (done.get("anchor_tags") or [])
    assert "w:gillianv" in s1["failed"]


def test_f2_real_words_untouched_and_all_names_drop(tmp_path, monkeypatch):
    """F2 end-to-end: mark (real top, name sense lower) keeps its anchor
    with no reroute flag; all-names gillian drops as anchor-name-gloss;
    mixed gillian reroutes and survives."""
    items = [{"kind": "word", "text": "mark", "pos": "noun",
              "pool_level": "B1"},
             {"kind": "word", "text": "gillian", "pos": "noun",
              "pool_level": "B1"},
             {"kind": "word", "text": "gillianx", "pos": "noun",
              "pool_level": "B1"}]
    index = {"mark": _name_rows("a visible mark", "A male given name."),
             "gillian": _name_rows("A female given name."),
             "gillianx": _name_rows("A female given name.",
                                     "a small songbird")}
    rows, _s0 = _run_s0_only(tmp_path, monkeypatch, items, index,
                             _zipf_fn=lambda t: 5.0)
    assert {r["key"] for r in rows} == {"w:mark", "w:gillianx"}
    s1 = json.loads(
        (pathlib.Path(str(tmp_path / "prog")) / "s1.json").read_text(
            encoding="utf-8"))
    assert s1["done"]["w:mark"]["top"]["gloss"] == "a visible mark"
    assert "rerouted_from_name" not in s1["done"]["w:mark"]
    assert s1["done"]["w:gillian"]["dropped"] == "anchor-name-gloss"
    assert "w:gillian" in s1["failed"]
    assert s1["done"]["w:gillianx"].get("rerouted_from_name") is True
    assert s1["done"]["w:gillianx"]["top"]["gloss"] == "a small songbird"


# ---------------- F3: slang/colloquial register floor ----------------

def test_f3_slang_colloquial_floor_informal():
    """F3: slang/colloquial sense tags imply at least informal (vulgar
    still wins; plain words stay neutral)."""
    from precard_pipeline import register_for
    assert register_for(["slang"]) == "informal"
    assert register_for(["colloquial"]) == "informal"
    assert register_for(["Slang"]) == "informal"  # normalized here
    assert register_for(["vulgar"]) == "slang_vulgar"
    assert register_for(["slang", "vulgar"]) == "slang_vulgar"
    assert register_for(["colloquial", "offensive"]) == "slang_vulgar"
    assert register_for(["informal"]) == "informal"
    assert register_for([]) == "neutral"


def test_f3_slang_word_enriches_informal(tmp_path, monkeypatch):
    """F3 end-to-end: kush/recon-style slang tags land informal (not
    neutral) on the precard row."""
    items = [{"kind": "word", "text": "kush", "pos": "noun",
              "pool_level": "B1"}]
    index = {"kush": _tagged_rows(("a strain of cannabis", ["slang"]))}
    rows, _s0 = _run_s0_only(tmp_path, monkeypatch, items, index,
                             _zipf_fn=lambda t: 5.0)
    assert len(rows) == 1
    assert rows[0]["register"] == "informal"
    assert rows[0]["lexical_type"] == "slang"


# ---------------- F4: post-judge inflection-stub veto ----------------

def test_f4_veto_falls_back_to_anchor_top_non_stub():
    """F4: a judged pick whose gloss is a mechanical-inflection reference
    falls back to the anchor-top non-stub; real picks, empty picks, and
    all-stub windows stay untouched (fail-closed)."""
    from precard_pipeline import _veto_inflection_pick
    anchor = {"candidates": [
        {"sense_id": "removed#0", "gloss": "to take away"},
        {"sense_id": "removed#1", "gloss": "simple past of remove"}]}
    sid, gloss = _veto_inflection_pick(
        {"sense_id": "removed#1", "gloss": "simple past of remove"},
        anchor)
    assert (sid, gloss) == ("removed#0", "to take away")
    # Real pick untouched.
    assert _veto_inflection_pick(
        {"sense_id": "removed#0", "gloss": "to take away"},
        anchor) == ("removed#0", "to take away")
    # Empty pick untouched.
    assert _veto_inflection_pick({"sense_id": "", "gloss": ""},
                                 anchor) == ("", "")
    # All-stub window: keep the original (never veto into nothing).
    all_stub = {"candidates": [
        {"sense_id": "went#0", "gloss": "past of go"}]}
    assert _veto_inflection_pick(
        {"sense_id": "went#0", "gloss": "past of go"},
        all_stub) == ("went#0", "past of go")
    # Review W1: bare "comparative" without "of" is a real gloss, not a
    # stub ("a comparative study" must not veto into another sense).
    assert _veto_inflection_pick(
        {"sense_id": "study#0", "gloss": "a comparative study"},
        {"candidates": [{"sense_id": "study#0",
                         "gloss": "a comparative study"},
                        {"sense_id": "study#1",
                         "gloss": "to examine closely"}]}) == (
        "study#0", "a comparative study")


def test_f4_judge_stub_pick_vetoed_end_to_end(tmp_path, monkeypatch):
    """F4 end-to-end: the judge picking forcing#1 (present participle of
    force) resolves to the real forcing#0 sense in the precard row."""
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    items = [{"kind": "word", "text": "forcing", "pos": "noun",
              "pool_level": "B1"}]
    index = {"forcing": _name_rows("the act of compelling",
                                   "present participle of force")}
    sample = write_sample(tmp_path, items)
    out, prog = str(tmp_path / "precard.jsonl"), str(tmp_path / "prog")

    def stub_judge(api_key, model, user_text):
        return json.dumps({"results": [
            {"key": "w:forcing", "pick": "forcing#1"}]})

    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=stub_judge, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=lambda s: None,
        _index=index, _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0)
    assert rc == 0
    rows = load_out(out)
    assert len(rows) == 1
    assert rows[0]["sense_id"] == "forcing#0"
    assert rows[0]["en_def"] == "the act of compelling"


def test_label_batch_16_items_single_call():
    """B1: 16 items share exactly 1 LLM call; prompt holds all 16."""
    import precard_pipeline
    from precard_pipeline import label_batch
    from phrase_judge import KeyRing

    assert precard_pipeline.LABEL_BATCH == 16
    items = [{"kind": "word", "text": "w%02d" % i, "pool_level": "B1"}
             for i in range(16)]
    from precard_pipeline import item_key
    picks = {item_key(it): {"sense_id": "%s#0" % it["text"],
                            "gloss": "gloss %s" % it["text"]}
             for it in items}
    calls = []

    def fake_transport(api_key, model, user_text):
        calls.append(user_text)
        results = []
        for it in items:
            sid = "%s#0" % it["text"]
            results.append({
                "lemma": it["text"], "senses": [{
                    "sense_id": sid, "topic_id": 4,
                    "topic_label": "Work & Careers",
                    "confidence": 0.9, "vector": [{
                        "topic_id": 4,
                        "topic_label": "Work & Careers",
                        "weight": 1.0}]}]})
        return json.dumps({"results": results})

    state = {"done": {}, "failed": [], "backoffs": []}
    out = label_batch(
        items, picks, None, "k", fake_transport, lambda s: None, state,
        None, {}, ring=KeyRing(["k"]),
        lookup=lambda t, g: None)
    assert len(calls) == 1
    for it in items:
        assert it["text"] in calls[0]
        assert ("%s#0" % it["text"]) in calls[0]
    assert len(out) == 16
    for it in items:
        row = out[item_key(it)]
        assert row["label"] == "Work & Careers"
        assert row["topic_path"] == "llm"


def test_label_batch_salvages_valid_rows():
    """B1: one malformed row fails closed only its own item."""
    from precard_pipeline import item_key, label_batch
    from phrase_judge import KeyRing

    items = [{"kind": "word", "text": "good", "pool_level": "B1"},
             {"kind": "word", "text": "bad", "pool_level": "B1"}]
    picks = {item_key(it): {"sense_id": "%s#0" % it["text"],
                            "gloss": "gloss %s" % it["text"]}
             for it in items}

    def fake_transport(api_key, model, user_text):
        return json.dumps({"results": [
            {"lemma": "good", "senses": [{
                "sense_id": "good#0", "topic_id": 4,
                "topic_label": "Work & Careers", "confidence": 0.9,
                "vector": [{"topic_id": 4,
                            "topic_label": "Work & Careers",
                            "weight": 1.0}]}]},
            {"lemma": "bad", "senses": [{
                "sense_id": "bad#0", "topic_id": 99,
                "topic_label": "Nope", "confidence": 0.9,
                "vector": [{"topic_id": 99, "topic_label": "Nope",
                            "weight": 1.0}]}]}]})

    state = {"done": {}, "failed": [], "backoffs": []}
    out = label_batch(
        items, picks, None, "k", fake_transport, lambda s: None, state,
        None, {}, ring=KeyRing(["k"]),
        lookup=lambda t, g: None)
    assert out[item_key(items[0])]["topic_path"] == "llm"
    assert out[item_key(items[0])]["label"] == "Work & Careers"
    assert out[item_key(items[1])]["topic_path"] == "fallback"
    assert out[item_key(items[1])]["label"] == "Other / Abstract"


def test_label_batch_duplicate_lemma_text():
    """B1: word+phrase sharing a lemma text both resolve (no collapse)."""
    from precard_pipeline import item_key, label_batch
    from phrase_judge import KeyRing

    items = [{"kind": "word", "text": "run", "pool_level": "B1"},
             {"kind": "phrase", "text": "run", "pool_level": "B1"}]
    assert item_key(items[0]) != item_key(items[1])
    picks = {item_key(it): {"sense_id": "run#0",
                            "gloss": "gloss %s" % item_key(it)}
             for it in items}
    calls = []

    def fake_transport(api_key, model, user_text):
        calls.append(user_text)
        return json.dumps({"results": [
            {"lemma": "run", "senses": [{
                "sense_id": "run#0", "topic_id": 14,
                "topic_label": "Sports & Leisure", "confidence": 0.9,
                "vector": [{"topic_id": 14,
                            "topic_label": "Sports & Leisure",
                            "weight": 1.0}]}]},
            {"lemma": "run", "senses": [{
                "sense_id": "run#0", "topic_id": 14,
                "topic_label": "Sports & Leisure", "confidence": 0.8,
                "vector": [{"topic_id": 14,
                            "topic_label": "Sports & Leisure",
                            "weight": 1.0}]}]}]})

    state = {"done": {}, "failed": [], "backoffs": []}
    out = label_batch(
        items, picks, None, "k", fake_transport, lambda s: None, state,
        None, {}, ring=KeyRing(["k"]),
        lookup=lambda t, g: None)
    assert len(calls) == 1
    for it in items:
        row = out[item_key(it)]
        assert row["label"] == "Sports & Leisure"
        assert row["topic_path"] == "llm"
