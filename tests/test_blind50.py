"""Hermetic tests for factory/blind50.py (4-way S2 blind test).

No network, no W:, no real keys: HTTP is an injected fake, key files
are tmp_path fixtures, S1 windows are inline dicts.
"""

import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "factory"))
import blind50

S1MAP = {
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
                               "PROMPT", S1MAP, http_post=fake_post)
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

    out = blind50.google_judge("k", "m", ITEMS, "PROMPT", S1MAP,
                               http_post=fake_post)
    assert len(seen) == 2  # one retry, then fail-closed {}
    assert out == {}


def test_three_consecutive_429_aborts(tmp_path):
    items = [dict(ITEMS[0], text="w%d" % i) for i in range(3)]

    def fake_judge(chunk, prompt):
        raise urllib.error.HTTPError("u", 429, "slow", {}, None)

    try:
        blind50.run_model("g35", items, S1MAP, str(tmp_path / "p.json"),
                          fake_judge, batch=1, pace=0,
                          sleep_fn=lambda s: None)
    except blind50.RateLimited:
        return
    raise AssertionError("expected RateLimited after 3x429")


def test_isolated_429_requeues_instead_of_dropping(tmp_path):
    calls = []

    def fake_judge(chunk, prompt):
        calls.append(chunk[0]["text"])
        if len(calls) == 1:
            raise urllib.error.HTTPError("u", 429, "slow", {}, None)
        return {"w:apple": {"sense_id": "apple#0", "gloss": "x"}}

    out = blind50.run_model("g35", ITEMS, S1MAP, str(tmp_path / "p.json"),
                            fake_judge, pace=0,
                            sleep_fn=lambda s: None)
    assert calls == ["apple", "apple"]  # same batch retried
    assert out["w:apple"]["sense_id"] == "apple#0"


def test_openrouter_sends_bearer_token(monkeypatch):
    seen = {}

    def fake_default(url, payload, timeout, headers=None):
        seen.update(headers or {})
        return json.dumps({"choices": [{"message": {"content": GOOD}}]}
                          ).encode()

    monkeypatch.setattr(blind50, "_default_post", fake_default)
    out = blind50.openrouter_judge("secret-k", "m", ITEMS, "PROMPT",
                                   S1MAP)
    assert out["w:apple"]["sense_id"] == "apple#0"
    assert seen.get("Authorization") == "Bearer secret-k"


def test_progress_resume_skips_done(tmp_path):
    prog = tmp_path / "prog.json"
    prog.write_text(json.dumps({"g35": {"w:apple": {"sense_id": "x"}}}),
                    encoding="utf-8")

    def fake_judge(chunk, prompt):
        raise AssertionError("must not call network for done keys")

    out = blind50.run_model("g35", ITEMS, S1MAP, str(prog), fake_judge,
                            pace=0, sleep_fn=lambda s: None)
    assert out == {"w:apple": {"sense_id": "x"}}


def test_fill_missing_windows_uses_ranker():
    s1map = dict(S1MAP)

    def fake_rank(item, index, read_entry):
        assert index is None and read_entry is None
        return {"candidates": [
            {"sense_id": "pear#0", "gloss": "a fruit"}]}

    items = ITEMS + [{"kind": "word", "text": "pear", "pos": "noun",
                      "pool_level": "A1"}]
    out = blind50.fill_missing_windows(items, s1map,
                                       rank_fn=fake_rank)
    assert out["w:apple"] is S1MAP["w:apple"]
    assert out["w:pear"]["candidates"][0]["sense_id"] == "pear#0"


def test_fill_missing_windows_fail_closed():
    def bad_rank(item, index, read_entry):
        raise RuntimeError("kaikki down")

    items = ITEMS + [{"kind": "word", "text": "pear", "pos": "noun",
                      "pool_level": "A1"}]
    out = blind50.fill_missing_windows(items, S1MAP, rank_fn=bad_rank)
    assert out["w:pear"] == {"candidates": []}
