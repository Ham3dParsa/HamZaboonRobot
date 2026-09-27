"""Wave two worker two: benchmark logic + gold evaluator ONLY.

Isolated unit tests with mocked model responses (no network, no keys,
no files outside tmp paths). Kilo arrives as DATA through the manifest
manager — never a code row. Secret VALUES never appear anywhere: only
provider/key NAMES cross these tests.
"""

import json
import pathlib

from factory.precard import provider_benchmark as bench
from factory.precard import provider_manifest as manifest_mod

#: Canary value that must never appear in any result blob (no key
#: VALUES exist in this scope, so its absence proves secret-freedom).
_CANARY_VALUE = "CANARY-SECRET-VALUE-9f3"


def _write_witness(tmp_path, rows):
    path = str(tmp_path / "calibration_gold_test.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False)
    return path


def _gold_rows():
    return [
        {"kid": "run#1", "gemini_verdict": "LINK",
         "winner_sensekey": "run%2:38:00::"},
        {"kid": "run#2", "verdict": "REVIEW",
         "table_winner_sensekey": "run%2:38:01::"},
        {"kid": "run#3", "class": "LINK",
         "target_synset": "run.v.01"},
        {"kid": "run#4", "baseline": "REVIEW"},
    ]


def _patched_manager(tmp_path):
    """Tmp manifest with kilo registered as DATA (never a code row)."""
    path = str(tmp_path / "provider_manifest.json")
    mgr = manifest_mod.ProviderManifestManager(path=path)
    mgr.load()  # seeds the core providers, including google
    assert "google" in mgr.provider_names()
    mgr.create("kilo", {
        "protocol": "openai_compat",
        "base_url": "http://127.0.0.1:9/v1/chat/completions",
        "route": "direct",
        "key_vars": ["KILO_API_KEY_1"],
        "request_extras": {},
    })
    assert "kilo" in mgr.provider_names()
    return mgr


def _mock_invoke(script):
    """Fake model seam: (provider, kid) -> result dict (records calls)."""
    calls = []

    def _invoke(provider, sense):
        calls.append((provider, sense.get("kid")))
        return dict(script.get(
            (provider, sense.get("kid")),
            {"verdict": "", "winner": "", "input_tokens": 0,
             "output_tokens": 0, "latency_s": 0.0}))

    _invoke.calls = calls
    return _invoke


def _script_all_match(senses):
    script = {}
    for row in senses:
        for provider in ("google", "kilo"):
            script[(provider, row["kid"])] = {
                "verdict": row["expected_verdict"],
                "winner": row.get("expected_winner", ""),
                "input_tokens": 10, "output_tokens": 5,
                "latency_s": 1.23456}
    return script


def test_gold_loader_validates_fields(tmp_path):
    rows = [
        {"kid": "run#1", "gemini_verdict": "LINK",
         "winner_sensekey": "run%2:38:00::"},
        {"kid": "run#2", "verdict": "REVIEW"},  # winner optional
        {"kid": ""},  # invalid: empty kid
        {"verdict": "LINK"},  # invalid: no kid
        {"kid": "run#9"},  # invalid: no verdict
        "junk",  # invalid: not a dict
    ]
    path = _write_witness(tmp_path, rows)
    gold = bench.load_gold(path)
    assert gold["path"] == path
    assert gold["total"] == 6
    assert gold["skipped"] == 4
    assert [e["kid"] for e in gold["entries"]] == ["run#1", "run#2"]
    assert gold["entries"][0] == {
        "kid": "run#1", "expected_verdict": "LINK",
        "expected_winner": "run%2:38:00::"}
    assert gold["entries"][1]["expected_winner"] == ""
    # {"rows": [...]} shape accepted too.
    wrapped = _write_witness(tmp_path, {"rows": rows[:2]})
    assert len(bench.load_gold(wrapped)["entries"]) == 2


def test_gold_loader_rejects_bad_files(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        bench.load_gold(str(tmp_path / "absent.json"))
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        bench.load_gold(str(corrupt))
    shaped = _write_witness(tmp_path, {"kid": "run#1"})
    with pytest.raises(ValueError):
        bench.load_gold(shaped)


def test_full_sense_set_runs_match_pct_and_structured_dict(tmp_path):
    mgr = _patched_manager(tmp_path)
    senses = bench.load_gold(
        _write_witness(tmp_path, _gold_rows()))["entries"]
    assert len(senses) == 4
    # Google matches all four; kilo matches run#1 + run#3 only.
    script = _script_all_match(senses)
    script[("kilo", "run#2")] = {
        "verdict": "LINK", "winner": "", "input_tokens": 7,
        "output_tokens": 3, "latency_s": 2.5}
    script[("kilo", "run#4")] = {
        "verdict": "LINK", "winner": "", "input_tokens": 7,
        "output_tokens": 3, "latency_s": 2.5}
    invoke = _mock_invoke(script)
    runner = bench.ProviderBenchmark(manager=mgr, invoke_fn=invoke)
    report = runner.run_all(senses=senses,
                            providers=["google", "kilo"])
    assert set(report) == {"gold_path", "providers", "total_senses",
                           "results", "summary", "note"}
    assert report["providers"] == ["google", "kilo"]
    assert report["total_senses"] == 4
    assert len(report["results"]) == 8
    for row in report["results"]:
        assert set(row) == {"kid", "expected_verdict",
                            "expected_winner", "provider",
                            "latency_s", "input_tokens",
                            "output_tokens", "model_verdict",
                            "model_winner", "match", "error"}
        assert row["error"] is None
    summary = report["summary"]
    assert summary["total_runs"] == 8
    assert summary["total_matches"] == 6
    assert summary["accuracy"] == 0.75
    assert summary["accuracy_pct"] == 75.0
    assert summary["mean_latency_s"] == round(
        (4 * 1.235 + 2 * 1.235 + 2 * 2.5) / 8, 3)
    per = summary["tokens_per_provider"]
    assert per["google"]["input_tokens"] == 40
    assert per["google"]["output_tokens"] == 20
    assert per["google"]["accuracy"] == 1.0
    assert per["kilo"]["input_tokens"] == 10 + 10 + 7 + 7
    assert per["kilo"]["output_tokens"] == 5 + 5 + 3 + 3
    assert per["kilo"]["accuracy"] == 0.5
    blob = json.dumps(report, ensure_ascii=False)
    assert _CANARY_VALUE not in blob
    assert "google" in blob and "kilo" in blob


def test_single_sense_filter_runs_one(tmp_path):
    mgr = _patched_manager(tmp_path)
    senses = bench.load_gold(
        _write_witness(tmp_path, _gold_rows()))["entries"]
    invoke = _mock_invoke(_script_all_match(senses))
    runner = bench.ProviderBenchmark(manager=mgr, invoke_fn=invoke)
    report = runner.run_all(senses=senses, providers=["google", "kilo"],
                            sense_id="run#2")
    assert report["total_senses"] == 1
    assert len(report["results"]) == 2
    assert {r["kid"] for r in report["results"]} == {"run#2"}
    assert report["summary"]["accuracy"] == 1.0
    missing = runner.run_all(senses=senses, providers=["google"],
                             sense_id="run#99")
    assert missing["results"] == []
    assert missing["summary"]["total_runs"] == 0
    assert missing["note"].startswith("sense not found")


def test_unknown_provider_parks_without_invoke(tmp_path):
    mgr = _patched_manager(tmp_path)
    senses = bench.load_gold(
        _write_witness(tmp_path, _gold_rows()[:1]))["entries"]
    invoke = _mock_invoke(_script_all_match(senses))
    runner = bench.ProviderBenchmark(manager=mgr, invoke_fn=invoke)
    rows = runner.run_sense(senses[0], ["google", "nope"])
    assert rows[0]["error"] is None and rows[0]["match"] is True
    assert rows[1]["match"] is False
    assert rows[1]["error"].startswith("unknown provider: nope")
    assert [c for c in invoke.calls if c[0] == "nope"] == []


def test_missing_invoke_fn_parks_without_live_call(tmp_path):
    mgr = _patched_manager(tmp_path)
    senses = bench.load_gold(
        _write_witness(tmp_path, _gold_rows()[:1]))["entries"]
    runner = bench.ProviderBenchmark(manager=mgr, invoke_fn=None)
    rows = runner.run_sense(senses[0], ["google", "kilo"])
    assert all(r["match"] is False for r in rows)
    assert all(r["error"] and "no invoke_fn" in r["error"]
               for r in rows)


def test_kilo_never_a_code_row():
    # A provider ROW is quoted data (protocol literal, endpoint key,
    # key-var NAME literal); prose mentions in comments/docstrings are
    # not rows. Kilo's row arrives via manager.create() in tmp DATA.
    src = pathlib.Path(bench.__file__).read_text(encoding="utf-8")
    for literal in ('"openai_compat"', "'openai_compat'",
                    '"base_url"', "'base_url'",
                    '"gemini_rest"', "'gemini_rest'"):
        assert literal not in src
    assert "api.kilo" not in src.lower()
    assert "KILO_API_KEY" not in src  # key NAMES live in manifest DATA
