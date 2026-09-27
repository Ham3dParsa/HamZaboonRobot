"""W1 wake-on-down-probe + W2 screening export routes (backend only).

Behavior spec (locked W1+W2):
- R1: a resolved supervisor token with a DOWN health probe (health_fn
  when injected, else the local snapshot) enters the wake branch —
  never a blind ready. An unverifiable probe (raises) keeps the old
  assume-alive path. Fakes only, never a process or the network.
- W2: POST /api/screening/run spawns
  ``python -m factory.linking.export_screened`` via Popen (fake here),
  records the PID and returns while running; GET /api/screening/status
  reports idle/running/completed/failed + elapsed + exit code + the
  single combined 100-line tail + the manifest summary on success;
  POST /api/screening/abort SIGTERMs the child with a kill fallback.

Hermetic: fakes only, no processes, no network, no secret values.
"""

import json
import os
import sys
import threading
import time

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import server as webui


# ---------------------------------------------------------------------------
# R1: wake fix — token x probe matrix through the leased gate.
# ---------------------------------------------------------------------------

def _leased(provider="google", **kwargs):
    kwargs.setdefault("tunneled", {"google": True})
    return webui._ensure_supervisor_for_leased(provider, **kwargs)


def test_wake_gate_down_probe_with_token_enters_wake_branch(monkeypatch):
    """Token + down probe: the wake leg runs (never a blind ready)."""
    calls = {"wake": 0}
    states = {"token": "tokentokentoken"}

    def fake_wake():
        calls["wake"] += 1
        return True

    monkeypatch.setattr(webui, "_supervisor_token",
                        lambda: states["token"])
    # Wake succeeds and the token still resolves -> ready, but ONLY
    # through the wake branch (wake leg ran exactly once).
    ready, error = _leased(
        wake_fn=fake_wake, health_fn=lambda: (False, {"healthy": False}))
    assert ready is True
    assert error is None
    assert calls["wake"] == 1

    # Wake runs but the supervisor is still down (no token after the
    # wake): friendly wait line, never a blind ready.
    states["token"] = "tokentokentoken"

    def fake_wake_no_issue():
        calls["wake"] += 1
        states["token"] = ""
        return True

    ready, error = _leased(
        wake_fn=fake_wake_no_issue,
        health_fn=lambda: (False, {"healthy": False}))
    assert ready is False
    assert isinstance(error, str) and "background" in error
    assert "Traceback" not in error
    assert calls["wake"] == 2


def test_wake_gate_up_probe_with_token_never_wakes(monkeypatch):
    """Token + healthy probe: ready, wake leg untouched."""
    calls = {"wake": 0}

    def fake_wake():
        calls["wake"] += 1
        return True

    monkeypatch.setattr(webui, "_supervisor_token",
                        lambda: "tokentokentoken")
    ready, error = _leased(
        wake_fn=fake_wake, health_fn=lambda: (True, {"healthy": True}))
    assert ready is True
    assert error is None
    assert calls["wake"] == 0


def test_wake_gate_unverifiable_probe_assumes_alive(monkeypatch):
    """Token + raising probe: old assume-alive path, no blind wake."""
    calls = {"wake": 0}

    def fake_wake():
        calls["wake"] += 1
        return True

    def boom():
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(webui, "_supervisor_token",
                        lambda: "tokentokentoken")
    ready, error = _leased(wake_fn=fake_wake, health_fn=boom)
    assert ready is True
    assert error is None
    assert calls["wake"] == 0


def test_wake_gate_snapshot_leg_without_injected_probe(monkeypatch):
    """No health_fn: the local snapshot is the probe (faked, no network)."""
    calls = {"wake": 0}

    def fake_wake():
        calls["wake"] += 1
        return True

    monkeypatch.setattr(webui, "_supervisor_token",
                        lambda: "tokentokentoken")
    # Snapshot says down -> wake branch runs.
    monkeypatch.setattr(webui, "supervisor_health_snapshot",
                        lambda timeout=10: (False, {"healthy": False}))
    ready, error = _leased(wake_fn=fake_wake)
    assert ready is True
    assert error is None
    assert calls["wake"] == 1
    # Snapshot raises (unverifiable) -> assume alive, no wake.
    monkeypatch.setattr(webui, "supervisor_health_snapshot", lambda: 1 / 0)
    ready, error = _leased(wake_fn=fake_wake)
    assert ready is True
    assert error is None
    assert calls["wake"] == 1


