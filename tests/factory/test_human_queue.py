"""Human escalation queue (HQ tickets): module + pipeline seam.

Hermetic, synthetic fixtures, zero model calls, zero network. Covers:

- Schema/fields + queue_id format + created_at stamping (module).
- Nullable policy: identity required, everything else nullable/empty-ok.
- Append-only multi-row + sink-path injection (tmp_path).
- Reader: missing file -> [], same queue_id keeps latest created_at.
- I/O-failure path: module raises HumanQueueError; the pipeline seam
  warns and the run stays green (HQ7).
- No interference: an enrich run with veto rows writes the sink AND
  keeps precard rows byte-identical in card fields (run green).
"""

import json

import pytest

from factory.linking import human_queue as hq
from factory.precard import pipeline


def _record(**over):
    base = {"lemma": "alpha", "pos": "noun", "sense_id": "alpha#0",
            "escalation_reason": "SplitVoteVeto"}
    base.update(over)
    return base


# --- module: schema / queue_id / stamping ---

def test_enqueue_schema_fields_and_pending(tmp_path):
    sink = tmp_path / "q.jsonl"
    queue_id = hq.enqueue_escalation(_record(), str(sink))
    assert queue_id == "esc-alpha-noun-alpha#0"
    line = json.loads(sink.read_text(encoding="utf-8").strip())
    assert set(line) == {"queue_id", "created_at", "escalation_reason",
                         "source_entry", "candidates", "signals_trace",
                         "arbiter_trace", "human_resolution"}
    assert line["queue_id"] == queue_id
    assert line["escalation_reason"] == "SplitVoteVeto"
    assert line["human_resolution"] == "PENDING"
    assert line["created_at"]  # stamped ISO8601-UTC
    from datetime import datetime
    assert datetime.fromisoformat(line["created_at"]).tzinfo is not None


def test_enqueue_keeps_explicit_created_at(tmp_path):
    sink = tmp_path / "q.jsonl"
    rec = _record(created_at="2026-09-20T00:00:00+00:00")
    assert hq.enqueue_escalation(rec, str(sink)) == "esc-alpha-noun-alpha#0"
    line = json.loads(sink.read_text(encoding="utf-8").strip())
    assert line["created_at"] == "2026-09-20T00:00:00+00:00"


def test_queue_id_sanitizes_separators_and_whitespace():
    assert hq.build_queue_id("a/b", "n n", "x#0") == "esc-a-b-n-n-x#0"
    assert hq.build_queue_id("a\\b", "n\tn", "x#0") == "esc-a-b-n-n-x#0"
    with pytest.raises(hq.HumanQueueError):
        hq.build_queue_id("  ", "noun", "x#0")
    with pytest.raises(hq.HumanQueueError):
        hq.build_queue_id("a", "", "x#0")


def test_enqueue_validates_identity(tmp_path):
    sink = tmp_path / "q.jsonl"
    for bad in ({}, "not-a-dict",
                _record(lemma=""), _record(pos=""),
                _record(sense_id=""), _record(escalation_reason="  ")):
        with pytest.raises(hq.HumanQueueError):
            hq.enqueue_escalation(bad, str(sink))
    assert not sink.exists()  # failed validation writes nothing


def test_nullable_policy_minimal_record(tmp_path):
    sink = tmp_path / "q.jsonl"
    hq.enqueue_escalation(_record(), str(sink))
    line = json.loads(sink.read_text(encoding="utf-8").strip())
    assert line["candidates"] is None
    assert line["signals_trace"] is None
    assert line["arbiter_trace"] is None
    assert line["source_entry"]["sense_id"] == "alpha#0"


def test_nullable_policy_empty_lists_preserved(tmp_path):
    sink = tmp_path / "q.jsonl"
    hq.enqueue_escalation(_record(candidates=[], signals_trace=[],
                                  arbiter_trace=[]), str(sink))
    line = json.loads(sink.read_text(encoding="utf-8").strip())
    assert line["candidates"] == []
    assert line["signals_trace"] == []
    assert line["arbiter_trace"] == []


