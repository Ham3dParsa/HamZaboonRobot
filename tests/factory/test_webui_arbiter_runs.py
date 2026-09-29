"""P3 arbiter endpoint tests (stubbed transports, isolated data root).

Locked R1–R5: detached run + poll/abort; senses from configured
screened file (+ids/limit); preset NAME resolved server-side; verdicts
JSONL beside the run; needs_review surfaced (never auto-labeled).
"""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

from factory.webui import server as webui


def _write_screened(path, n=6):
    with open(path, "w", encoding="utf-8") as handle:
        for i in range(n):
            handle.write(json.dumps({
                "lemma": "run", "sense": {
                    "sense_id": "run#%d" % i, "id": "en-run-%d" % i,
                    "glosses": ["move fast"],
                    "examples": [{"text": "run fast"}],
                    "tags": ["verb"]}}) + "\n")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    os.makedirs(root)
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", root)
    screened = str(tmp_path / "screened.jsonl")
    _write_screened(screened)
    monkeypatch.setenv("HAMZABAN_SCREENED_PATH", screened)
    return {"client": webui.app.test_client(), "root": root}


class _StubAdapter:
    def __init__(self, answer=None, block=None):
        self._answer = answer or (
            '{"verdict": "NONE", "winner_index": null, '
            '"kaikki_evidence": "move", "wordnet_evidence": ""}')
        self._block = block

    def execute_arbitration(self, prompt):
        if self._block is not None:
            assert self._block.wait(timeout=30)
        return self._answer


def _preset_payload(name="t3-preset"):
    return {"name": name, "kind": "judge", "provider": "stub-local",
            "model": "stub-m", "version": 1}


def _save_preset(client, payload):
    presets = os.path.join(os.environ["HAMZABAN_DATA_ROOT"], "webui",
                           "presets")
    os.makedirs(presets, exist_ok=True)
    with open(os.path.join(presets, payload["name"] + ".json"),
              "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _wait_done(client, run_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/api/arbiter/runs/%s" % run_id).get_json()
        if body["run"]["status"] in ("done", "failed", "aborted"):
            return body["run"]
        time.sleep(0.05)
    raise AssertionError("run never settled: %s" % run_id)


def test_create_run_poll_verdicts(env, monkeypatch):
    _save_preset(env["client"], _preset_payload())
    monkeypatch.setattr(webui, "_arbiter_transport_for",
                        lambda _preset: _StubAdapter())
    created = env["client"].post(
        "/api/arbiter/runs",
        json={"preset": "t3-preset", "limit": 4}).get_json()
    run_id = created["run"]["run_id"]
    assert created["run"]["status"] == "running"
    job = _wait_done(env["client"], run_id)
    assert job["status"] == "done"
    assert job["done"] == 4 and job["abstained"] == 0
    verdicts = env["client"].get(
        "/api/arbiter/runs/%s/verdicts" % run_id).get_json()["verdicts"]
    assert len(verdicts) == 4
    assert all(v["model"] == "stub-m" for v in verdicts)


def test_create_unknown_preset_404(env):
    resp = env["client"].post("/api/arbiter/runs",
                              json={"preset": "no-such-preset"})
    assert resp.status_code == 404


def test_create_untrusted_provider_refused(env):
    created = env["client"].post(
        "/api/managed_providers",
        json={"name": "evil-prov", "protocol": "openai_compat",
              "base_url": "https://evil.example/v1", "route": "direct",
              "kind": "cloud", "key_vars": []})
    assert created.status_code == 200, created.get_json()
    _save_preset(env["client"], {"name": "t3-evil", "kind": "judge",
                                 "provider": "evil-prov",
                                 "model": "evil-m", "version": 1})
    resp = env["client"].post("/api/arbiter/runs",
                              json={"preset": "t3-evil"})
    assert resp.status_code == 400
    assert "trust" in resp.get_json()["error"]


def test_abort_run(env, monkeypatch):
    _save_preset(env["client"], _preset_payload())
    gate = threading.Event()
    monkeypatch.setattr(webui, "_arbiter_transport_for",
                        lambda _preset: _StubAdapter(block=gate))
    run_id = env["client"].post(
        "/api/arbiter/runs",
        json={"preset": "t3-preset", "limit": 3}).get_json()["run"]["run_id"]
    assert env["client"].post(
        "/api/arbiter/runs/%s/abort" % run_id).status_code == 200
    gate.set()
    job = _wait_done(env["client"], run_id)
    assert job["status"] == "aborted"


def test_unknown_run_404(env):
    assert env["client"].get("/api/arbiter/runs/nope").status_code == 404
    assert env["client"].post(
        "/api/arbiter/runs/nope/abort").status_code == 404