def test_tunnel_models_path_wakes_when_supervisor_down(monkeypatch):
    """Tunnel-needing lease path: token + down probe wakes, never leases.

    ``provider_model_list`` rides ``lease_tunnel_for_run``; this drives
    that same seam with a lease leg that explodes when touched — the
    wait line must arrive with the lease leg untouched and the wake
    leg run exactly once.
    """
    wakes = {"n": 0}
    leases = {"n": 0}
    states = {"token": "tokentokentoken"}

    def fake_wake():
        wakes["n"] += 1
        states["token"] = ""  # wake in flight, bearer not yet re-readable
        return True

    def exploding_lease(*args, **kwargs):
        leases["n"] += 1
        raise AssertionError("lease must not run while supervisor is down")

    monkeypatch.setattr(webui, "_supervisor_token",
                        lambda: states["token"])
    lease, error = webui.lease_tunnel_for_run(
        "google", tunneled={"google": True},
        wake_fn=fake_wake, health_fn=lambda: (False, {"healthy": False}),
        lease_fn=exploding_lease, state_log=[])
    assert lease is None
    assert isinstance(error, str) and "background" in error
    assert wakes["n"] == 1
    assert leases["n"] == 0


def test_wake_gate_no_token_path_still_wakes(monkeypatch):
    """No token: unchanged behavior — wake, then the wait line."""
    calls = {"wake": 0}

    def fake_wake():
        calls["wake"] += 1
        return True

    monkeypatch.setattr(webui, "_supervisor_token", lambda: "")
    ready, error = _leased(
        wake_fn=fake_wake, health_fn=lambda: (False, {"healthy": False}))
    assert ready is False
    assert isinstance(error, str) and "background" in error
    assert calls["wake"] == 1


# ---------------------------------------------------------------------------
# W2: screening export routes.
# ---------------------------------------------------------------------------

@pytest.fixture()
def _idle_screening():
    def _reset():
        with webui._SCREENING_LOCK:
            webui._SCREENING.update(
                proc=None, pid=None, status="idle", words=[],
                out_dir="", started=None, exit_code=None, log=[],
                manifest=None, note="")

    _reset()
    yield
    _reset()


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)


class _FakeProc:
    """Controllable child: wait() blocks until released (running leg)."""

    def __init__(self, lines=(), code=0, pid=4242, auto_done=False):
        self.stdout = _FakeStdout(lines)
        self._code = code
        self.pid = pid
        self._done = threading.Event()
        if auto_done:
            self._done.set()
        self.terminated = 0
        self.killed = 0

    def poll(self):
        return self._code if self._done.is_set() else None

    def wait(self, timeout=None):
        self._done.wait(timeout if timeout is not None else 60)
        return self._code

    def terminate(self):
        self.terminated += 1
        self._done.set()

    def kill(self):
        self.killed += 1
        self._done.set()


def _popen_factory(seen, procs):
    def _fake_popen(argv, **kwargs):
        seen["argv"] = list(argv)
        proc = _FakeProc()
        procs.append(proc)
        return proc

    return _fake_popen


def _wait_for_status(client, want, deadline_s=10.0, min_log=0):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        body = client.get("/api/screening/status").get_json()["screening"]
        if body["status"] == want and len(body["log"]) >= min_log:
            return body
        time.sleep(0.05)
    raise AssertionError("screening never reached %r" % (want,))


