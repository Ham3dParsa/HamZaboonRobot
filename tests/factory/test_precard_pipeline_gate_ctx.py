"""Row-surfacing gate_ctx (locked contract R1-R6): honest signals only.

Hermetic, synthetic fixtures, zero model calls, zero network. Covers:

- R1: gate_ctx built at the pipeline enrich call sites from genuinely
  available data only (item lemma, sub gloss/sense_id, picked rank
  resolvable from the stored anchor_rank candidates). Never
  synthesized jaccard/votes/quality fires; missing key = absent.
- R2: rows carry gate keys on the primary AND extras paths.
- R3: enrich stage counters aggregate verdicts/fires/would-fires.
- R4: legacy enrich states without gate keys are never re-enriched
  and keep their sparse row shape.
- R5: SignalQuality stays annotation-only (verdict LINK preserved).

factory.precard.enrich / factory.linking.gates are NOT modified here
(F3 lock); the pipeline only passes honestly-available ctx through.
"""

import json

from factory.linking import gates
from factory.precard import enrich as real_enrich
from factory.precard import pipeline


def _idx():
    def rows(glosses, ipa, lemma):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": [{"text": (
                                           "I saw %s in the morning "
                                           "light" % lemma)}]}
                                      for g in glosses]}}]

    index = {"alpha": rows(["first alpha gloss", "second alpha gloss"],
                           "/aelfa/", "alpha"),
             "beta": rows(["only beta gloss"], "/beeta/", "beta")}

    def read_entry(row):
        return row["entry"]

    return index, read_entry


_ALPHA_ANCHOR = {
    "candidates": [
        {"sense_id": "alpha#0", "gloss": "first alpha gloss"},
        {"sense_id": "alpha#1", "gloss": "second alpha gloss"},
    ],
    "top": {"sense_id": "alpha#0", "gloss": "first alpha gloss"},
}
_BETA_ANCHOR = {
    "candidates": [{"sense_id": "beta#0", "gloss": "only beta gloss"}],
    "top": {"sense_id": "beta#0", "gloss": "only beta gloss"},
}
_ALPHA_S2 = {
    "sense_id": "alpha#0", "gloss": "first alpha gloss", "model": "test",
    "picks": [{"sense_id": "alpha#0", "gloss": "first alpha gloss"},
              {"sense_id": "alpha#1", "gloss": "second alpha gloss"}],
}
_BETA_S2 = {"sense_id": "beta#0", "gloss": "only beta gloss",
            "model": "test"}
# Pre-gate-ctx legacy payload: complete per the resume condition
# (pre_card_id + sense_cefr_method + example_fallback, method not
# pool-fallback, single-pick s2 so no fan-out re-enrich) but with NO
# gate keys whatsoever.
_BETA_LEGACY_S5 = {
    "sense_id": "beta#0", "en_def": "only beta gloss",
    "circular_def": False, "ipa": "/beeta/", "ipa_src": "dataset",
    "dataset_examples": [], "example_fallback": "lemma",
    "example_synthetic_needed": False, "abbrev_expansion": "",
    "pos": ["noun"], "pos_src": "dataset", "enrich_path": "partial",
    "sense_cefr": "", "sense_cefr_method": "unmapped",
    "lexical_type": "word", "register": "neutral",
    "pre_card_id": "0123456789abcdef",
}

_HONEST_KEYS = {"lemma", "winner_gloss", "rank_index"}


# --- R1: _build_gate_ctx honesty ---

def test_gate_ctx_honest_rank_resolution():
    item = {"kind": "word", "text": "alpha"}
    primary = pipeline._build_gate_ctx(
        item, {"sense_id": "alpha#0", "gloss": "first alpha gloss"},
        _ALPHA_ANCHOR)
    assert primary == {"lemma": "alpha",
                       "winner_gloss": "first alpha gloss",
                       "rank_index": 0}
    extra = pipeline._build_gate_ctx(
        item, {"sense_id": "alpha#1", "gloss": "second alpha gloss"},
        _ALPHA_ANCHOR)
    assert extra["rank_index"] == 1
    assert extra["winner_gloss"] == "second alpha gloss"
    assert set(primary) <= _HONEST_KEYS


def test_gate_ctx_unknown_sense_omits_rank():
    ctx = pipeline._build_gate_ctx(
        {"kind": "word", "text": "alpha"},
        {"sense_id": "alpha#9", "gloss": "ghost gloss"},
        _ALPHA_ANCHOR)
    assert "rank_index" not in ctx
    assert ctx["lemma"] == "alpha"


def test_gate_ctx_sparse_and_hostile_never_raise():
    assert pipeline._build_gate_ctx({}, {}, {}) == {}
    assert pipeline._build_gate_ctx(None, None, None) == {}
    assert pipeline._build_gate_ctx(
        {"text": "  "}, {"sense_id": [], "gloss": None}, None) == {}
    assert pipeline._build_gate_ctx(
        {"text": "alpha"}, "not-a-dict", ["not-a-dict"])["lemma"] == "alpha"


