"""Phase-05 telemetry + logging (R10/R11), hermetic.

run_id (start-ts + pid) joins all four sinks (provider_map.json,
run.log header, telemetry_records.jsonl, telemetry_summary.json);
terminal records carry real perf_counter latency, real ring.idx,
provider, and model_actual vs model_requested; Google None-usage is
flagged cost-unknown (never a silent zero); attempt rows stay behind
--tele-attempts (default off); stdout is human-only (--quiet) with
warnings on stderr and machine files (--json-log JSONL).
"""

import json
import re
import time
import urllib.error

from factory.core import telemetry as core_tele
from factory.precard import transport as precard_transport


def _idx():
    def rows(glosses, ipa):
        return [{"pos": "noun",
                 "entry": {"pos": "noun", "sounds": [{"ipa": ipa}],
                           "senses": [{"glosses": [g], "tags": [],
                                       "examples": []}
                                      for g in glosses]}}]
    index = {"apple": rows(["a round fruit", "a tech company"], "/aɪpa/")}

    def read_entry(row):
        return row["entry"]

    return index, read_entry


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
    keys, cur = [], None
    for line in user_text.splitlines():
        hit = re.match(r"^KEY (\S+)", line)
        if hit:
            cur = hit.group(1)
            keys.append(cur)
    return json.dumps({"results": [
        {"key": k, "keep": True, "reason": "test keep"} for k in keys]})


def _hermetic_kwargs():
    index, read_entry = _idx()
    return dict(
        _judge_transport=_fake_judge, _topic_transport=_fake_topics,
        _assign_transport=None, _inflect_transport=_fake_inflect,
        _sleep_fn=lambda s: None,
        _index=index, _read_entry=read_entry, _tatoeba={},
        _zipf_fn=lambda t: 5.0, _awl_set=set(), _type_map={},
        _type_log_available=False)


def _run_apple(tmp_path, *extra_argv):
    from factory.precard import pipeline as pipe
    items = [{"kind": "word", "text": "apple", "pos": "noun",
              "pool_level": "A1"}]
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(items), encoding="utf-8")
    out = str(tmp_path / "precard.jsonl")
    prog = str(tmp_path / "prog")
    rc = pipe.main(["--sample", str(sample), "--out", out,
                    "--progress-dir", prog, *extra_argv],
                   **_hermetic_kwargs())
    assert rc == 0
    return out


def _out_dir(out):
    import pathlib
    return pathlib.Path(out).parent