def test_append_only_multi_row(tmp_path):
    sink = tmp_path / "q.jsonl"
    hq.enqueue_escalation(_record(), str(sink))
    hq.enqueue_escalation(_record(lemma="beta", sense_id="beta#0",
                                  escalation_reason="LowRankZeroOverlapVeto"),
                          str(sink))
    lines = [line for line in sink.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["queue_id"] == "esc-alpha-noun-alpha#0"
    assert json.loads(lines[1])["queue_id"] == "esc-beta-noun-beta#0"


def test_sink_parent_dirs_created(tmp_path):
    sink = tmp_path / "deep" / "nested" / "q.jsonl"
    assert hq.enqueue_escalation(_record(), str(sink))
    assert sink.exists()


def test_enqueue_io_failure_raises_module_error(tmp_path):
    with pytest.raises(hq.HumanQueueError):
        hq.enqueue_escalation(_record(), str(tmp_path))  # a directory


# --- module: reader ---

def test_reader_missing_file_is_empty(tmp_path):
    assert hq.load_queue_deduped(str(tmp_path / "nope.jsonl")) == []


def test_reader_dedupe_keeps_latest(tmp_path):
    sink = tmp_path / "q.jsonl"
    hq.enqueue_escalation(_record(created_at="2026-01-01T00:00:00+00:00"),
                          str(sink))
    hq.enqueue_escalation(_record(created_at="2026-03-01T00:00:00+00:00",
                                  escalation_reason="EvidenceGlossMismatchVeto"),
                          str(sink))
    rows = hq.load_queue_deduped(str(sink))
    assert len(rows) == 1
    assert rows[0]["created_at"] == "2026-03-01T00:00:00+00:00"
    assert rows[0]["escalation_reason"] == "EvidenceGlossMismatchVeto"


def test_reader_skips_blank_and_corrupt(tmp_path):
    sink = tmp_path / "q.jsonl"
    sink.write_text("\nnot-json\n{\"no_queue_id\": 1}\n", encoding="utf-8")
    hq.enqueue_escalation(_record(), str(sink))
    rows = hq.load_queue_deduped(str(sink))
    assert [r["queue_id"] for r in rows] == ["esc-alpha-noun-alpha#0"]


# --- seam helpers: pure ---

def test_default_sink_resolved_against_out_root(tmp_path):
    out = tmp_path / "run" / "precard.jsonl"
    assert pipeline._default_human_queue_sink(str(out)) == (
        tmp_path / "run" / "reports" / "linker"
        / "human_escalation_queue.jsonl")


def test_record_only_for_veto_fires():
    item = {"kind": "word", "text": "alpha"}
    quiet = {"sense_id": "alpha#0", "pos": ["noun"], "gate_fires": [],
             "signal_quality_would_fire": True}
    assert pipeline._human_queue_record(item, quiet) is None
    assert pipeline._human_queue_record(item, {}) is None
    assert pipeline._human_queue_record(item, "hostile") is None
    veto = {"sense_id": "alpha#0", "pos": ["noun"],
            "en_def": "first alpha gloss",
            "gate_verdict": "ESCALATE:HUMAN_QUEUE",
            "gate_fires": ["SplitVoteVeto"],
            "gate_reasons": {"SplitVoteVeto": "non-unanimous:split"}}
    rec = pipeline._human_queue_record(item, veto)
    assert rec["escalation_reason"] == "SplitVoteVeto"
    assert rec["candidates"] == []  # online: no jaccard/votes
    assert rec["arbiter_trace"] is None
    assert rec["source_entry"]["gloss"] == "first alpha gloss"
    # Missing identity never raises, never queues.
    assert pipeline._human_queue_record(
        {}, {"sense_id": "x#0", "gate_fires": ["SplitVoteVeto"]}) is None


def test_flush_empty_writes_nothing(tmp_path):
    assert pipeline._flush_human_queue([], str(tmp_path / "q.jsonl")) == 0
    assert not (tmp_path / "q.jsonl").exists()


def test_flush_failure_warns_and_continues(tmp_path):
    warns = []
    pending = [({"kind": "word", "text": "alpha"},
                {"sense_id": "alpha#0", "pos": ["noun"],
                 "gate_fires": ["SplitVoteVeto"]})]
    n = pipeline._flush_human_queue(pending, str(tmp_path),  # a directory
                                    warn_fn=warns.append)
    assert n == 0
    assert warns and "human queue" in warns[0].lower()


# --- seam: pipeline enrich run ---

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


def _seed(progress_dir, name, done):
    path = progress_dir / name
    path.write_text(json.dumps({"done": done, "failed": [],
                                "backoffs": []}),
                    encoding="utf-8")


def _run_enrich_only(tmp_path, monkeypatch, veto=False, extra_args=()):
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
    _seed(prog, "enrich.json", {})
    out = str(tmp_path / "precard.jsonl")
    index, read_entry = _idx()

    real = pipe.enrich_item

    def recording(*args, **kwargs):
        payload = real(*args, **kwargs)
        if veto:
            item = args[0] if args else {}
            # Only alpha veto-fires; beta stays quiet LINK (never queued).
            if isinstance(item, dict) and item.get("text") == "alpha":
                payload = dict(payload)
                payload["gate_verdict"] = "ESCALATE:HUMAN_QUEUE"
                payload["gate_fires"] = ["SplitVoteVeto"]
                payload["gate_reasons"] = {"SplitVoteVeto": "test-split"}
        return payload

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
                    "--only", "enrich"] + list(extra_args), **kwargs)
    assert rc == 0
    return out


