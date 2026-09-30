"""arbiter_jobs unit tests (no threads except abort flow).

Pins: restart-honesty (persisted running reads back interrupted),
traversal-safe ids, worker-crash → failed (fail_job wired).
"""

from __future__ import annotations

import json
import os
import threading
import time

from factory.webui import arbiter_jobs as _jobs


import pytest as _pytest


@_pytest.fixture(autouse=True)
def _isolated_jobs():
    """In-memory jobs never leak across tests sharing this worker."""
    _jobs.reset_for_tests()
    yield
    _jobs.reset_for_tests()


def _root(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    os.makedirs(root)
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", root)
    return root


def _write_status(run_id, doc, root):
    base = os.path.join(root, "webui", "arbiter_runs", run_id)
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "status.json"), "w",
              encoding="utf-8") as handle:
        json.dump(doc, handle)


def test_restart_running_reads_interrupted(tmp_path, monkeypatch):
    root = _root(tmp_path, monkeypatch)
    _write_status("gone-1", {"run_id": "gone-1", "status": "running",
                             "total": 3, "done": 1}, root)
    job = _jobs.get_job("gone-1")
    assert job["status"] == "interrupted"
    assert "restart" in (job.get("error") or "")
    assert _jobs.request_abort("gone-1") is False


def test_traversal_ids_refused(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    assert _jobs.get_job("..") is None
    assert _jobs.load_verdicts("../x") == []
    assert _jobs.request_abort("..") is False
    _jobs.fail_job("../../evil", "x")
    assert not os.path.exists(
        os.path.join(str(tmp_path), "evil"))


def test_worker_crash_marks_failed(tmp_path, monkeypatch):
    import factory.linking.arbiter_runner as _runner

    _root(tmp_path, monkeypatch)
    monkeypatch.setattr(_runner, "run_arbiter",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("boom")))
    run_id = _jobs.launch({"name": "p", "model": "m"},
                          [{"sense_id": "s#0"}], lambda prompt: "{}")
    deadline = time.time() + 15
    while time.time() < deadline:
        job = _jobs.get_job(run_id)
        if job and job["status"] in ("done", "failed", "aborted"):
            break
        time.sleep(0.05)
    assert _jobs.get_job(run_id)["status"] == "failed"
    assert "boom" in (_jobs.get_job(run_id).get("error") or "")


def test_abort_flow_still_works(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    gate = threading.Event()

    def _slow(prompt):
        assert gate.wait(timeout=15)
        return ('{"verdict": "NONE", "winner_index": null, '
                '"kaikki_evidence": "", "wordnet_evidence": ""}')

    run_id = _jobs.launch({"name": "p", "model": "m"},
                          [{"sense_id": "s#0"}], _slow)
    assert _jobs.request_abort(run_id) is True
    gate.set()
    deadline = time.time() + 15
    while time.time() < deadline:
        if _jobs.get_job(run_id)["status"] == "aborted":
            break
        time.sleep(0.05)
    assert _jobs.get_job(run_id)["status"] == "aborted"
