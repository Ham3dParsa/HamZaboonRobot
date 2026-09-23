"""Hermetic tests for factory/pipeline/blind50.py (4-way S2 blind test).

No network, no W:, no real keys: HTTP is an injected fake, key files
are tmp_path fixtures, S1 windows are inline dicts.
"""

import io
import json
import urllib.error

import pytest

from factory.pipeline import blind50
ANCHOR_MAP = {
    "w:apple": {"candidates": [
        {"sense_id": "apple#0", "gloss": "a round fruit"},
        {"sense_id": "apple#1", "gloss": "a tech company"}]},
}
ITEMS = [{"kind": "word", "text": "apple", "pos": "noun",
          "pool_level": "A1"}]
GOOD = json.dumps({"results": [{"key": "w:apple",
                                "pick": "apple#0"}]})


def _google_envelope(text):
    return json.dumps({"candidates": [{"content": {"parts": [
        {"text": text}]}}], "usageMetadata": {}}).encode()


def test_key_precedence_env_over_files(tmp_path):
    factory_env = tmp_path / "factory.env"
    factory_env.write_text("GOOGLE_AI_API_KEY=file-key\n",
                           encoding="utf-8")
    keys = blind50.load_keys(
        {"GOOGLE_AI_API_KEY": "env-key"},
        str(factory_env), str(tmp_path / "nope.env"))
    assert keys["GOOGLE_AI_API_KEY"] == "env-key"


def test_key_fallback_to_egress_env(tmp_path):
    factory_env = tmp_path / "factory.env"
    factory_env.write_text("", encoding="utf-8")
    egress_env = tmp_path / "egress.env"
    egress_env.write_text("GOOGLE_AI_API_KEY=egress-key\n",
                          encoding="utf-8")
    keys = blind50.load_keys({}, str(factory_env), str(egress_env))
    assert keys["GOOGLE_AI_API_KEY"] == "egress-key"


def test_google_judge_parses_envelope():
    calls = []

    def fake_post(url, payload, timeout):
        calls.append((url, payload))
        return _google_envelope(GOOD)

    out = blind50.google_judge("k", "gemini-3.5-flash-lite", ITEMS,
                               "PROMPT", ANCHOR_MAP, http_post=fake_post)
    assert out["w:apple"]["sense_id"] == "apple#0"
    assert "gemini-3.5-flash-lite" in calls[0][0]
    body = json.loads(calls[0][1].decode())
    assert body["generationConfig"]["thinkingConfig"][
        "thinkingLevel"] == "MINIMAL"


def test_invalid_json_retries_once_then_fails_closed():
    seen = []

    def fake_post(url, payload, timeout):
        seen.append(payload)
        if len(seen) == 1:
            return _google_envelope("not json{{")
        return _google_envelope(json.dumps({"results": []}))

    out = blind50.google_judge("k", "m", ITEMS, "PROMPT", ANCHOR_MAP,
                               http_post=fake_post)
    assert len(seen) == 2  # one retry, then fail-closed {}
    assert out == {}


def test_three_consecutive_429_aborts(tmp_path, capsys):
    items = [dict(ITEMS[0], text="w%d" % i) for i in range(3)]

    def fake_judge(chunk, prompt):
        raise urllib.error.HTTPError("u", 429, "slow", {}, None)

    try:
        blind50.run_model("g35", items, ANCHOR_MAP, str(tmp_path / "p.json"),
                          fake_judge, batch=1, pace=0,
                          sleep_fn=lambda s: None)
    except blind50.RateLimited:
        out = capsys.readouterr().out
        assert "429 (strike 3/3, stopping)" in out
        assert out.count("re-queued") == 2
        return
    raise AssertionError("expected RateLimited after 3x429")


def test_isolated_429_requeues_instead_of_dropping(tmp_path, capsys):
    calls = []

    def fake_judge(chunk, prompt):
        calls.append(chunk[0]["text"])
        if len(calls) == 1:
            raise urllib.error.HTTPError("u", 429, "slow", {}, None)
        return {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}

    out = blind50.run_model("g35", ITEMS, ANCHOR_MAP, str(tmp_path / "p.json"),
                            fake_judge, pace=0,
                            sleep_fn=lambda s: None)
    assert calls == ["apple", "apple"]  # same batch retried
    assert out["w:apple"]["sense_id"] == "apple#0"
    logs = capsys.readouterr().out
    assert "429 (strike 1/3, re-queued)" in logs


def test_openrouter_sends_bearer_token(monkeypatch):
    seen = {}

    def fake_default(url, payload, timeout, headers=None):
        seen.update(headers or {})
        return json.dumps({"choices": [{"message": {"content": GOOD}}]}
                          ).encode()

    monkeypatch.setattr(blind50, "_default_post", fake_default)
    out = blind50.openrouter_judge("secret-k", "m", ITEMS, "PROMPT",
                                   ANCHOR_MAP)
    assert out["w:apple"]["sense_id"] == "apple#0"
    assert seen.get("Authorization") == "Bearer secret-k"


