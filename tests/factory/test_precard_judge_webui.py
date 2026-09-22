"""Focused tests for the linker-judge WebUI thin adapter.

Behavior spec: CLI is the system of record; the WebUI only builds the
exact ``python -m factory.precard`` command, spawns it, tails the
engine's run_events.jsonl, and scores outputs against gold labels.
Secrets never surface (booleans only); custom runs are non-comparable.
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.linking.webui import server as webui
from factory.precard import provider_registry


def _fields(**over):
    base = {"provider": "avalai", "model": "", "sample": "",
            "limit": 0, "out": "", "progress_dir": "", "resume": "on"}
    base.update(over)
    return base


def test_build_minimal_is_base_command():
    argv = webui.build_cli_argv(_fields())
    assert argv[:3] == [sys.executable, "-m", "factory.precard"]
    assert "--llm-provider" in argv and "avalai" in argv
    assert "--json-log" in argv
    assert "--no-resume" not in argv and "--resume" not in argv
    assert "--limit" not in argv


def test_build_full_fields_exact_flags():
    argv = webui.build_cli_argv(_fields(
        model="deepseek-v4-flash", sample="s.json", limit=8,
        out="o.jsonl", progress_dir="pdir", resume="off"))
    for flag, value in (("--precard-model", "deepseek-v4-flash"),
                        ("--sample", "s.json"), ("--limit", "8"),
                        ("--out", "o.jsonl"), ("--progress-dir", "pdir")):
        assert flag in argv
        assert argv[argv.index(flag) + 1] == value
    assert "--no-resume" in argv


def test_build_resume_plan_flag():
    argv = webui.build_cli_argv(_fields(resume="plan"))
    assert "--resume" in argv
    assert "--no-resume" not in argv


def test_build_rejects_unknown_provider():
    with pytest.raises(ValueError):
        webui.build_cli_argv(_fields(provider="nope-provider"))


def test_build_rejects_bad_limit_and_resume():
    with pytest.raises(ValueError):
        webui.build_cli_argv(_fields(limit=-1))
    with pytest.raises(ValueError):
        webui.build_cli_argv(_fields(limit="many"))
    with pytest.raises(ValueError):
        webui.build_cli_argv(_fields(resume="sometimes"))


def test_cli_equivalent_replays_identically():
    argv = webui.build_cli_argv(_fields(
        model="m", sample="s.json", limit=3, resume="off"))
    shown = webui.cli_equivalent(argv)
    assert shown.startswith("python -m factory.precard")
    for token in ("--llm-provider", "avalai", "--precard-model", "m",
                  "--sample", "s.json", "--limit", "3",
                  "--no-resume", "--json-log"):
        assert token in shown


def test_key_presence_booleans_only_never_values():
    secret = "SUPER-SECRET-VALUE-12345"
    refs = list(provider_registry.key_ref_for("avalai", "G1")
                + provider_registry.key_ref_for("avalai", "G2"))
    assert refs, "engine registry must name key vars"
    os.environ[refs[0]] = secret
    try:
        rows = webui.key_presence()
        names = [r["name"] for r in rows]
        assert names == provider_registry.provider_names()
        body = json.dumps(rows)
        assert secret not in body
        avalai = [r for r in rows if r["name"] == "avalai"][0]
        assert avalai["has_key"] is True
        assert isinstance(avalai["has_key"], bool)
        assert avalai["key_var"] == webui._provider_key_var("avalai")
        assert avalai["key_var"] in avalai["key_vars"]
        for var in refs:
            assert var in avalai["key_vars"]
    finally:
        del os.environ[refs[0]]


def test_scrub_secrets_redacts_values():
    secret = "SCRUB-ME-99999999"
    os.environ["JUDGE_WEBUI_TEST_KEY"] = secret
    try:
        out = webui.scrub_secrets("using key=%s then ok" % secret)
        assert secret not in out
        assert "api_key=***" in webui.scrub_secrets("x api_key=abc123 y")
    finally:
        del os.environ["JUDGE_WEBUI_TEST_KEY"]


def test_parse_run_events_skips_bad_lines():
    text = ('{"event": "run_start", "run_id": "r1"}\n'
            'not json\n'
            '{"event": "batch", "stage": "sense_judge", "batch": 1}\n')
    events = webui.parse_run_events(text)
    assert [e["event"] for e in events] == ["run_start", "batch"]
    assert events[0]["run_id"] == "r1"


def test_score_against_gold_accuracy_and_mismatches():
    run = {"w:laugh": "laugh#0", "w:better": "better#9", "w:zzz": "zzz#0"}
    gold = {"w:laugh": "laugh#0", "w:better": "better#0"}
    res = webui.score_against_gold(run, gold)
    assert res["total"] == 2
    assert res["matched"] == 1
    assert res["accuracy"] == pytest.approx(0.5)
    assert res["mismatches"] == [
        {"key": "w:better", "gold": "better#0", "predicted": "better#9"}]


def test_comparability_custom_watermark_without_gold():
    ok, reason = webui.comparability({}, {"w:a": "a#0"})
    assert ok is False
    assert webui.NON_COMPARABLE_WATERMARK in reason
    ok, _ = webui.comparability({"w:a": "a#0"}, {"w:a": "a#0"})
    assert ok is True


def test_gold_and_run_row_readers(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps([
        {"kind": "word", "text": "laugh", "sense_id": "laugh#0"},
        {"kind": "phrase", "text": "x y"},
        {"nope": True},
    ]), encoding="utf-8")
    gold = webui.gold_rows_by_key(str(sample))
    assert gold == {"w:laugh": "laugh#0", "p:x y": ""}
    out = tmp_path / "precard.jsonl"
    out.write_text('{"key": "w:laugh", "sense_id": "laugh#0"}\n'
                   'broken line\n'
                   '{"key": "w:laugh", "sense_id": "laugh#1"}\n',
                   encoding="utf-8")
    assert webui.run_rows_by_key(str(out)) == {"w:laugh": "laugh#1"}
    assert webui.run_rows_by_key(str(tmp_path / "missing.jsonl")) == {}
    assert webui.gold_rows_by_key(str(tmp_path / "missing.json")) == {}


def test_api_providers_has_no_secret_values():
    client = webui.app.test_client()
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    for var, val in os.environ.items():
        upper = var.upper()
        if ("KEY" in upper or "TOKEN" in upper or "SECRET" in upper) \
                and val and len(val) >= 8:
            assert val not in body


def test_api_create_rejects_unknown_provider():
    client = webui.app.test_client()
    resp = client.post("/api/runs", json=_fields(provider="nope"))
    assert resp.status_code == 400


def test_api_unknown_run_404():
    client = webui.app.test_client()
    assert client.get("/api/runs/does-not-exist").status_code == 404
    assert client.get(
        "/api/runs/does-not-exist/events").status_code == 404
    assert client.get(
        "/api/runs/does-not-exist/compare").status_code == 404


class _ExitedProc:
    def poll(self):
        return 0


def test_api_runs_reaps_exited_proc_without_deadlock(tmp_path, monkeypatch):
    """Reaping an exited run inside a locked handler must not deadlock.

    Regression: _poll_proc() pops from _procs under the registry lock while
    callers already hold it — a non-reentrant lock wedged the server as soon
    as any run finished.
    """
    registry = tmp_path / "runs.json"
    record = {"id": "r-dead", "status": "running", "exit_code": None,
              "provider": "avalai", "cli": "python -m factory.precard"}
    registry.write_text(json.dumps([record]), encoding="utf-8")
    monkeypatch.setattr(webui, "REGISTRY_PATH", str(registry))
    monkeypatch.setitem(webui._procs, "r-dead", _ExitedProc())
    try:
        out = {}

        def _get():
            out["resp"] = webui.app.test_client().get("/api/runs")

        worker = __import__("threading").Thread(target=_get, daemon=True)
        worker.start()
        worker.join(timeout=10)
        assert not worker.is_alive(), "GET /api/runs deadlocked"
        assert out["resp"].status_code == 200
        (run,) = out["resp"].get_json()["runs"]
        assert run["status"] == "done" and run["exit_code"] == 0
    finally:
        webui._procs.pop("r-dead", None)


# ─── Additions: dated layout, validation, presets, profiles, keys ───

def test_build_concurrency_flag_and_rejects():
    assert "--concurrency" not in webui.build_cli_argv(_fields())
    argv = webui.build_cli_argv(_fields(concurrency=4))
    assert argv[argv.index("--concurrency") + 1] == "4"
    for bad in (-1, 11, "many"):
        with pytest.raises(ValueError):
            webui.build_cli_argv(_fields(concurrency=bad))


def test_build_accepts_custom_profile_name(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "PROFILES_DIR", str(tmp_path))
    (tmp_path / "mine.json").write_text(json.dumps({
        "name": "mine", "base_url": "https://x.example/v1",
        "key_var": "MINE_API_KEY", "model": "m"}), encoding="utf-8")
    argv = webui.build_cli_argv(_fields(provider="mine"))
    assert "--llm-provider" in argv and "mine" in argv


def test_validate_sample_file_cases(tmp_path):
    ok, err, info = webui.validate_sample_file("")
    assert ok is False and err
    ok, err, _ = webui.validate_sample_file(str(tmp_path / "nope.json"))
    assert ok is False and "پیدا نشد" in err
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert webui.validate_sample_file(str(bad))[0] is False
    notlist = tmp_path / "notlist.json"
    notlist.write_text(json.dumps({"kind": "word"}), encoding="utf-8")
    ok, err, _ = webui.validate_sample_file(str(notlist))
    assert ok is False and "فهرست" in err
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    ok, err, _ = webui.validate_sample_file(str(empty))
    assert ok is False and "خالی" in err
    badrow = tmp_path / "badrow.json"
    badrow.write_text(json.dumps([{"kind": "word"}]), encoding="utf-8")
    ok, err, _ = webui.validate_sample_file(str(badrow))
    assert ok is False and "text" in err
    badkind = tmp_path / "badkind.json"
    badkind.write_text(json.dumps([{"kind": "noun", "text": "x"}]),
                       encoding="utf-8")
    ok, err, _ = webui.validate_sample_file(str(badkind))
    assert ok is False and "kind" in err
    good = tmp_path / "good.json"
    good.write_text(json.dumps([
        {"kind": "word", "text": "laugh", "sense_id": "laugh#0"},
        {"kind": "phrase", "text": "x y"},
    ]), encoding="utf-8")
    ok, err, info = webui.validate_sample_file(str(good))
    assert ok is True and err == "" and info == {"rows": 2, "gold": 1}


def test_run_name_sortable_and_dated():
    early = webui.run_name_for("2026-09-20T10:00:00+00:00", "aaaaaaaaaaaa")
    late = webui.run_name_for("2026-09-21T10:00:00+00:00", "bbbbbbbbbbbb")
    assert early < late
    assert early.startswith("2026-09-20T10-00-00_")
    assert early.endswith("_aaaaaaaaaaaa")
    assert webui._parent_of_run(early) == "2026-09-20"


def test_migrate_record_moves_dir_and_rewrites_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "RUNS_DIR", str(tmp_path / "runs"))
    old = tmp_path / "runs" / "abc123abc123"
    old.mkdir(parents=True)
    (old / "precard.jsonl").write_text("{}\n", encoding="utf-8")
    rec = {"id": "abc123abc123", "created": "2026-09-21T14:01:43+00:00",
           "dir": str(old), "out": str(old / "precard.jsonl"),
           "progress_dir": str(old / "progress"),
           "cli": "python --out '%s'" % (old / "precard.jsonl")}
    assert webui._migrate_record(rec) is True
    assert os.path.isdir(rec["dir"])
    assert not os.path.exists(str(old)) or rec["dir"] != str(old)
    assert rec["run_name"].startswith("2026-09-21T14-01-43_")
    assert rec["out"] == os.path.join(rec["dir"], "precard.jsonl")
    assert str(old) not in rec["cli"]
    # already-new layout is a no-op
    assert webui._migrate_record(rec) is False


def test_preset_save_version_bump_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path))
    rec1 = webui.save_preset({"name": "p1", "provider": "avalai",
                              "model": "m", "sample": "s", "limit": 5,
                              "concurrency": 3})
    assert rec1["version"] == 1
    rec2 = webui.save_preset({"name": "p1", "provider": "avalai",
                              "model": "m2", "sample": "s", "limit": 0,
                              "concurrency": 0})
    assert rec2["version"] == 2 and rec2["model"] == "m2"
    assert webui.get_preset("p1")["version"] == 2
    assert [p["name"] for p in webui.list_presets()] == ["p1"]
    assert webui.delete_preset("p1") is True
    assert webui.delete_preset("p1") is False
    with pytest.raises(ValueError):
        webui.save_preset({"name": "p1", "provider": "nope"})


def test_profile_save_rejects_registry_name_and_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "PROFILES_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        webui.save_profile({"name": "avalai", "base_url": "https://x",
                            "key_var": "X_API_KEY", "model": ""})
    rec = webui.save_profile({"name": "mine", "base_url": "https://x/v1",
                              "key_var": "mine_api_key", "model": "m"})
    assert rec["key_var"] == "MINE_API_KEY"
    assert webui.get_profile("mine")["base_url"] == "https://x/v1"
    assert webui.delete_profile("mine") is True


def test_comparability_custom_profile_always_watermark():
    ok, reason = webui.comparability({"w:a": "a#0"}, {"w:a": "a#0"},
                                     profile="mine")
    assert ok is False
    assert webui.NON_COMPARABLE_WATERMARK in reason
    assert "mine" in reason


def test_api_preset_crud_names_only_and_run_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(webui, "PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.setattr(webui, "RUNS_DIR", str(tmp_path / "runs"))
    registry = tmp_path / "runs.json"
    registry.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(webui, "REGISTRY_PATH", str(registry))
    client = webui.app.test_client()
    resp = client.post("/api/presets", json={"name": "op1",
                                             "provider": "avalai", "model": "",
                                             "sample": "", "limit": 0,
                                             "concurrency": 0})
    assert resp.status_code == 200
    assert resp.get_json()["preset"]["version"] == 1
    assert client.get("/api/presets").get_json()["presets"][0]["name"] == "op1"
    # unknown preset on launch -> plain 400, nothing spawned
    resp = client.post("/api/runs", json=dict(_fields(), preset="ghost"))
    assert resp.status_code == 400


def test_api_keys_names_only_never_values(tmp_path, monkeypatch):
    keys = tmp_path / "operator_keys.json"
    monkeypatch.setattr(webui, "OPERATOR_KEYS_PATH", str(keys))
    client = webui.app.test_client()
    secret = "op-secret-value-987654321"
    resp = client.post("/api/keys", json={"key_var": "OP_TEST_KEY",
                                          "key_value": secret})
    assert resp.status_code == 200
    assert resp.get_json() == {"stored": "OP_TEST_KEY"}
    body = client.get("/api/keys").get_data(as_text=True)
    assert secret not in body
    assert "OP_TEST_KEY" in body
    stored = json.loads(keys.read_text(encoding="utf-8"))
    assert stored["OP_TEST_KEY"].startswith("v1:")
    assert secret not in json.dumps(stored)
    assert client.delete("/api/keys/OP_TEST_KEY").status_code == 200
    assert client.delete("/api/keys/OP_TEST_KEY").status_code == 404


def test_engine_info_matches_registry_and_states_gaps():
    info = webui.engine_info()
    assert info["providers"] == provider_registry.provider_names()
    assert "kilo" not in [p.lower() for p in info["providers"]]
    assert info["model_list"] is None
    assert info["temperature"] == {"supported": False, "fixed": 0.0}
    assert info["judge_batch"] >= 1
    assert info["concurrency"]["default"] == 8
    body = webui.app.test_client().get("/api/engine_info").get_json()
    assert body["providers"] == info["providers"]
    assert "kilo" not in json.dumps(body).lower()


def test_file_browser_roots_and_list(tmp_path):
    client = webui.app.test_client()
    roots = client.get("/api/files/roots").get_json()["roots"]
    assert roots and all("path" in r and "label" in r for r in roots)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "s.json").write_text("[]", encoding="utf-8")
    (tmp_path / "top.json").write_text("[]", encoding="utf-8")
    body = client.get("/api/files/list",
                      query_string={"dir": str(tmp_path)}).get_json()
    names = [(e["name"], e["is_dir"]) for e in body["entries"]]
    assert ("sub", True) in names and ("top.json", False) in names
    assert body["parent"] and body["dir"]
    # names only: no file contents, no secret values anywhere
    assert "[]" not in json.dumps(body)
    assert client.get("/api/files/list",
                      query_string={"dir": str(tmp_path / "nope") }
                      ).status_code == 400
    assert client.get("/api/files/list").status_code == 400


def test_preset_kinds_judge_and_run(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path))
    client = webui.app.test_client()
    # judge preset: kind forced by the judge route
    resp = client.post("/api/judge_presets", json={
        "name": "j1", "provider": "avalai", "model": "m", "concurrency": 4})
    assert resp.status_code == 200
    rec = resp.get_json()["judge_preset"]
    assert rec["kind"] == "judge" and rec["version"] == 1
    got = client.get("/api/judge_presets").get_json()
    assert [p["name"] for p in got["judge_presets"]] == ["j1"]
    # run preset: full compose form (out/progress_dir/resume included)
    resp = client.post("/api/job_templates", json={
        "name": "r1", "provider": "avalai", "model": "", "sample": "s",
        "limit": 5, "concurrency": 8, "out": "o.jsonl",
        "progress_dir": "pdir", "resume": "off"})
    assert resp.status_code == 200
    rec = resp.get_json()["job_template"]
    assert rec["kind"] == "run"
    assert (rec["out"], rec["progress_dir"], rec["resume"]) == (
        "o.jsonl", "pdir", "off")
    assert [p["name"] for p in
            client.get("/api/job_templates").get_json()["job_templates"]] == [
        "r1", webui.WITNESS_PRESET_NAME]
    # bad kind rejected; judge delete path works
    assert client.post("/api/presets", json={
        "name": "x", "provider": "avalai", "kind": "nope"}).status_code == 400
    assert client.delete("/api/judge_presets/j1").status_code == 200
    assert client.delete("/api/judge_presets/j1").status_code == 404


def test_witness_preset_seeded_once_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path))
    client = webui.app.test_client()
    names = [p["name"] for p in
             client.get("/api/presets").get_json()["presets"]]
    assert webui.WITNESS_PRESET_NAME in names
    wit = [p for p in client.get("/api/job_templates").get_json()
           ["job_templates"] if p["name"] == webui.WITNESS_PRESET_NAME][0]
    assert wit["kind"] == "run" and wit.get("ready") is True
    assert wit["limit"] > 0  # speed cap
    assert wit["sample"] == ""  # engine-default gold sample: accuracy
    # operator edit wins: re-seed never overwrites
    client.post("/api/job_templates", json=dict(
        wit, limit=7))
    kept = [p for p in client.get("/api/job_templates").get_json()
            ["job_templates"] if p["name"] == webui.WITNESS_PRESET_NAME][0]
    assert kept["limit"] == 7 and kept.get("ready") is True


def test_compare_rows_carry_glosses_and_text(tmp_path, monkeypatch):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps([
        {"kind": "word", "text": "laugh", "pos": "verb",
         "sense_id": "laugh#0", "en_def": "mirth sound"},
        {"kind": "word", "text": "better", "sense_id": "better#0"},
    ]), encoding="utf-8")
    out = tmp_path / "precard.jsonl"
    out.write_text(
        '{"key": "w:laugh", "sense_id": "laugh#0", "en_def": "mirth sound"}\n'
        '{"key": "w:better", "sense_id": "better#9", "en_def": "other"}\n',
        encoding="utf-8")
    monkeypatch.setattr(webui, "RUNS_DIR", str(tmp_path / "runs"))
    registry = tmp_path / "runs.json"
    registry.write_text(json.dumps([{
        "id": "r-gloss", "sample": str(sample), "out": str(out),
        "status": "done", "cli": "python -m factory.precard",
        "profile": None}]), encoding="utf-8")
    monkeypatch.setattr(webui, "REGISTRY_PATH", str(registry))
    body = webui.app.test_client().get(
        "/api/runs/r-gloss/compare").get_json()
    assert body["comparable"] is True
    by_key = {r["key"]: r for r in body["rows"]}
    laugh = by_key["w:laugh"]
    # human-readable first, technical ids still present (secondary)
    assert laugh["text"] == "laugh" and laugh["kind"] == "word"
    assert laugh["pos"] == "verb"
    assert laugh["gold_gloss"] == "mirth sound"
    assert laugh["predicted_gloss"] == "mirth sound"
    assert laugh["match"] is True
    assert by_key["w:better"]["predicted_gloss"] == "other"
    # legacy keys intact for old readers
    assert laugh["gold"] == "laugh#0" and laugh["key"] == "w:laugh"


def test_custom_key_var_derived_from_name():
    assert webui._key_var_for_custom_name("mine") == "MINE_API_KEY"
    assert webui._key_var_for_custom_name("my-provider") == \
        "MY_PROVIDER_API_KEY"
    assert webui._key_var_for_custom_name("avalai") == "AVALAI_API_KEY"
    # explicit legacy names still validate for old records
    assert webui._KEY_VAR_RX.match(
        webui._key_var_for_custom_name("mine") or "")


def test_provider_key_var_resolves_first_ref():
    var = webui._provider_key_var("avalai")
    assert var == provider_registry.key_ref_for("avalai")[0]
    assert webui._provider_key_var("nope-provider") == ""


def test_shared_key_helpers_roundtrip(tmp_path, monkeypatch):
    keys = tmp_path / "operator_keys.json"
    monkeypatch.setattr(webui, "OPERATOR_KEYS_PATH", str(keys))
    ok, _ = webui._store_operator_key("HELPER_TEST_KEY", "helper-secret-123")
    assert ok is True
    assert "HELPER_TEST_KEY" in webui.operator_key_names()
    assert webui._remove_operator_key("HELPER_TEST_KEY") is True
    assert webui._remove_operator_key("HELPER_TEST_KEY") is False


def test_api_provider_key_endpoints(tmp_path, monkeypatch):
    keys = tmp_path / "operator_keys.json"
    monkeypatch.setattr(webui, "OPERATOR_KEYS_PATH", str(keys))
    client = webui.app.test_client()
    secret = "provider-secret-value-123456789"
    # unknown provider -> 404, nothing stored
    assert client.post("/api/providers/nope/key",
                       json={"key_value": secret}).status_code == 404
    assert client.delete("/api/providers/nope/key").status_code == 404
    # empty value -> 400, nothing stored
    assert client.post("/api/providers/avalai/key",
                       json={"key_value": ""}).status_code == 400
    # save under the first configured key var, names only back
    resp = client.post("/api/providers/avalai/key",
                       json={"key_value": secret})
    assert resp.status_code == 200
    assert resp.get_json() == {"stored": "avalai"}
    var = webui._provider_key_var("avalai")
    stored = json.loads(keys.read_text(encoding="utf-8"))
    assert var in stored and secret not in json.dumps(stored)
    body = client.get("/api/providers").get_data(as_text=True)
    assert secret not in body
    avalai = [r for r in client.get("/api/providers").get_json()["providers"]
              if r["name"] == "avalai"][0]
    assert avalai["has_key"] is True
    # delete resolves the same var; second delete -> 404
    assert client.delete("/api/providers/avalai/key").status_code == 200
    assert client.delete("/api/providers/avalai/key").status_code == 404


def test_api_custom_create_with_key_value_autoderives(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "PROFILES_DIR", str(tmp_path / "profiles"))
    keys = tmp_path / "operator_keys.json"
    monkeypatch.setattr(webui, "OPERATOR_KEYS_PATH", str(keys))
    client = webui.app.test_client()
    secret = "custom-secret-value-123456789"
    resp = client.post("/api/custom_providers", json={
        "name": "unified", "base_url": "https://x.example/v1",
        "model": "m", "key_value": secret})
    assert resp.status_code == 200
    rec = resp.get_json()["profile"]
    assert rec["key_var"] == "UNIFIED_API_KEY"
    stored = json.loads(keys.read_text(encoding="utf-8"))
    assert stored.get("UNIFIED_API_KEY", "").startswith("v1:")
    assert secret not in json.dumps(stored)
    rows = client.get("/api/custom_providers").get_json()["custom"]
    assert [r for r in rows if r["name"] == "unified"][0]["has_key"] is True
    # legacy explicit key_var still honored (old records keep working)
    resp = client.post("/api/custom_providers", json={
        "name": "legacy", "base_url": "https://x.example/v1",
        "key_var": "LEGACY_EXPLICIT_KEY", "model": ""})
    assert resp.status_code == 200
    assert resp.get_json()["profile"]["key_var"] == "LEGACY_EXPLICIT_KEY"
    # profile without a pasted key still saves (derived ref, missing pill)
    resp = client.post("/api/custom_providers", json={
        "name": "nokey", "base_url": "https://x.example/v1", "model": ""})
    assert resp.status_code == 200
    assert resp.get_json()["profile"]["key_var"] == "NOKEY_API_KEY"


def test_api_generic_keys_stay_thin_wrappers(tmp_path, monkeypatch):
    keys = tmp_path / "operator_keys.json"
    monkeypatch.setattr(webui, "OPERATOR_KEYS_PATH", str(keys))
    client = webui.app.test_client()
    secret = "wrapper-secret-value-123456789"
    resp = client.post("/api/keys", json={"key_var": "WRAPPER_TEST_KEY",
                                          "key_value": secret})
    assert resp.status_code == 200
    assert client.delete("/api/keys/WRAPPER_TEST_KEY").status_code == 200


def test_api_paths_echo_and_sample_validate(tmp_path):
    client = webui.app.test_client()
    good = tmp_path / "good.json"
    good.write_text(json.dumps([{"kind": "word", "text": "laugh"}]),
                    encoding="utf-8")
    resp = client.get("/api/sample/validate", query_string={"path": str(good)})
    assert resp.get_json()["ok"] is True
    resp = client.get("/api/sample/validate",
                      query_string={"path": str(tmp_path / "missing.json")})
    assert resp.get_json()["ok"] is False
    resp = client.get("/api/paths", query_string={"sample": str(good)})
    body = resp.get_json()
    assert body["sample_ok"] is True and body["rows"] == 1
    assert body["out"].endswith("precard.jsonl")
    assert "/preview" in body["run_dir"] or "preview" in body["run_dir"]
