"""Hermetic tests for factory/blind50.py (4-way S2 blind test).

No network, no W:, no real keys: HTTP is an injected fake, key files
are tmp_path fixtures, S1 windows are inline dicts.
"""

import io
import json
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "factory"))
import blind50

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

    # report_fn=None also gates the on-mode paths (no crash, no call).
    calls = []

    def flaky(chunk, prompt):
        calls.append(1)
        if len(calls) == 1:
            raise _http_error(400, LOCATION_BODY)
        return {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}

    out = blind50.run_model("g35", ITEMS, ANCHOR_MAP,
                            str(tmp_path / "r.json"), flaky,
                            pace=0, sleep_fn=lambda s: None,
                            provider="google", report_fn=None)
    assert out == {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}


def test_on_mode_reports_ok_429_and_location_blocked(tmp_path):
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
        key = blind50.precard_pipeline.item_key
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


def test_supervisor_outcome_maps_location_blocked():
    assert blind50._supervisor_outcome("location-blocked") == "http429"
    assert blind50._supervisor_outcome("ok") == "ok"
    assert blind50._supervisor_outcome("http429") == "http429"


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
