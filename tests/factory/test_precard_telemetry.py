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
from factory.precard import provider_transport as precard_transport


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
    # Legs stay top-level (existing readers keep working). All legs
    # are caller-injected here, so no flag resolved a provider (None =
    # caller-owned transport).
    assert prov["sense_judge"]["provider"] is None
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
    from factory.precard.judge import arbiter_batch
    from factory.precard.provider_transport import KeyRing
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
    out = arbiter_batch(batch, anchor, "k1", fake, lambda s: None, {},
                      telemetry=store, tele_stage="sense_judge",
                      tele_batch=1, ring=KeyRing(["k1", "k2"]),
                      models=["req-name"], provider="avalai",
                      tele_run_id="r1", tele_attempts=False)
    assert out["w:apple"]["sense_id"] == "apple#0"
    assert calls == ["k1", "k2"]
    assert len(store) == 1  # terminal only: no attempt rows by default
    rec = store[0]
    assert rec["kind"] == "terminal"
    assert rec["latency_s"] > 0
    assert rec["key_idx"] == 1
    assert rec["provider"] == "avalai"
    assert rec["model"] == "req-name"
    assert rec["model_actual"] == "req-name"
    assert (rec["prompt_tokens"], rec["completion_tokens"]) == (5, 7)
    assert rec["cost"] is None
    assert rec["run_id"] == "r1"


def test_model_actual_vs_requested_on_remap_leg():
    """R10: the remap-name lie is gone — requested vs really-hit."""
    from factory.precard.judge import arbiter_batch
    from factory.precard.provider_transport import KeyRing

    def fake(api_key, model, text):
        return (json.dumps({"results": [
            {"key": "w:apple", "picks": ["apple#0"]}]}), None)

    batch, anchor = _judge_anchor()
    store = []
    arbiter_batch(batch, anchor, "k", fake, lambda s: None, {},
                telemetry=store, tele_stage="sense_judge",
                tele_batch=1, ring=KeyRing(["k"]),
                models=["req-name"], provider="avalai",
                tele_run_id="r1", tele_model_actual="glm-5.3-flash")
    assert len(store) == 1
    rec = store[0]
    assert rec["model"] == "req-name"
    assert rec["model_actual"] == "glm-5.3-flash"
    # Google-style None usage on a paid leg: unknown, never silent zero.
    assert rec["cost"] == "unknown"