def test_run_id_joins_all_four_sinks(tmp_path):
    """R10: provider_map, run.log header, every record, and the summary
    share one run_id (start-ts + pid)."""
    out = _run_apple(tmp_path)
    parent = _out_dir(out)
    prov = json.loads(
        (parent / "provider_map.json").read_text(encoding="utf-8"))
    run_id = prov["run_id"]
    assert run_id and "-pid" in run_id
    # Legs stay top-level (existing readers keep working).
    assert prov["sense_judge"]["provider"] == "zen"
    head = (parent / "run.log").read_text(encoding="utf-8").splitlines()
    assert head and head[0].startswith("run %s started=" % run_id)
    recs = [json.loads(line) for line in
            (parent / "telemetry_records.jsonl").read_text(
                encoding="utf-8").splitlines() if line.strip()]
    assert recs  # judge + vectors terminal rows at minimum
    assert {r["run_id"] for r in recs} == {run_id}
    summary = json.loads(
        (parent / "telemetry_summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == run_id


def _judge_anchor():
    batch = [{"kind": "word", "text": "apple", "pool_level": "A1"}]
    anchor = {"w:apple": {"candidates": [
        {"sense_id": "apple#0", "gloss": "a round fruit"}]}}
    return batch, anchor


def _http_429():
    return urllib.error.HTTPError(
        "http://x", 429, "too many", {}, None)


def test_terminal_record_real_latency_and_key(tmp_path):
    """R10: terminal rows carry the measured latency and the real
    ring.idx (a 429 rotates k1 -> k2, so key_idx == 1, latency > 0)."""
    from factory.precard.judge import judge_batch
    from factory.precard.transport import KeyRing
    calls = []

    def fake(api_key, model, text):
        calls.append(api_key)
        if len(calls) == 1:
            raise _http_429()
        time.sleep(0.005)
        return (json.dumps({"results": [
            {"key": "w:apple", "picks": ["apple#0"]}]}),
            {"input_tokens": 5, "output_tokens": 7})

    batch, anchor = _judge_anchor()
    store = []
    out = judge_batch(batch, anchor, "k1", fake, lambda s: None, {},
                      telemetry=store, tele_stage="sense_judge",
                      tele_batch=1, ring=KeyRing(["k1", "k2"]),
                      models=["zen-name"], provider="zen",
                      tele_run_id="r1", tele_attempts=False)
    assert out["w:apple"]["sense_id"] == "apple#0"
    assert calls == ["k1", "k2"]
    assert len(store) == 1  # terminal only: no attempt rows by default
    rec = store[0]
    assert rec["kind"] == "terminal"
    assert rec["latency_s"] > 0
    assert rec["key_idx"] == 1
    assert rec["provider"] == "zen"
    assert rec["model"] == "zen-name"
    assert rec["model_actual"] == "zen-name"
    assert (rec["prompt_tokens"], rec["completion_tokens"]) == (5, 7)
    assert rec["cost"] is None
    assert rec["run_id"] == "r1"


def test_model_actual_vs_requested_on_remap_leg():
    """R10: the remap-name lie is gone — requested vs really-hit."""
    from factory.precard.judge import judge_batch
    from factory.precard.transport import KeyRing

    def fake(api_key, model, text):
        return (json.dumps({"results": [
            {"key": "w:apple", "picks": ["apple#0"]}]}), None)

    batch, anchor = _judge_anchor()
    store = []
    judge_batch(batch, anchor, "k", fake, lambda s: None, {},
                telemetry=store, tele_stage="sense_judge",
                tele_batch=1, ring=KeyRing(["k"]),
                models=["zen-name"], provider="avalai",
                tele_run_id="r1", tele_model_actual="glm-5.3-flash")
    assert len(store) == 1
    rec = store[0]
    assert rec["model"] == "zen-name"
    assert rec["model_actual"] == "glm-5.3-flash"
    # Google-style None usage on a paid leg: unknown, never silent zero.
    assert rec["cost"] == "unknown"


def test_google_none_usage_cost_unknown_never_zero():
    """R10: unknown usage flags cost-unknown in the summary instead of
    summing as a silent zero."""
    store = core_tele.new_store()
    core_tele.record_call(
        store, stage="sense_judge", batch_id=1, key_idx=0,
        model="zen-name", model_actual="gemini-3.5-flash-lite",
        provider="google", latency_s=0.4, outcome="ok",
        run_id="r1",
        cost=core_tele.resolve_cost(made_call=True))
    assert store[0]["cost"] == "unknown"
    summary = core_tele.summarize(store)
    bucket = summary["by_stage"]["sense_judge"]
    assert bucket["prompt_tokens"] == 0 and bucket["completion_tokens"] == 0
    assert bucket["unknown"] == 1  # the zero is flagged, never silent
    assert summary["cost_unknown"] == 1


def test_attempt_rows_behind_flag_default_off():
    """R10: per-try attempt rows only with tele_attempts=True."""
    from factory.precard.judge import judge_batch
    from factory.precard.transport import KeyRing

    def fake(api_key, model, text):
        if not fake.seen:
            fake.seen.append(1)
            raise _http_429()
        return (json.dumps({"results": [
            {"key": "w:apple", "picks": ["apple#0"]}]}), None)
    fake.seen = []

    batch, anchor = _judge_anchor()
    plain = []
    judge_batch(batch, anchor, "k1", fake, lambda s: None, {},
                telemetry=plain, tele_stage="sense_judge",
                tele_batch=1, ring=KeyRing(["k1", "k2"]),
                models=["m"], provider="zen", tele_run_id="r1")
    assert plain and all(r["kind"] == "terminal" for r in plain)

    fake.seen = []
    flagged = []
    judge_batch(batch, anchor, "k1", fake, lambda s: None, {},
                telemetry=flagged, tele_stage="sense_judge",
                tele_batch=1, ring=KeyRing(["k1", "k2"]),
                models=["m"], provider="zen", tele_run_id="r1",
                tele_attempts=True)
    attempts = [r for r in flagged if r["kind"] == "attempt"]
    assert len(attempts) >= 2  # rotated + settled tries
    assert {r["run_id"] for r in attempts} == {"r1"}
    assert {r["try_outcome"] for r in attempts} >= {"rotated", "settled"}


def test_quiet_suppresses_stdout_human_progress(tmp_path, capsys):
    """R11: --quiet leaves stdout empty; files still written."""
    out = _run_apple(tmp_path, "--quiet")
    captured = capsys.readouterr()
    assert captured.out == ""
    rows = [line for line in open(out, encoding="utf-8")
            if line.strip()]
    assert len(rows) == 1
    assert (_out_dir(out) / "run.log").exists()


def test_json_log_events_run_id_joined(tmp_path):
    """R11: --json-log writes one JSON object per event, all run_id."""
    out = _run_apple(tmp_path, "--json-log")
    parent = _out_dir(out)
    run_id = json.loads(
        (parent / "provider_map.json").read_text(encoding="utf-8"))["run_id"]
    lines = [line for line in
             (parent / "run_events.jsonl").read_text(
                 encoding="utf-8").splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]
    assert events
    assert {e["run_id"] for e in events} == {run_id}
    kinds = {e["event"] for e in events}
    assert {"run_start", "stage_start", "batch", "stage_end",
            "run_done"} <= kinds


def test_quota_stop_emits_abort_event_and_closes_json_log(
        tmp_path, monkeypatch):
    """Reviewer must-fix: a quota STOP records an abort event and the
    json-log stream is closed by the finally (readable, complete)."""
    import pytest
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")
    from factory.precard import pipeline as pipe
    items = [{"kind": "word", "text": "apple", "pos": "noun",
              "pool_level": "A1"}]
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(items), encoding="utf-8")
    out = str(tmp_path / "precard.jsonl")
    prog = str(tmp_path / "prog")

    def always_429(api_key, model, user_text):
        raise _http_429()

    with pytest.raises(SystemExit):
        pipe.main(["--sample", str(sample), "--out", out,
                   "--progress-dir", prog, "--json-log"],
                  **{**_hermetic_kwargs(),
                     "_judge_transport": always_429})
    parent = _out_dir(out)
    events = [json.loads(line) for line in
              (parent / "run_events.jsonl").read_text(
                  encoding="utf-8").splitlines() if line.strip()]
    aborts = [e for e in events if e["event"] == "abort"]
    assert aborts and aborts[0]["stage"] == "sense_judge"
    assert len({e["run_id"] for e in events}) == 1  # joined, complete


def test_transport_shim_reexports_owner():
    """Route-delete: transport keeps the narrow shim, bodies live in
    core."""
    for name in ("record_call", "summarize", "write_summary",
                 "extract_usage", "now_ts", "OUTCOMES"):
        assert getattr(precard_transport, name) is getattr(core_tele, name)
    import ast
    import pathlib
    tree = ast.parse((pathlib.Path(precard_transport.__file__).read_text(
        encoding="utf-8")))
    defs = {node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)}
    assert "record_call" not in defs
    assert "summarize" not in defs
    assert "write_summary" not in defs
    assert "extract_usage" not in defs