def test_gate_ctx_never_synthesizes_signals():
    ctx = pipeline._build_gate_ctx(
        {"kind": "word", "text": "alpha"},
        {"sense_id": "alpha#0", "gloss": "first alpha gloss"},
        _ALPHA_ANCHOR)
    for banned in ("winner_jaccard", "winner_fires", "wordnet_evidence",
                   "votes_for", "votes_total", "failed",
                   "rank1_fires", "rank2_fires"):
        assert banned not in ctx


# --- R1/R4: sparse ctx fails open through the real enrich seam ---

def test_sparse_ctx_quiet_link_through_real_enrich():
    index, read_entry = _idx()
    item = {"kind": "word", "text": "alpha", "pool_level": "A1"}
    for ctx in ({}, None):
        out = real_enrich.enrich_item(
            item, {"sense_id": "alpha#0", "gloss": "first alpha gloss"},
            index, read_entry, {}, gate_ctx=ctx)
        assert out["gate_verdict"] == gates.LINK
        assert out["gate_fires"] == []
        assert out["signal_quality_would_fire"] is False
        # Card content untouched by the annotation seam.
        assert out["sense_id"] == "alpha#0"
        assert out["en_def"] == "first alpha gloss"


# --- R2/R3/R4: --only enrich run with seeded progress ---

def _seed(progress_dir, name, done):
    path = progress_dir / name
    path.write_text(json.dumps({"done": done, "failed": [],
                                "backoffs": []}),
                    encoding="utf-8")


def _run_enrich_only(tmp_path, monkeypatch, calls):
    from factory.precard import pipeline as pipe

    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(
        [{"kind": "word", "text": "alpha", "pool_level": "A1"},
         {"kind": "word", "text": "beta", "pool_level": "A2"}]),
        encoding="utf-8")
    prog = tmp_path / "prog"
    prog.mkdir()
    _seed(prog, "anchor.json",
          {"w:alpha": _ALPHA_ANCHOR, "w:beta": _BETA_ANCHOR})
    _seed(prog, "sense-judge.json",
          {"w:alpha": _ALPHA_S2, "w:beta": _BETA_S2})
    _seed(prog, "enrich.json", {"w:beta": dict(_BETA_LEGACY_S5)})
    out = str(tmp_path / "precard.jsonl")
    index, read_entry = _idx()

    real = pipe.enrich_item

    def recording(*args, **kwargs):
        pick = kwargs.get("judge_pick")
        if pick is None and len(args) >= 2:
            pick = args[1]
        calls.append({"sense_id": (pick or {}).get("sense_id"),
                      "gate_ctx": kwargs.get("gate_ctx")})
        return real(*args, **kwargs)

    monkeypatch.setattr(pipe, "enrich_item", recording)
    kwargs = dict(
        _judge_transport=None, _topic_transport=None,
        _assign_transport=None, _inflect_transport=None,
        _sleep_fn=lambda s: None,
        _index=index, _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0, _awl_set=set(), _type_map={},
        _type_log_available=False)
    rc = pipe.main(["--sample", str(sample), "--out", out,
                    "--progress-dir", str(prog),
                    "--only", "enrich", "--json-log"], **kwargs)
    assert rc == 0
    return out, prog


def test_gate_ctx_reaches_enrich_at_both_call_sites(tmp_path, monkeypatch):
    calls = []
    _run_enrich_only(tmp_path, monkeypatch, calls)
    by_sid = {c["sense_id"]: c["gate_ctx"] for c in calls}
    # Primary + fanned-out extra enriched; beta resume-skipped.
    assert sorted(by_sid) == ["alpha#0", "alpha#1"]
    assert by_sid["alpha#0"] == {
        "lemma": "alpha", "winner_gloss": "first alpha gloss",
        "rank_index": 0}
    assert by_sid["alpha#1"] == {
        "lemma": "alpha", "winner_gloss": "second alpha gloss",
        "rank_index": 1}
    for ctx in by_sid.values():
        assert set(ctx) <= _HONEST_KEYS


def test_no_reenrich_for_legacy_state_without_gate_keys(
        tmp_path, monkeypatch):
    calls = []
    _, prog = _run_enrich_only(tmp_path, monkeypatch, calls)
    assert all(c["sense_id"] != "beta#0" for c in calls)
    saved = json.loads((prog / "enrich.json").read_text(encoding="utf-8"))
    # R4: the legacy entry is preserved verbatim — no gate backfill.
    assert saved["done"]["w:beta"] == _BETA_LEGACY_S5
    assert "gate_verdict" not in saved["done"]["w:beta"]