def test_progress_resume_skips_done(tmp_path):
    prog = tmp_path / "prog.json"
    prog.write_text(json.dumps({"g35": {"w:apple": {"sense_id": "x"}}}),
                    encoding="utf-8")

    def fake_judge(chunk, prompt):
        raise AssertionError("must not call network for done keys")

    out = blind50.run_model("g35", ITEMS, ANCHOR_MAP, str(prog), fake_judge,
                            pace=0, sleep_fn=lambda s: None)
    assert out == {"w:apple": {"sense_id": "x"}}


def test_fill_missing_windows_uses_ranker():
    anchor_map = dict(ANCHOR_MAP)

    def fake_rank(item, index, read_entry):
        assert index is None and read_entry is None
        return {"candidates": [
            {"sense_id": "pear#0", "gloss": "a fruit"}]}

    items = ITEMS + [{"kind": "word", "text": "pear", "pos": "noun",
                      "pool_level": "A1"}]
    out = blind50.fill_missing_windows(items, anchor_map,
                                       rank_fn=fake_rank)
    assert out["w:apple"] is ANCHOR_MAP["w:apple"]
    assert out["w:pear"]["candidates"][0]["sense_id"] == "pear#0"


def test_fill_missing_windows_fail_closed():
    def bad_rank(item, index, read_entry):
        raise RuntimeError("kaikki down")

    items = ITEMS + [{"kind": "word", "text": "pear", "pos": "noun",
                      "pool_level": "A1"}]
    out = blind50.fill_missing_windows(items, ANCHOR_MAP, rank_fn=bad_rank)
    assert out["w:pear"] == {"candidates": []}


def test_run_model_prints_progress(capsys, tmp_path):
    def fake_judge(chunk, prompt):
        return {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}

    blind50.run_model("g35", ITEMS, ANCHOR_MAP, str(tmp_path / "p.json"),
                      fake_judge, pace=0, sleep_fn=lambda s: None)
    out = capsys.readouterr().out
    assert "[blind50 g35] start: 1 items (1 todo, 0 kept)" in out
    assert "[blind50 g35] batch 1/1: done=1/1" in out
    assert "[blind50 g35] finished: done=1/1" in out
    out.encode("ascii")


def test_flag_aliases_anchor_and_glm_judge(tmp_path, capsys):
    """Voice: --anchor/--glm-judge canonical; --s1/--glm-s2 still work."""
    import factory.pipeline.blind50 as b50

    accept = tmp_path / "a.json"
    accept.write_text(json.dumps(ITEMS), encoding="utf-8")
    anchor_f = tmp_path / "anchor.json"
    anchor_f.write_text(json.dumps({"done": ANCHOR_MAP}), encoding="utf-8")
    glm_f = tmp_path / "glm.json"
    glm_f.write_text(json.dumps({"done": {}}), encoding="utf-8")
    for flags in (["--anchor", "--glm-judge"], ["--s1", "--glm-s2"]):
        out = tmp_path / "o.json"
        assert b50.main([
            "--accept", str(accept), flags[0], str(anchor_f), flags[1],
            str(glm_f), "--out", str(out),
            "--progress", str(tmp_path / "p.json"),
            "--dry-run"]) == 0


LOCATION_BODY = (
    '{"error":{"code":400,"message":"User location is not supported '
    'for the API use.","status":"FAILED_PRECONDITION"}}'
).encode()


def _http_error(code, body):
    return urllib.error.HTTPError(
        "http://x", code, "err", {}, io.BytesIO(body))


def test_off_mode_is_byte_identical_and_never_reports(tmp_path):
    """Default off mode (provider/report_fn None) is today's behavior."""
    def fake_judge(chunk, prompt):
        return {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}

    prog = tmp_path / "p.json"
    out = blind50.run_model("g35", ITEMS, ANCHOR_MAP, str(prog),
                            fake_judge, pace=0, sleep_fn=lambda s: None)
    assert out == {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}
    assert prog.read_bytes() == json.dumps(
        {"g35": out}, ensure_ascii=False).encode("utf-8")

    # A 400 location body still takes today's raise path when the
    # provider is unknown (no classify location row fires).
    def boom(chunk, prompt):
        raise _http_error(400, LOCATION_BODY)

    with pytest.raises(urllib.error.HTTPError):
        blind50.run_model("g35", ITEMS, ANCHOR_MAP,
                          str(tmp_path / "q.json"), boom,
                          pace=0, sleep_fn=lambda s: None)

    # Off mode is byte-identical: even with provider set, a 400
    # location body raises (today's path) when report_fn is None.
    def flaky(chunk, prompt):
        raise _http_error(400, LOCATION_BODY)

    with pytest.raises(urllib.error.HTTPError):
        blind50.run_model("g35", ITEMS, ANCHOR_MAP,
                          str(tmp_path / "r.json"), flaky,
                          pace=0, sleep_fn=lambda s: None,
                          provider="google", report_fn=None)


