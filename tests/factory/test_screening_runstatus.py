"""T04 — run-status disk file + reconnect (UX-20, OQ-8).

Locked rule: ``factory/webui/run_status.py`` owns
``<DATA_ROOT>/webui/<cabin>_run_status.json``
(``{run_id, pid, started_iso, out_dir, out_name, words_hash,
status}``); written on spawn, updated on settle, atomic tmp+replace
with fsync. ``GET /api/screening/status`` merges disk state when no
in-memory proc exists (refresh/restart → same run_id, log tail +
progress recovered from out_dir). PID is a liveness probe only.

Hermetic: tmp data root, Flask test client, fake children plus one
real short-lived sleep process for the liveness probe. No network, no
secrets. The "kill -9 server proc" case is simulated by wiping the
in-memory record (a dead server process keeps no memory) while the
child + disk file survive — a fresh snapshot must read disk state.
"""

import hashlib
import json
import os
import subprocess as _subprocess
import sys
import threading

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import run_status as store
from factory.webui import server as webui


@pytest.fixture()
def _roots(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture()
def _idle_screening():
    def _reset():
        with webui._SCREENING_LOCK:
            webui._SCREENING.update(
                proc=None, pid=None, status="idle", words=[],
                out_dir="", started=None, started_iso=None,
                run_id=None, words_hash=None,
                exit_code=None, log=[], manifest=None, note="")

    _reset()
    yield
    _reset()


class _FakeProc:
    pid = 4242

    def __init__(self, lines=(), code=0, done=True):
        self.stdout = iter(list(lines))
        self._code = code
        self._done = threading.Event()
        if done:
            self._done.set()

    def poll(self):
        return self._code if self._done.is_set() else None

    def wait(self, timeout=None):
        self._done.wait(timeout)
        return self._code


def _words_hash(words):
    return hashlib.sha256(",".join(words).encode("utf-8")).hexdigest()[:16]


def test_store_write_read_roundtrip(_roots):
    """Spawn-shaped record persists with fsync; read returns it verbatim."""
    record = {"run_id": "abc123", "pid": 4242,
              "started_iso": "2026-09-27T00:00:00+00:00",
              "out_dir": str(_roots / "screened"), "out_name": "screened",
              "words_hash": "deadbeef", "status": "running"}
    stored = store.write(str(_roots), "screening", record)
    assert stored == record
    path = _roots / "webui" / "screening_run_status.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == record
    assert store.read(str(_roots), "screening") == record
    assert store.status_path(str(_roots), "screening") == str(path)


def test_second_cabin_no_crosstalk(_roots):
    """A second cabin key lands in its own file; screening is untouched."""
    store.write(str(_roots), "screening",
                {"run_id": "s1", "status": "running"})
    store.write(str(_roots), "probe-cabin",
                {"run_id": "p9", "status": "completed"})
    assert store.read(str(_roots), "screening")["run_id"] == "s1"
    assert store.read(str(_roots), "probe-cabin")["run_id"] == "p9"
    assert (_roots / "webui" / "probe-cabin_run_status.json").is_file()
    # Settling the probe cabin never touches screening.
    store.write(str(_roots), "probe-cabin",
                {"run_id": "p9", "status": "failed"})
    assert store.read(str(_roots), "screening")["status"] == "running"


def test_corrupt_missing_and_unsafe(_roots):
    """Missing/corrupt reads as None; unsafe cabins and bad records fail."""
    assert store.read(str(_roots), "screening") is None
    (_roots / "webui").mkdir(parents=True)
    (_roots / "webui" / "screening_run_status.json").write_text(
        "{broken", encoding="utf-8")
    assert store.read(str(_roots), "screening") is None
    (_roots / "webui" / "screening_run_status.json").write_text(
        "[1,2]", encoding="utf-8")
    assert store.read(str(_roots), "screening") is None
    with pytest.raises(ValueError):
        store.status_path(str(_roots), "../escape")
    with pytest.raises(ValueError):
        store.write(str(_roots), "screening", {"status": "running"})
    with pytest.raises(ValueError):
        store.write(str(_roots), "", {"run_id": "x"})


def test_spawn_writes_running_status(_roots, _idle_screening, monkeypatch):
    """POST /api/screening/run → disk file holds running + identity."""
    monkeypatch.setattr(_subprocess, "Popen",
                        lambda argv, **kw: _FakeProc(done=False))
    client = webui.app.test_client()
    resp = client.post("/api/screening/run",
                       json={"words": "run,take",
                             "reprocess_duplicates": True})
    assert resp.status_code == 201
    body = resp.get_json()["screening"]
    assert body["run_id"]
    file_rec = store.read(str(_roots), "screening")
    assert file_rec["status"] == "running"
    assert file_rec["run_id"] == body["run_id"]
    assert file_rec["pid"] == 4242
    assert file_rec["started_iso"] == body["started_iso"]
    assert file_rec["out_dir"] == body["out_dir"]
    assert file_rec["out_name"] == os.path.basename(body["out_dir"])
    assert file_rec["words_hash"] == _words_hash(["run", "take"])
    with webui._SCREENING_LOCK:
        webui._SCREENING["proc"]._done.set()


def test_settle_updates_disk_file(_roots, _idle_screening, monkeypatch):
    """Exited child settles the disk file on the next status read."""
    proc = _FakeProc(lines=["kept=1 dropped=0"], code=0)
    monkeypatch.setattr(_subprocess, "Popen",
                        lambda argv, **kw: proc)
    client = webui.app.test_client()
    assert client.post("/api/screening/run",
                       json={"words": "run",
                             "reprocess_duplicates": True}).status_code == 201
    payload = client.get("/api/screening/status").get_json()["screening"]
    assert payload["status"] == "completed"
    assert store.read(str(_roots), "screening")["status"] == "completed"


def test_restart_recovers_running_state(_roots, _idle_screening):
    """Dead server memory + live child + disk file → same run resumes.

    Simulates ``kill -9`` on the console process: the in-memory record
    is wiped (a dead process keeps no memory) while the child (a real
    short sleep, so the pid probe is genuinely alive) and the T04 file
    survive. A fresh snapshot must return the SAME run_id as running
    with ``resumed: true``; killing the child then settles to failed
    (no manifest in out_dir) and the disk file follows.
    """
    sleeper = _subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        out_dir = str(_roots / "screened")
        os.makedirs(out_dir, exist_ok=True)
        record = {"run_id": "run-live-1", "pid": sleeper.pid,
                  "started_iso": "2026-09-27T00:00:01+00:00",
                  "out_dir": out_dir, "out_name": "screened",
                  "words_hash": "abc", "status": "running"}
        store.write(str(_roots), "screening", record)
        client = webui.app.test_client()
        snap = client.get("/api/screening/status").get_json()["screening"]
        assert snap["run_id"] == "run-live-1"
        assert snap["status"] == "running"
        assert snap["resumed"] is True
        assert snap["started_iso"] == "2026-09-27T00:00:01+00:00"
        assert snap["out_dir"] == out_dir
        # The dead child settles honestly: no manifest → failed.
        sleeper.kill()
        sleeper.wait(timeout=10)
        snap = client.get("/api/screening/status").get_json()["screening"]
        assert snap["run_id"] == "run-live-1"
        assert snap["status"] == "failed"
        assert store.read(str(_roots), "screening")["status"] == "failed"
    finally:
        try:
            sleeper.kill()
        except OSError:
            pass


def test_completed_manifest_recovered_from_out_dir(
        _roots, _idle_screening):
    """Dead pid + manifest in out_dir → completed with totals + log tail."""
    out_dir = str(_roots / "screened")
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"kept_total": 2, "dropped_total": 1, "per_lemma": [],
                "words": ["run"]}
    with open(os.path.join(out_dir, "screened.manifest.json"), "w",
              encoding="utf-8") as handle:
        json.dump(manifest, handle)
    with open(os.path.join(out_dir, "screening.log"), "w",
              encoding="utf-8") as handle:
        handle.write("kept=2 dropped=1 out=%s\n" % out_dir)
    store.write(str(_roots), "screening",
                {"run_id": "run-done-7", "pid": 1,
                 "started_iso": "2026-09-27T00:00:02+00:00",
                 "out_dir": out_dir, "out_name": "screened",
                 "words_hash": "abc", "status": "running"})
    client = webui.app.test_client()
    snap = client.get("/api/screening/status").get_json()["screening"]
    assert snap["run_id"] == "run-done-7"
    assert snap["status"] == "completed"
    assert snap["resumed"] is True
    assert snap["manifest"]["kept_total"] == 2
    assert snap["manifest"]["dropped_total"] == 1
    assert snap["log"] == ["kept=2 dropped=1 out=%s" % out_dir]
    assert store.read(str(_roots), "screening")["status"] == "completed"