def test_rows_carry_gate_keys_primary_and_extras(tmp_path, monkeypatch):
    calls = []
    out, _ = _run_enrich_only(tmp_path, monkeypatch, calls)
    with open(out, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    assert len(rows) == 3
    by_sid = {r["sense_id"]: r for r in rows}
    assert sorted(by_sid) == ["alpha#0", "alpha#1", "beta#0"]
    for sid in ("alpha#0", "alpha#1"):
        row = by_sid[sid]
        assert row["gate_verdict"] == gates.LINK
        assert row["gate_fires"] == []
        assert isinstance(row["gate_reasons"], dict)
        assert row["signal_quality_would_fire"] is False
        assert "signal_quality_reason" in row
    # Legacy row: quiet LINK defaults, sparse shape kept (no reason).
    legacy = by_sid["beta#0"]
    assert legacy["gate_verdict"] == gates.LINK
    assert legacy["gate_fires"] == []
    assert legacy["gate_reasons"] == {}
    assert legacy["signal_quality_would_fire"] is False
    assert "signal_quality_reason" not in legacy
    # Card content unchanged by the annotation seam.
    assert by_sid["alpha#0"]["en_def"] == "first alpha gloss"
    assert by_sid["alpha#1"]["en_def"] == "second alpha gloss"
    assert by_sid["beta#0"]["en_def"] == "only beta gloss"


def test_stage_counters_aggregate_in_summary_and_json_log(
        tmp_path, monkeypatch, capsys):
    calls = []
    out, _ = _run_enrich_only(tmp_path, monkeypatch, calls)
    shown = capsys.readouterr().out
    assert "gates LINK=3" in shown
    assert "SQ-would-fire=0" in shown
    events_path = tmp_path / "run_events.jsonl"
    stage_ends = [
        json.loads(line) for line in
        events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()]
    enrich_end = [e for e in stage_ends
                  if e.get("event") == "stage_end"
                  and e.get("stage") == "enrich"]
    assert len(enrich_end) == 1
    assert enrich_end[0]["gate_counts"] == {
        "verdicts": {"LINK": 3}, "fires": {},
        "signal_quality_would_fire": 0}


# --- R3 unit: counter aggregation incl. extras + hostile ---

def test_count_enrich_gates_tallies_verdicts_fires_extras():
    done = {
        "w:a": {"gate_verdict": "LINK", "gate_fires": [],
                "signal_quality_would_fire": False},
        "w:b": {"gate_verdict": "ESCALATE:HUMAN_QUEUE",
                "gate_fires": ["SplitVoteVeto"],
                "signal_quality_would_fire": True,
                "extra": [
                    {"gate_verdict": "LINK", "gate_fires": [],
                     "signal_quality_would_fire": True},
                    "hostile",
                ]},
        "w:c": "hostile",
    }
    counts = pipeline._count_enrich_gates(done)
    assert counts["verdicts"] == {"LINK": 2, "ESCALATE:HUMAN_QUEUE": 1}
    assert counts["fires"] == {"SplitVoteVeto": 1}
    assert counts["signal_quality_would_fire"] == 2
    assert pipeline._count_enrich_gates(None) == {
        "verdicts": {}, "fires": {}, "signal_quality_would_fire": 0}


def test_format_gate_counts_hostile_renders_zeros():
    assert "SQ-would-fire=0" in pipeline._format_gate_counts(None)
    assert "SQ-would-fire=0" in pipeline._format_gate_counts("hostile")
    text = pipeline._format_gate_counts(
        {"verdicts": {"LINK": 2}, "fires": {"SplitVoteVeto": 1},
         "signal_quality_would_fire": 1})
    assert "LINK=2" in text and "SplitVoteVeto=1" in text
    assert "SQ-would-fire=1" in text


# --- R5: SignalQuality surfacing never routes ---

def test_signal_quality_would_fire_never_blocks_row():
    row = pipeline._build_precard_row(
        {"kind": "word", "text": "alpha"}, "w:alpha",
        {"sense_id": "alpha#0"},
        {"sense_id": "alpha#0", "en_def": "first alpha gloss",
         "gate_verdict": gates.LINK, "gate_fires": [],
         "gate_reasons": {"SignalQualityVeto": "rank2-beats-rank1"},
         "signal_quality_would_fire": True,
         "signal_quality_reason": "rank2-higher-quality-beats-rank1"},
        {}, [{"label": "Other / Abstract", "weight": 1.0}],
        {}, {}, {}, {}, {}, 0, 1)
    assert row["gate_verdict"] == gates.LINK
    assert row["gate_fires"] == []
    assert row["signal_quality_would_fire"] is True
    assert row["signal_quality_reason"] == (
        "rank2-higher-quality-beats-rank1")
    assert row["en_def"] == "first alpha gloss"
