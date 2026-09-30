"""Arbiter cost guards tests (isolated data root, frozen clock).

Locked: fail-fast quota (hour/day by scope) before create; single-flight
(one running run); per-run ceiling; precise per provider/model/address/
account stats; 0 cap means unlimited. No sleeping in tests — minute
pacing is verified through summarize math, not wall time.
"""

from __future__ import annotations

import datetime
import os

import pytest

from factory.webui import arbiter_jobs as _jobs


def _now():
    return datetime.datetime(2026, 9, 28, 12, 0, 0,
                             tzinfo=datetime.timezone.utc)


def _rec(minutes_ago=0, days_ago=0, **kw):
    ts = _now() - datetime.timedelta(minutes=minutes_ago,
                                     days=days_ago)
    rec = {"ts": ts.isoformat(), "provider": "p", "model": "m",
           "endpoint": "e", "key_var": "K", "preset": "pp",
           "run_id": "r"}
    rec.update(kw)
    return rec


def test_scope_keys():
    assert _jobs.scope_key("model", provider="p", model="m",
                           endpoint="e", key_var="K") == ("model", "m")
    assert _jobs.scope_key("address", provider="p", model="m",
                           endpoint="e", key_var="K") == ("address", "e")
    assert _jobs.scope_key("account", provider="p", model="m",
                           endpoint="e", key_var="K") == ("account", "K")
    assert _jobs.scope_key("bogus", provider="p", model="m",
                           endpoint="e", key_var="K") == ("model", "m")


def test_summarize_windows():
    recs = [_jobs._to_record(_rec(minutes_ago=0)),
            _jobs._to_record(_rec(minutes_ago=30)),
            _jobs._to_record(_rec(minutes_ago=90)),
            _jobs._to_record(_rec(days_ago=1)),
            _jobs._to_record(_rec(days_ago=3))]
    out = _jobs.summarize(
        [r for r in recs if r is not None], _now())
    got = out[("model", "m")]
    assert got == {"minute": 1, "hour": 2, "day": 3}


def test_quota_remaining_zero_means_unlimited():
    recs = [_jobs._to_record(_rec()) for _ in range(100)]
    recs = [r for r in recs if r is not None]
    assert _jobs.quota_remaining(
        {"max_rph": 0, "max_daily": 0}, ("model", "m"), recs,
        _now()) == {"hour": None, "day": None}


def test_quota_remaining_counts():
    recs = [_jobs._to_record(_rec(minutes_ago=i)) for i in range(5)]
    recs = [r for r in recs if r is not None]
    assert _jobs.quota_remaining(
        {"max_rph": 10, "max_daily": 10}, ("model", "m"), recs,
        _now()) == {"hour": 5, "day": 5}


def test_single_flight_second_launch_conflicts(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    os.makedirs(root)
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", root)
    _jobs.reset_for_tests()
    import threading

    gate = threading.Event()
    slow = lambda prompt: (gate.wait(timeout=30), '{"verdict": "NONE", "winner_index": null, "kaikki_evidence": "", "wordnet_evidence": ""}')[1]
    run_id = _jobs.launch({"name": "p", "model": "m"},
                          [{"sense_id": "s#0"}], slow)
    try:
        with pytest.raises(_jobs.ConflictError):
            _jobs.launch({"name": "p", "model": "m"},
                         [{"sense_id": "s#1"}], slow)
    finally:
        gate.set()
        _jobs.request_abort(run_id)
        gate.set()
        # Settle + reset so no running job leaks into later tests that
        # share this worker process (same reason webui suites reset).
        import time as _time

        deadline = _time.time() + 15
        while _time.time() < deadline:
            job = _jobs.get_job(run_id)
            if job is None or job.get("status") != "running":
                break
            _time.sleep(0.05)
        _jobs.reset_for_tests()


def test_run_ceiling_clamps(tmp_path, monkeypatch):
    root = str(tmp_path / "data")
    os.makedirs(root)
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", root)
    _jobs.reset_for_tests()
    assert _jobs.ARBITER_RUN_MAX == 100
    senses = [{"sense_id": "s#%d" % i} for i in range(250)]
    run_id = _jobs.launch(
        {"name": "p", "model": "m"}, senses,
        lambda prompt: ('{"verdict": "NONE", "winner_index": null, '
                        '"kaikki_evidence": "", "wordnet_evidence": ""}'))
    job = _jobs.get_job(run_id)
    assert job["requested"] == 250
    assert job["total"] == 100
    # Settle + reset: the 100-sense worker outlives the assertions and
    # must not leak a running job into later tests sharing this worker.
    import time as _time

    deadline = _time.time() + 30
    while _time.time() < deadline:
        job = _jobs.get_job(run_id)
        if job is None or job.get("status") != "running":
            break
        _time.sleep(0.05)
    _jobs.reset_for_tests()