def test_supervisor_leases_append_only(tmp_path, monkeypatch):
    """R10: lease/report append secret-free lines; probes untouched."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                    "..", "tools", "egress"))
    import supervisor as sup
    monkeypatch.setattr(sup, "LEASES_PATH", tmp_path / "leases.jsonl")
    pool = sup.Pool()
    lease = pool.lease("direct")
    assert pool.report(lease["lease_id"], "ok") == {"action": "keep"}
    assert pool.report("nope", "ok") == {"action": "unknown-lease"}
    lines = (tmp_path / "leases.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 2  # unknown-lease reports log nothing
    events = [json.loads(line) for line in lines]
    assert [e["event"] for e in events] == ["lease", "report"]
    assert all(e["ts"] and e["lease"] for e in events)
    blob = "\n".join(lines)
    assert "proxy_url" not in blob and "token" not in blob.lower()
    assert all(len(e["lease"]) <= 8 for e in events)
    # Probe seam owned by the parallel PR: still attached, uncalled here.
    assert sup.TARGETS["zen"]["probe"] is sup.zen_probe
    assert sup.TARGETS["google"]["probe"] is sup.google_probe


def test_run_with_lease_line_gains_server_provider(
        tmp_path, monkeypatch, capsys):
    """R10: the lease line names server + provider, never secrets."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                    "..", "tools", "egress"))
    import run_with_lease as rwl

    def fake_lease(target):
        return {"lease_id": "L1234567890", "mode": "tunnel",
                "proxy_url": "http://127.0.0.1:18888",
                "egress_ip": "9.9.9.9", "server_id": "s1",
                "provider": "zen", "target": target}

    def fake_report(lid, outcome):
        return {"action": "keep"}

    monkeypatch.setattr(rwl.client, "lease", fake_lease)
    monkeypatch.setattr(rwl.client, "report", fake_report)

    class FakeProc:
        def wait(self):
            return 0

    monkeypatch.setattr(rwl.subprocess, "Popen",
                        lambda cmd, env=None: FakeProc())
    assert rwl.main(["zen", "--", "echo", "hi"]) == 0
    out = capsys.readouterr().out
    assert "server=s1" in out and "provider=zen" in out
    assert "proxy_url" not in out and "127.0.0.1:18888" not in out