def test_google_none_usage_cost_unknown_never_zero():
    """R10: unknown usage flags cost-unknown in the summary instead of
    summing as a silent zero."""
    store = core_tele.new_store()
    core_tele.record_call(
        store, stage="sense_judge", batch_id=1, key_idx=0,
        model="req-name", model_actual="gemini-3.5-flash-lite",
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
    from factory.precard.judge import arbiter_batch
    from factory.precard.provider_transport import KeyRing

    def fake(api_key, model, text):
        if not fake.seen:
            fake.seen.append(1)
            raise _http_429()
        return (json.dumps({"results": [
            {"key": "w:apple", "picks": ["apple#0"]}]}), None)
    fake.seen = []

    batch, anchor = _judge_anchor()
    plain = []
    arbiter_batch(batch, anchor, "k1", fake, lambda s: None, {},
                telemetry=plain, tele_stage="sense_judge",
                tele_batch=1, ring=KeyRing(["k1", "k2"]),
                models=["m"], provider="avalai", tele_run_id="r1")
    assert plain and all(r["kind"] == "terminal" for r in plain)

    fake.seen = []
    flagged = []
    arbiter_batch(batch, anchor, "k1", fake, lambda s: None, {},
                telemetry=flagged, tele_stage="sense_judge",
                tele_batch=1, ring=KeyRing(["k1", "k2"]),
                models=["m"], provider="avalai", tele_run_id="r1",
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


def test_bool_attempt_key_idx_coerced_never_crashes(tmp_path):
    """Reviewer must-fix: a bool key_idx in an attempt row coerces to 0
    instead of tripping record_call's TypeError (diagnostic telemetry
    must never abort the run it measures)."""
    store = core_tele.new_store()
    core_tele.emit_attempt_rows(
        store, stage="sense_judge", batch_id=1, run_id="r1",
        attempts=[{"model": "m", "attempt": 1, "outcome": "settled",
                   "key_idx": True, "latency_s": 0.1}])
    assert store and store[0]["kind"] == "attempt"
    assert store[0]["key_idx"] == 0


def test_preflight_abort_closes_json_log(tmp_path):
    """Reviewer must-fix: pre-flight exits (e.g. corrupt progress) record
    an abort event and close the stream — never dangling."""
    import pytest
    from factory.core.stage_glossary import STAGE_FILES
    from factory.precard import pipeline as pipe
    items = [{"kind": "word", "text": "apple", "pos": "noun",
              "pool_level": "A1"}]
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(items), encoding="utf-8")
    prog = tmp_path / "prog"
    prog.mkdir()
    (prog / STAGE_FILES["s2"]).write_text("not-json{{{",
                                          encoding="utf-8")
    with pytest.raises(SystemExit):
        pipe.main(["--sample", str(sample),
                   "--out", str(tmp_path / "precard.jsonl"),
                   "--progress-dir", str(prog), "--json-log"],
                  **_hermetic_kwargs())
    events = [json.loads(line) for line in
              (tmp_path / "run_events.jsonl").read_text(
                  encoding="utf-8").splitlines() if line.strip()]
    aborts = [e for e in events if e["event"] == "abort"]
    assert aborts and aborts[-1]["stage"] == "preflight"
    assert len({e["run_id"] for e in events}) == 1


def test_label_counters_one_bump_per_entry(tmp_path):
    """Reviewer-noise evidence: every label_batch entry is bumped exactly
    once (cache entries continue past the chunk loop, so no entry
    is ever double-counted; transport=None unlabelled counts as hit)."""
    from factory.precard.topics import label_batch
    from factory.precard.provider_transport import KeyRing
    batch = [{"kind": "word", "text": "t1", "pos": "noun",
              "pool_level": "A1"},
             {"kind": "word", "text": "t2", "pos": "noun",
              "pool_level": "A1"}]
    picks = {"w:t1": {"sense_id": "t1#0", "gloss": "g1"},
             "w:t2": {"sense_id": "t2#0", "gloss": "g2"}}
    counters = {"hit": 0, "miss": 0, "cache": 0}
    out = label_batch(batch, picks, {}, "", None, lambda s: None,
                      {"done": {}, "failed": [], "backoffs": []},
                      str(tmp_path / "cache.json"), {},
                      ring=KeyRing(["k"]), counters=counters)
    assert len(out) == 2
    assert counters == {"hit": 2, "miss": 0, "cache": 0}


def test_summarize_splits_attempts_from_calls():
    """Reviewer must-fix: attempt rows never inflate call accounting —
    buckets/records count terminal rows only, attempts separately."""
    store = core_tele.new_store()
    core_tele.record_call(store, stage="s2", batch_id=1, key_idx=0,
                          model="m", latency_s=0.4, outcome="ok",
                          run_id="r1")
    core_tele.emit_attempt_rows(
        store, stage="s2", batch_id=1, run_id="r1",
        attempts=[{"model": "m", "attempt": 1, "outcome": "rotated",
                   "key_idx": 0, "latency_s": 0.1},
                  {"model": "m", "attempt": 2, "outcome": "settled",
                   "key_idx": 1, "latency_s": 0.2}])
    summary = core_tele.summarize(store)
    assert summary["records"] == 1
    assert summary["attempts"] == 2
    assert summary["by_stage"]["s2"]["calls"] == 1


def test_error_row_stamps_last_attempt_latency():
    """Reviewer must-fix: a RateLimited terminal row carries the last
    measured try latency, not a hardcoded 0.0."""
    import time
    import pytest
    from factory.precard.judge import arbiter_batch
    from factory.precard.provider_transport import KeyRing

    def always_429(api_key, model, text):
        time.sleep(0.002)
        raise _http_429()

    batch, anchor = _judge_anchor()
    store = []
    with pytest.raises(Exception):
        arbiter_batch(batch, anchor, "k1", always_429, lambda s: None, {},
                    telemetry=store, tele_stage="sense_judge",
                    tele_batch=1, ring=KeyRing(["k1", "k2"]),
                    models=["m"], provider="avalai", tele_run_id="r1")
    errors = [r for r in store if r.get("outcome") == "error"]
    assert errors and errors[0]["latency_s"] > 0


def test_stage_selection_abort_closes_json_log(tmp_path):
    """Reviewer must-fix: stage-selection exits route through
    _preflight_exit (abort event + closed stream)."""
    import pytest
    from factory.precard import pipeline as pipe
    items = [{"kind": "word", "text": "apple", "pos": "noun",
              "pool_level": "A1"}]
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(items), encoding="utf-8")
    with pytest.raises(SystemExit):
        pipe.main(["--sample", str(sample),
                   "--out", str(tmp_path / "precard.jsonl"),
                   "--progress-dir", str(tmp_path / "prog"),
                   "--json-log", "--stages", "bogus-stage"],
                  **_hermetic_kwargs())
    events = [json.loads(line) for line in
              (tmp_path / "run_events.jsonl").read_text(
                  encoding="utf-8").splitlines() if line.strip()]
    aborts = [e for e in events if e["event"] == "abort"]
    assert aborts and aborts[-1]["stage"] == "preflight"