def test_screening_run_spawns_receipt_and_returns_running(
        tmp_path, monkeypatch, _idle_screening):
    """POST spawns the export receipt, records the PID, returns running."""
    import subprocess as _sub

    seen, procs = {}, []
    monkeypatch.setattr(_sub, "Popen", _popen_factory(seen, procs))
    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))

    client = webui.app.test_client()
    resp = client.get("/api/screening/status")
    assert resp.status_code == 200
    idle = resp.get_json()["screening"]
    assert idle["status"] == "idle"
    assert idle["elapsed"] is None
    assert idle["manifest"] is None

    resp = client.post("/api/screening/run", json={})
    assert resp.status_code == 201
    body = resp.get_json()["screening"]
    assert body["status"] == "running"
    assert body["pid"] == 4242
    assert body["exit_code"] is None
    assert isinstance(body["elapsed"], float) and body["elapsed"] >= 0.0
    assert body["words"] == ["run", "light", "take", "get", "make"]
    assert body["out_dir"] == os.path.join(
        str(tmp_path), "proof-linker", "screened")
    argv = seen["argv"]
    assert argv[:3] == [sys.executable, "-m",
                        "factory.linking.export_screened"]
    assert "--words" in argv and "--out-dir" in argv
    assert argv[argv.index("--words") + 1] == "run,light,take,get,make"

    # Second launch while in flight is refused, never double-spawned.
    resp = client.post("/api/screening/run", json={})
    assert resp.status_code == 409
    assert len(procs) == 1
    procs[0]._done.set()

    done = _wait_for_status(client, "completed")
    assert done["exit_code"] == 0