def test_on_mode_reports_ok_429_and_location_blocked(tmp_path, capsys):
    """report_fn(provider, outcome) fires once per attempted batch."""
    items = [dict(ITEMS[0]),
             {"kind": "word", "text": "pear", "pos": "noun",
              "pool_level": "A1"}]
    seen = []
    calls = []

    def fake_judge(chunk, prompt):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(429, b"slow down")
        if len(calls) == 2:
            raise _http_error(400, LOCATION_BODY)
        key = blind50.precard_accounting.source_item_key
        return {key(it): {"sense_id": "s", "gloss": "x"} for it in chunk}

    out = blind50.run_model(
        "g35", items, ANCHOR_MAP, str(tmp_path / "p.json"), fake_judge,
        batch=1, pace=0, sleep_fn=lambda s: None,
        provider="google", report_fn=lambda p, o: seen.append((p, o)))
    assert seen == [("google", "http429"),
                    ("google", "location-blocked"),
                    ("google", "ok"),
                    ("google", "ok")]
    assert out["w:apple"]["sense_id"] == "s"
    assert out["w:pear"]["sense_id"] == "s"
    logs = capsys.readouterr().out
    assert "location-blocked (strike 2/3" in logs


def test_on_mode_reports_cooldown_switch_as_http429(tmp_path):
    """Non-429 COOLDOWN_SWITCH (Google 400 resource_exhausted) reports
    http429 so the supervisor cools the dead egress instead of
    re-leasing it on the next run."""
    seen = []
    calls = []

    def fake_judge(chunk, prompt):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(400, b"RESOURCE_EXHAUSTED: quota")
        key = blind50.precard_accounting.source_item_key
        return {key(it): {"sense_id": "s", "gloss": "x"} for it in chunk}

    out = blind50.run_model(
        "g35", ITEMS, ANCHOR_MAP, str(tmp_path / "p.json"), fake_judge,
        batch=1, pace=0, sleep_fn=lambda s: None,
        provider="google", report_fn=lambda p, o: seen.append((p, o)))
    assert seen == [("google", "http429"), ("google", "ok")]
    assert out["w:apple"]["sense_id"] == "s"


def test_report_fn_raising_is_warned_and_continued(tmp_path, capsys):
    """A throwing report_fn must not break judging: batch committed, warn logged.

    Direct run_model() callers (not main()'s closure) pass report_fn in;
    its exceptions must warn-and-continue, never mask a committed batch
    nor the 429/location-blocked strike logic.
    """
    called = {"n": 0}

    def fake_judge(chunk, prompt):
        return {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}

    def boom_report(provider, outcome):
        called["n"] += 1
        raise ValueError("observer down")

    prog = tmp_path / "p.json"
    out = blind50.run_model(
        "g35", ITEMS, ANCHOR_MAP, str(prog), fake_judge, pace=0,
        sleep_fn=lambda s: None, provider="google", report_fn=boom_report)
    # Batch committed despite report_fn raising.
    assert out["w:apple"]["sense_id"] == "apple#0"
    assert called["n"] == 1
    on_disk = json.loads(prog.read_text(encoding="utf-8"))
    assert on_disk["g35"]["w:apple"]["sense_id"] == "apple#0"  # atomic write OK
    logs = capsys.readouterr().out
    assert "[blind50 g35] report failed:" in logs
    assert "observer down" in logs


def test_report_fn_none_unchanged_no_report_call(tmp_path):
    """report_fn None: no reporting path, no try/except overhead, byte-identical."""
    def fake_judge(chunk, prompt):
        return {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}

    prog = tmp_path / "p.json"
    out = blind50.run_model("g35", ITEMS, ANCHOR_MAP, str(prog), fake_judge,
                            pace=0, sleep_fn=lambda s: None)
    assert out == {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}


def test_supervisor_outcome_passthrough_location_blocked():
    # R5: no mapping layer remains — the supervisor takes
    # "location-blocked" first-class, so the observer-visible outcome
    # travels verbatim (no http429 rewrite).
    assert not hasattr(blind50, "_SUPERVISOR_OUTCOME")
    assert getattr(blind50, "_supervisor_outcome", None) is None


class _FakeSupervisor:
    instances = []

    def __init__(self, base_url, token=""):
        self.base_url = base_url
        self.token = token
        self.leases = []
        self.reports = []
        _FakeSupervisor.instances.append(self)

    def lease(self, target):
        self.leases.append(target)
        return {"lease_id": "L1"}

    def report(self, lease_id, outcome, provider=None):
        self.reports.append((lease_id, outcome, provider))