def test_enrich_run_with_veto_rows_writes_sink_run_green(
        tmp_path, monkeypatch):
    out = _run_enrich_only(tmp_path, monkeypatch, veto=True)
    sink = (tmp_path / "reports" / "linker"
            / "human_escalation_queue.jsonl")
    assert sink.exists()  # default sink against the run output root
    rows = [json.loads(line) for line in
            sink.read_text(encoding="utf-8").splitlines() if line.strip()]
    # alpha primary + fanned-out extra; beta quiet LINK never enqueues.
    assert len(rows) == 2
    assert {r["queue_id"] for r in rows} == {
        "esc-alpha-noun-alpha#0", "esc-alpha-noun-alpha#1"}
    for row in rows:
        assert row["escalation_reason"] == "SplitVoteVeto"
        assert row["human_resolution"] == "PENDING"
        assert set(row) == {"queue_id", "created_at", "escalation_reason",
                            "source_entry", "candidates", "signals_trace",
                            "arbiter_trace", "human_resolution"}
    # No interference: card fields on the precard rows are untouched.
    with open(out, encoding="utf-8") as handle:
        precards = [json.loads(line) for line in handle if line.strip()]
    by_sid = {r["sense_id"]: r for r in precards}
    assert by_sid["alpha#0"]["en_def"] == "first alpha gloss"
    assert by_sid["alpha#1"]["en_def"] == "second alpha gloss"
    assert by_sid["beta#0"]["en_def"] == "only beta gloss"


def test_enrich_run_without_veto_writes_no_sink(tmp_path, monkeypatch):
    _run_enrich_only(tmp_path, monkeypatch, veto=False)
    assert not (tmp_path / "reports" / "linker"
                / "human_escalation_queue.jsonl").exists()


def test_enrich_run_queue_io_failure_stays_green(
        tmp_path, monkeypatch, capsys):
    _run_enrich_only(tmp_path, monkeypatch, veto=True,
                     extra_args=("--human-queue-path", str(tmp_path)))
    err = capsys.readouterr().err
    assert "human queue" in err.lower()  # HQ7 warning, run still rc 0


def test_explicit_sink_path_flag(tmp_path, monkeypatch):
    custom = tmp_path / "custom" / "hq.jsonl"
    _run_enrich_only(tmp_path, monkeypatch, veto=True,
                     extra_args=("--human-queue-path", str(custom)))
    rows = hq.load_queue_deduped(str(custom))
    assert len(rows) == 2