def test_screening_status_tail_and_manifest(tmp_path, monkeypatch,
                                            _idle_screening):
    """Tail keeps the last 100 merged lines; success attaches the summary."""
    import subprocess as _sub

    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    out_dir = tmp_path / "proof-linker" / "screened"
    out_dir.mkdir(parents=True)
    manifest = {"created_at": "t", "words": ["run"], "kept_total": 7,
                "dropped_total": 3,
                "per_lemma": [{"lemma": "run", "kept": 7, "dropped": 3}],
                "extra_ignored": True}
    (out_dir / "screened.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    lines = ["line-%d" % i for i in range(150)]

    holder = {}

    def _fake_popen(argv, **kwargs):
        holder["argv"] = list(argv)
        return _FakeProc(lines=lines, code=0, auto_done=True)

    monkeypatch.setattr(_sub, "Popen", _fake_popen)
    client = webui.app.test_client()
    resp = client.post("/api/screening/run",
                       json={"words": "run", "out_dir": str(out_dir)})
    assert resp.status_code == 201
    done = _wait_for_status(client, "completed", min_log=100)
    assert done["exit_code"] == 0
    assert done["words"] == ["run"]
    assert done["out_dir"] == os.path.abspath(str(out_dir))
    assert len(done["log"]) == 100
    assert done["log"][0] == "line-50"
    assert done["log"][-1] == "line-149"
    assert done["manifest"] == {"kept_total": 7, "dropped_total": 3,
                                "per_lemma": [{"lemma": "run", "kept": 7,
                                               "dropped": 3}]}


def test_screening_failed_exit_reports_code(tmp_path, monkeypatch,
                                            _idle_screening):
    """Nonzero exit settles to failed with the code and no manifest."""
    import subprocess as _sub

    def _fake_popen(argv, **kwargs):
        return _FakeProc(lines=["boom"], code=2, auto_done=True)

    monkeypatch.setattr(_sub, "Popen", _fake_popen)
    client = webui.app.test_client()
    assert client.post("/api/screening/run", json={}).status_code == 201
    done = _wait_for_status(client, "failed", min_log=1)
    assert done["exit_code"] == 2
    assert done["manifest"] is None
    assert done["log"] == ["boom"]


def test_screening_abort_sigterms_with_kill_fallback(
        tmp_path, monkeypatch, _idle_screening):
    """Abort SIGTERMs the recorded child; graceful here, so no kill."""
    import subprocess as _sub

    seen, procs = {}, []
    monkeypatch.setattr(_sub, "Popen", _popen_factory(seen, procs))
    client = webui.app.test_client()
    assert client.post("/api/screening/run", json={}).status_code == 201
    proc = procs[0]
    assert client.get("/api/screening/status").get_json(
    )["screening"]["status"] == "running"

    resp = client.post("/api/screening/abort")
    assert resp.status_code == 200
    body = resp.get_json()["screening"]
    assert proc.terminated == 1
    assert proc.killed == 0
    assert body["status"] == "failed"
    assert "abort" in body["note"]
    assert body["pid"] == 4242

    # Nothing left to stop: abort on a settled/idle job is a 409.
    resp = client.post("/api/screening/abort")
    assert resp.status_code == 409


def test_screening_abort_kill_fallback_when_child_ignores_term(
        tmp_path, monkeypatch, _idle_screening):
    """A child that ignores SIGTERM gets the kill fallback."""
    import subprocess as _sub

    class _StubbornProc(_FakeProc):
        def terminate(self):
            self.terminated += 1  # ignores SIGTERM: stays alive

        def wait(self, timeout=None):
            if self.terminated and not self.killed:
                import subprocess as _real_sub

                raise _real_sub.TimeoutExpired("fake", 5.0)
            self._done.wait(60)
            return self._code

    procs = []

    def _fake_popen(argv, **kwargs):
        proc = _StubbornProc()
        procs.append(proc)
        return proc

    monkeypatch.setattr(_sub, "Popen", _fake_popen)
    client = webui.app.test_client()
    assert client.post("/api/screening/run", json={}).status_code == 201
    body = client.post("/api/screening/abort").get_json()["screening"]
    assert procs[0].terminated == 1
    assert procs[0].killed == 1
    assert body["status"] == "failed"
    assert "abort" in body["note"]


# ---------------------------------------------------------------------------
# W3: input confinement — words validated + capped, out_dir jailed.
# ---------------------------------------------------------------------------

def test_screening_words_validated_and_capped():
    """Only [a-z-]{1,64} tokens survive; the list caps at 50."""
    assert webui._screening_parse_words("Run, LIGHT, take") == [
        "run", "light", "take"]
    assert webui._screening_parse_words(
        "run,../x,C:\\win,has space,ok-word") == ["run", "ok-word"]
    assert webui._screening_parse_words("") == [
        "run", "light", "take", "get", "make"]
    many = ",".join("z" * ((i % 60) + 1) for i in range(200))
    assert len(webui._screening_parse_words(many)) == 50


def test_screening_out_dir_escapes_rejected(tmp_path, monkeypatch,
                                            _idle_screening):
    """Absolute/traversal out_dir outside the screening root -> 400, no spawn."""
    import subprocess as _sub

    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    monkeypatch.setattr(_sub, "Popen", _popen_factory({}, []))
    client = webui.app.test_client()
    for evil in ("C:\\Windows\\Temp\\evil", "../../evil",
                 str(tmp_path.parent / "sibling-evil")):
        resp = client.post("/api/screening/run",
                           json={"words": "run", "out_dir": evil})
        assert resp.status_code == 400
        assert "escapes" in resp.get_json()["error"]
    assert client.get("/api/screening/status").get_json(
    )["screening"]["status"] == "idle"


def test_screening_out_dir_inside_root_accepted(tmp_path, monkeypatch,
                                                _idle_screening):
    """A subdir of the confined root spawns normally (abspath receipt)."""
    import subprocess as _sub

    seen, procs = {}, []
    monkeypatch.setattr(_sub, "Popen", _popen_factory(seen, procs))
    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    nested = str(tmp_path / "proof-linker" / "screened" / "custom")
    client = webui.app.test_client()
    resp = client.post("/api/screening/run",
                       json={"words": "run", "out_dir": nested})
    assert resp.status_code == 201
    assert resp.get_json()["screening"]["out_dir"] == os.path.abspath(nested)
    assert len(procs) == 1
    procs[0]._done.set()