def _main_files(tmp_path):
    accept = tmp_path / "accept.json"
    accept.write_text(json.dumps(ITEMS), encoding="utf-8")
    s1 = tmp_path / "s1.json"
    s1.write_text(json.dumps({"done": dict(ANCHOR_MAP)}),
                  encoding="utf-8")
    glm = tmp_path / "glm.json"
    glm.write_text(json.dumps({"done": {}}), encoding="utf-8")
    return accept, s1, glm


def test_main_supervisor_on_leases_and_reports(monkeypatch, tmp_path):
    _FakeSupervisor.instances.clear()
    monkeypatch.setattr(blind50, "_SupervisorClient", _FakeSupervisor)
    monkeypatch.setattr(
        blind50, "google_judge",
        lambda k, m, chunk, prompt, anchors, **kw: {
            "w:apple": {"sense_id": "apple#0", "gloss": "x"}})
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "k")
    accept, s1, glm = _main_files(tmp_path)
    out = tmp_path / "out.json"
    prog = tmp_path / "prog.json"
    assert blind50.main([
        "--accept", str(accept), "--s1", str(s1),
        "--glm-s2", str(glm), "--out", str(out),
        "--progress", str(prog), "--models", "g35",
        "--pace", "0", "--supervisor", "http://127.0.0.1:1",
        "--sup-token", "tok"]) == 0
    (sup,) = _FakeSupervisor.instances
    assert sup.base_url == "http://127.0.0.1:1"
    assert sup.token == "tok"
    assert sup.leases == ["google"]  # g35 leases the google target
    assert sup.reports == [("L1", "ok", "google")]
    assert json.loads(out.read_text(encoding="utf-8"))["g35"][
        "w:apple"]["sense_id"] == "apple#0"


def test_main_supervisor_lease_failure_aborts_tag(monkeypatch, tmp_path):
    class _FailingSup(_FakeSupervisor):
        def lease(self, target):
            self.leases.append(target)
            return {"error": "park", "message": "no link-bearing server"}

    monkeypatch.setattr(blind50, "_SupervisorClient", _FailingSup)
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "k")
    accept, s1, glm = _main_files(tmp_path)
    with pytest.raises(SystemExit) as exc:
        blind50.main([
            "--accept", str(accept), "--s1", str(s1),
            "--glm-s2", str(glm), "--out", str(tmp_path / "o.json"),
            "--progress", str(tmp_path / "p.json"), "--models", "g35",
            "--pace", "0", "--supervisor", "http://127.0.0.1:1"])
    assert "g35" in str(exc.value)
    assert "no link-bearing server" in str(exc.value)


def test_main_supervisor_lease_transport_failure_aborts(monkeypatch, tmp_path):
    """sup.lease raising (URLError/timeout) aborts loudly via SystemExit."""
    import urllib.error as _urlerr

    class _BoomSup(_FakeSupervisor):
        def lease(self, target):
            self.leases.append(target)
            raise _urlerr.URLError("conn refused")

    monkeypatch.setattr(blind50, "_SupervisorClient", _BoomSup)
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "k")
    accept, s1, glm = _main_files(tmp_path)
    with pytest.raises(SystemExit) as exc:
        blind50.main([
            "--accept", str(accept), "--s1", str(s1),
            "--glm-s2", str(glm), "--out", str(tmp_path / "o.json"),
            "--progress", str(tmp_path / "p.json"), "--models", "g35",
            "--pace", "0", "--supervisor", "http://127.0.0.1:1"])
    assert "supervisor lease failed" in str(exc.value)
    assert "g35" in str(exc.value)


def test_main_supervisor_lease_without_id_aborts(monkeypatch, tmp_path):
    """Lease dicts without a truthy lease_id abort (no blank reports)."""
    for bad in ({}, {"lease_id": ""}):
        class _EmptySup(_FakeSupervisor):
            def lease(self, target, _bad=bad):
                self.leases.append(target)
                return dict(_bad)

        _FakeSupervisor.instances.clear()
        monkeypatch.setattr(blind50, "_SupervisorClient", _EmptySup)
        monkeypatch.setenv("GOOGLE_AI_API_KEY", "k")
        accept, s1, glm = _main_files(tmp_path)
        with pytest.raises(SystemExit) as exc:
            blind50.main([
                "--accept", str(accept), "--s1", str(s1),
                "--glm-s2", str(glm), "--out", str(tmp_path / "o.json"),
                "--progress", str(tmp_path / "p.json"), "--models", "g35",
                "--pace", "0", "--supervisor", "http://127.0.0.1:1"])
        assert "supervisor lease failed" in str(exc.value)