def test_last_attempt_latency_helper():
    """Unit pin: last measured try wins; empty/garbage yields 0.0."""
    assert core_tele.last_attempt_latency([]) == 0.0
    assert core_tele.last_attempt_latency(None) == 0.0
    assert core_tele.last_attempt_latency(
        [{"latency_s": 0.1}, {"latency_s": 0.4}]) == 0.4
    assert core_tele.last_attempt_latency([{"latency_s": "bad"}]) == 0.0


def _inflect_items():
    return [{"key": "w:cats", "text": "cats", "gloss": "plural of cat"}]


def test_inflection_fallback_stamps_measured_latency():
    """Reviewer must-fix: a fallback terminal row carries the last
    measured try latency, not 0.0 (calls were attempted)."""
    import time
    from factory.precard.judge import inflection_review

    def garbage(api_key, model, sys_text, user_text):
        time.sleep(0.002)
        return "not json at all {{{"

    store = []
    out = inflection_review(_inflect_items(), garbage, "k", {},
                            telemetry=store, tele_run_id="r1")
    assert out["w:cats"]["model"] == "review-fallback"
    terms = [r for r in store if r.get("kind", "terminal") == "terminal"]
    assert terms and terms[0]["outcome"] == "fallback"
    assert terms[0]["latency_s"] > 0


def test_inflection_auth_row_stamps_measured_latency():
    """Reviewer must-fix: the auth terminal row carries the measured
    attempt latency."""
    import time
    import pytest
    from factory.precard.judge import inflection_review

    def boom_401(api_key, model, sys_text, user_text):
        time.sleep(0.002)
        raise _http_401()

    store = []
    with pytest.raises(Exception):
        inflection_review(_inflect_items(), boom_401, "k", {},
                          telemetry=store, tele_run_id="r1")
    auths = [r for r in store if r.get("outcome") == "auth"]
    assert auths and auths[0]["latency_s"] > 0


def _http_401():
    import urllib.error
    return urllib.error.HTTPError(
        "http://x", 401, "unauthorized", {}, None)


