"""Mechanical endpoint tests (R1–R4+R7, stub-free offline, isolated root).

Locked: POST /api/mechanical/runs -> detached run with counts +
deferred_ids; GET results/log; arbiter create accepts {from_run} (R7);
arbiter verdicts enriched with gloss + candidates (bug-a fix).
"""

from __future__ import annotations

import json
import os
import time

import pytest

from factory.webui import server as webui


def _write_screened(path):
    rows = [
        ("run", "run#1", "en-run-en-verb-A1",
         "move fast on foot quickly across ground"),
        ("run", "run#2", "en-run-en-verb-A2", "An error."),
        ("bear", "bear#1", "en-bear-en-verb-B1",
         "carry heavy weight forward daily"),
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for lemma, short, full, gloss in rows:
            handle.write(json.dumps({
                "lemma": lemma, "sense": {
                    "sense_id": short, "id": full,
                    "glosses": [gloss],
                    "examples": [{"text": "ex"}],
                    "tags": []}}) + "\n")


def _write_table(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("kaikki_sense_id\twordnet_sensekey\tmethod\t"
                     "evidence\tprovenance\n")
        handle.write("en-run-en-verb-A1\trun%2:38:00::\tLINK:2-sig\t"
                     "Sa:j=0.40+Sb:fast\trules:v0\n")
        handle.write("en-run-en-verb-A2\trun%2:38:01::\tJUDGE-PENDING\t"
                     "Sa:j=0.20\trules:v0\n")
        handle.write("en-bear-en-verb-B1\tbear%2:33:00::\tJUDGE-PENDING\t"
                     "Sa:j=0.20\trules:v0\n")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from factory.webui import arbiter_jobs as _aj
    from factory.webui import mechanical_jobs as _mj

    _aj.reset_for_tests()
    _mj.reset_for_tests()
    root = str(tmp_path / "data")
    os.makedirs(root)
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", root)
    screened = str(tmp_path / "screened.jsonl")
    _write_screened(screened)
    monkeypatch.setenv("HAMZABAN_SCREENED_PATH", screened)
    table = str(tmp_path / "table.tsv")
    _write_table(table)
    monkeypatch.setenv("HAMZABAN_LINK_TABLE", table)
    yield {"client": webui.app.test_client(), "root": root}
    _aj.reset_for_tests()
    _mj.reset_for_tests()


def _wait_mech_done(client, run_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/api/mechanical/runs/%s" % run_id).get_json()
        if body["run"]["status"] in ("done", "failed", "aborted"):
            return body["run"]
        time.sleep(0.05)
    raise AssertionError("mechanical run never settled: %s" % run_id)


def test_mechanical_run_counts_and_deferred_ids(env):
    created = env["client"].post(
        "/api/mechanical/runs", json={}).get_json()
    run_id = created["run"]["run_id"]
    job = _wait_mech_done(env["client"], run_id)
    assert job["status"] == "done"
    assert job["done"] == 3
    assert job["approved"] + job["rejected"] + job["deferred"] == 3
    assert "run#2" in (job["deferred_ids"] or [])
    results = env["client"].get(
        "/api/mechanical/runs/%s/results" % run_id).get_json()["results"]
    assert len(results) == 3
    assert {r["sense_id"] for r in results} == {"run#1", "run#2", "bear#1"}
    by_id = {r["sense_id"]: r for r in results}
    assert by_id["run#1"]["verdict"] == "approved"
    assert by_id["run#2"]["verdict"] == "deferred"


def test_mechanical_single_flight_409(env):
    from factory.webui import mechanical_jobs as _mj

    _mj._JOBS["busy-1"] = {"run_id": "busy-1", "status": "running"}
    try:
        resp = env["client"].post("/api/mechanical/runs", json={})
        assert resp.status_code == 409
    finally:
        del _mj._JOBS["busy-1"]


def test_mechanical_log_tails_jsonl(env):
    run_id = env["client"].post(
        "/api/mechanical/runs", json={}).get_json()["run"]["run_id"]
    _wait_mech_done(env["client"], run_id)
    body = env["client"].get(
        "/api/mechanical/runs/%s/log?tail=5" % run_id).get_json()
    assert isinstance(body["log"], list) and body["log"]
    assert set(("ts", "level", "event", "detail")) <= set(body["log"][0])
    assert env["client"].get(
        "/api/mechanical/runs/nope/log").status_code == 404


def test_arbiter_from_run_resolves_deferred(env, monkeypatch):
    from factory.webui import mechanical_jobs as _mj

    run_id = env["client"].post(
        "/api/mechanical/runs", json={}).get_json()["run"]["run_id"]
    mech = _wait_mech_done(env["client"], run_id)
    assert mech["deferred_ids"]

    presets = os.path.join(os.environ["HAMZABAN_DATA_ROOT"], "webui",
                           "presets")
    os.makedirs(presets, exist_ok=True)
    with open(os.path.join(presets, "t3-m.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"name": "t3-m", "kind": "ai",
                   "provider": "stub-local", "model": "stub-m",
                   "version": 1}, handle)

    seen = {"prompts": 0}

    class _Stub:
        def execute_arbitration(self, prompt):
            seen["prompts"] += 1
            return ('{"verdict": "NONE", "winner_index": null, '
                    '"kaikki_evidence": "x", "wordnet_evidence": ""}')

    monkeypatch.setattr(webui, "_arbiter_transport_for",
                        lambda _preset: _Stub())
    created = env["client"].post(
        "/api/arbiter/runs",
        json={"preset": "t3-m", "from_run": run_id}).get_json()
    arb_id = created["run"]["run_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        job = env["client"].get(
            "/api/arbiter/runs/%s" % arb_id).get_json()["run"]
        if job["status"] in ("done", "failed", "aborted"):
            break
        time.sleep(0.05)
    assert job["total"] == len(mech["deferred_ids"])
    assert seen["prompts"] == len(mech["deferred_ids"])
    verdicts = env["client"].get(
        "/api/arbiter/runs/%s/verdicts" % arb_id).get_json()["verdicts"]
    assert len(verdicts) == len(mech["deferred_ids"])
    for row in verdicts:
        assert "gloss" in row and "candidates" in row
        assert isinstance(row["candidates"], list)


def test_arbiter_from_run_unknown_404(env):
    presets = os.path.join(os.environ["HAMZABAN_DATA_ROOT"], "webui",
                           "presets")
    os.makedirs(presets, exist_ok=True)
    with open(os.path.join(presets, "t3-m.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"name": "t3-m", "kind": "ai",
                   "provider": "stub-local", "model": "stub-m",
                   "version": 1}, handle)
    resp = env["client"].post(
        "/api/arbiter/runs", json={"preset": "t3-m", "from_run": "nope"})
    assert resp.status_code == 404


def test_mechanical_run_in_unified_history(env):
    run_id = env["client"].post(
        "/api/mechanical/runs", json={}).get_json()["run"]["run_id"]
    _wait_mech_done(env["client"], run_id)
    body = env["client"].get("/api/linking/history").get_json()
    rows = [r for r in body["runs"] if r["kind"] == "mechanical"
            and r["run_id"] == run_id]
    assert rows, body["runs"]
    assert set(rows[0]) >= {"kind", "run_id", "out_name", "status",
                            "created", "detail"}


def test_cli_mechanical_writes_results(tmp_path):
    from factory.linking import cli as _cli

    screened = str(tmp_path / "s.jsonl")
    _write_screened(screened)
    table = str(tmp_path / "t.tsv")
    _write_table(table)
    out = str(tmp_path / "out.jsonl")
    assert _cli.main(["mechanical", "--in", screened, "--out", out,
                      "--table", table]) == 0
    rows = [json.loads(line) for line in
            open(out, encoding="utf-8").read().splitlines()]
    assert len(rows) == 3
    assert {r["sense_id"] for r in rows} == {"run#1", "run#2", "bear#1"}
    assert {r["verdict"] for r in rows} <= {"approved", "rejected",
                                            "deferred"}


def test_arbiter_log_endpoint(env, monkeypatch):
    presets = os.path.join(os.environ["HAMZABAN_DATA_ROOT"], "webui",
                           "presets")
    os.makedirs(presets, exist_ok=True)
    with open(os.path.join(presets, "t3-l.json"), "w",
              encoding="utf-8") as handle:
        json.dump({"name": "t3-l", "kind": "ai",
                   "provider": "stub-local", "model": "stub-m",
                   "version": 1}, handle)

    class _Stub:
        def execute_arbitration(self, prompt):
            return ('{"verdict": "NONE", "winner_index": null, '
                    '"kaikki_evidence": "x", "wordnet_evidence": ""}')

    monkeypatch.setattr(webui, "_arbiter_transport_for",
                        lambda _preset: _Stub())
    run_id = env["client"].post(
        "/api/arbiter/runs",
        json={"preset": "t3-l", "limit": 1}).get_json()["run"]["run_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        job = env["client"].get(
            "/api/arbiter/runs/%s" % run_id).get_json()["run"]
        if job["status"] in ("done", "failed", "aborted"):
            break
        time.sleep(0.05)
    body = env["client"].get(
        "/api/arbiter/runs/%s/log" % run_id).get_json()
    assert body["log"] and body["log"][0]["event"] == "started"
    assert "current_sense" in job and "started_at" in job
