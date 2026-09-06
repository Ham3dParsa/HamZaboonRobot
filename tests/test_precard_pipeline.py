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


def test_429_backoff_then_continue(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    sample = write_sample(tmp_path, ITEMS[:1])
    out, prog, sleeps = (str(tmp_path / "precard.jsonl"),
                         str(tmp_path / "prog"), [])

    def always_429(api_key, model, user_text):
        raise _http_429()

    rc = precard_main(
        ["--sample", sample, "--out", out, "--progress-dir", prog],
        _judge_transport=always_429, _topic_transport=fake_topics,
        _assign_transport=None, _sleep_fn=sleeps.append,
        _index=make_index(), _read_entry=read_entry, _tatoeba={})
    assert rc == 0
    # 60s then 300s backoff, then batch sleep 2.5s (S2), then S3/S4 sleeps.
    assert sleeps[:2] == [60.0, 300.0]
    state = json.loads(open(prog + "/s2.json", encoding="utf-8").read())
    assert any(e["outcome"] == "exhausted-continue-next"
               for e in state["backoffs"])
    rows = load_out(out)
    assert len(rows) == 1
    assert rows[0]["sense_id"] == "apple#0"  # fail-closed to S1 top pick
    assert rows[0]["stage_calls"]["s2"] == "s1-fallback"
    assert "w:apple" in state["failed"]


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