def test_leases_file_startup_tail_cap(tmp_path, monkeypatch):
    """Reviewer must-fix: startup trims leases.jsonl to the newest
    lines (bounded disk); under-cap files untouched, no tmp left."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                    "..", "tools", "egress"))
    import supervisor as sup
    monkeypatch.setattr(sup, "LEASES_PATH", tmp_path / "leases.jsonl")
    monkeypatch.setattr(sup, "LEASES_TAIL_LINES", 10)
    monkeypatch.setattr(sup, "_LEASES_TRIM_BYTES", 0)
    path = tmp_path / "leases.jsonl"
    path.write_text("".join('{"n": %d}\n' % i for i in range(30)),
                    encoding="utf-8")
    sup._trim_leases_file()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10 and lines[0] == '{"n": 20}'
    assert not (tmp_path / "leases.jsonl.tmp").exists()
    small = tmp_path / "small.jsonl"
    small.write_text('{"n": 0}\n', encoding="utf-8")
    monkeypatch.setattr(sup, "LEASES_PATH", small)
    sup._trim_leases_file()  # under cap: untouched
    assert small.read_text(encoding="utf-8") == '{"n": 0}\n'


def test_auth_abort_flushes_stage_telemetry(tmp_path, monkeypatch):
    """Reviewer must-fix: an auth abort flushes in-memory stage rows
    (like quota-STOP) instead of losing them."""
    import pytest
    from factory.precard import pipeline as pipe
    from factory.precard.provider_transport import AuthError
    items = [{"kind": "word", "text": "apple", "pos": "noun",
              "pool_level": "A1"}]
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(items), encoding="utf-8")
    out = str(tmp_path / "precard.jsonl")

    def always_401(api_key, model, user_text):
        raise _http_401()

    with pytest.raises(AuthError):
        pipe.main(["--sample", str(sample), "--out", out,
                   "--progress-dir", str(tmp_path / "prog")],
                  **{**_hermetic_kwargs(),
                     "_topic_transport": always_401})
    recs = [json.loads(line) for line in
            (_out_dir(out) / "telemetry_records.jsonl").read_text(
                encoding="utf-8").splitlines() if line.strip()]
    assert recs  # judge rows flushed by _abort, not lost


def test_no_double_attempt_entry_on_raise_paths():
    """Reviewer-noise evidence: raises inside the rotation wrapper's
    `except HTTPError` block (RateLimited/AuthError/ProviderCooldown)
    propagate outward and never re-enter the generic handler — exactly
    one attempt_log entry per try."""
    import pytest
    from factory.core.llm_json import AuthError
    from factory.precard.provider_transport import (
        KeyRing, RateLimited, _call_with_rotation)
    state = {"done": {}, "failed": [], "backoffs": []}
    ring = KeyRing(["k1"])
    with pytest.raises(RateLimited):
        _call_with_rotation(
            lambda *a: (_ for _ in ()).throw(_http_429()),
            ring, "m", "t", lambda s: None, state, "lbl")
    assert len(ring.attempt_log) == 1
    assert ring.attempt_log[0]["outcome"] == "rotated"
    ring2 = KeyRing(["k1"])
    with pytest.raises(AuthError):
        _call_with_rotation(
            lambda *a: (_ for _ in ()).throw(_http_401()),
            ring2, "m", "t", lambda s: None,
            {"done": {}, "failed": [], "backoffs": []}, "lbl",
            key_var="K", file_label="f.env")
    assert len(ring2.attempt_log) == 1
    assert ring2.attempt_log[0]["outcome"] == "auth"


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


def test_run_start_carries_prompts_version_and_variant_map(tmp_path):
    """OC must-fix #765: run_start (run.log + run_events.jsonl) carries
    PROMPTS_VERSION + the resolved {name:variant} map, so two
    --prompt-variant runs are distinguishable in logs."""
    import os
    from factory.precard import pipeline as pipe
    from factory.precard import prompt_registry as PR
    PR.register_variant("topic_tiebreak", "test-alt-765", "ALT-TIEBREAK")
    saved_env = os.environ.get("FACTORY_PROMPT_VARIANT")
    os.environ.pop("FACTORY_PROMPT_VARIANT", None)
    try:
        out = _run_apple(tmp_path, "--json-log", "--prompt-variant",
                         "topic_tiebreak=test-alt-765")
    finally:
        PR.reset()
        if saved_env is not None:
            os.environ["FACTORY_PROMPT_VARIANT"] = saved_env
    parent = _out_dir(out)
    events = [json.loads(line) for line in
              (parent / "run_events.jsonl").read_text(
                  encoding="utf-8").splitlines() if line.strip()]
    starts = [e for e in events if e["event"] == "run_start"]
    assert len(starts) == 1
    assert starts[0]["prompts_version"] == PR.PROMPTS_VERSION == "v1"
    assert starts[0]["prompt_variants"]["topic_tiebreak"] == "test-alt-765"
    assert set(starts[0]["prompt_variants"]) == set(PR.PROMPT_NAMES)
    log_lines = (parent / "run.log").read_text(
        encoding="utf-8").splitlines()
    assert log_lines and log_lines[0].startswith("run ")
    assert any("test-alt-765" in line and "v1" in line
               for line in log_lines[1:])
