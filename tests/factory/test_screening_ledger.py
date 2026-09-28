"""T03 — screened_registry.jsonl ledger + fresh/duplicate preview (ADD-10).

Locked rule: registry at ``<DATA_ROOT>/screened_registry.jsonl`` (W
root via ``data_root()`` — no second resolver). Preview is read-only,
never mutates. Default run processes fresh-only; duplicates need
explicit ``reprocess_duplicates:true``. Registry write is best-effort
(never fails a successful export). Lemma identity is exact lowercase
match (documented, not fuzzy).

Hermetic: fake screen_fn, tmp data root, Flask test client with fake
children. No Kaikki, no network, no secret values.
"""

import json
import os
import sys
import threading

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.linking import export_screened as export
from factory.webui import server as webui


def _fake_screen_fn(senses, lemma=None):
    return [{"sense_id": "%s#1" % lemma}], [], {}


@pytest.fixture()
def _idle_screening():
    def _reset():
        with webui._SCREENING_LOCK:
            webui._SCREENING.update(
                proc=None, pid=None, status="idle", words=[],
                out_dir="", started=None, started_iso=None,
                exit_code=None, log=[], manifest=None, note="")

    _reset()
    yield
    _reset()


class _FakeProc:
    pid = 4242

    def __init__(self, lines=(), code=0):
        self.stdout = iter(list(lines))
        self._code = code
        self._done = threading.Event()
        self._done.set()

    def poll(self):
        return self._code if self._done.is_set() else None

    def wait(self, timeout=None):
        return self._code


def test_export_appends_registry_best_effort(tmp_path, monkeypatch):
    """Export twice → registry holds both runs; failure never breaks export."""
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", str(tmp_path))
    out = str(tmp_path / "screened")
    export.export_words(["run"], out, index={}, raw_path=str(tmp_path),
                        screen_fn=_fake_screen_fn)
    export.export_words(["run", "take"], out, index={},
                        raw_path=str(tmp_path), screen_fn=_fake_screen_fn)
    reg = tmp_path / "screened_registry.jsonl"
    rows = [json.loads(line) for line in
            reg.read_text(encoding="utf-8").splitlines()]
    assert [r["lemma"] for r in rows] == ["run", "run", "take"]
    assert all(r["run_id"] and r["created_at"] and r["out_dir"]
               for r in rows)
    # Best-effort: an unwritable root never fails the export.
    monkeypatch.setattr(export, "registry_path",
                        lambda *a, **k: "/proc/nope/registry.jsonl")
    manifest = export.export_words(["get"], out, index={},
                                   raw_path=str(tmp_path),
                                   screen_fn=_fake_screen_fn)
    assert manifest["kept_total"] == 1


def test_preview_partitions_and_run_filters(tmp_path, monkeypatch,
                                            _idle_screening):
    """Second preview shows fresh/dup split; default run skips dups."""
    import subprocess as _sub

    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", str(tmp_path))
    out = str(tmp_path / "screened")
    export.export_words(["run", "take"], out, index={},
                        raw_path=str(tmp_path), screen_fn=_fake_screen_fn)
    monkeypatch.setattr(_sub, "Popen", lambda argv, **kw: _FakeProc())
    client = webui.app.test_client()

    preview = client.get("/api/screening/ledger_preview",
                         query_string={"words": "run,take,get,make"})
    assert preview.status_code == 200
    payload = preview.get_json()
    assert payload["fresh"] == ["get", "make"]
    assert payload["duplicate"] == ["run", "take"]
    assert payload["fresh_count"] == 2 and payload["dup_count"] == 2

    # Default run processes fresh-only (argv carries 3 fresh words).
    holder = {}
    monkeypatch.setattr(
        _sub, "Popen",
        lambda argv, **kw: holder.setdefault("argv", list(argv))
        or _FakeProc())
    resp = client.post("/api/screening/run",
                       json={"words": "run,take,get,make,light"})
    assert resp.status_code == 201
    argv = holder["argv"]
    assert argv[argv.index("--words") + 1] == "get,make,light"
    with webui._SCREENING_LOCK:
        webui._SCREENING.update(proc=None, status="idle", started=None,
                                started_iso=None)

    # Explicit reprocess flag includes duplicates.
    holder.clear()
    resp = client.post("/api/screening/run",
                       json={"words": "run,take",
                             "reprocess_duplicates": True})
    assert resp.status_code == 201
    argv = holder["argv"]
    assert argv[argv.index("--words") + 1] == "run,take"


def test_missing_registry_means_all_fresh(tmp_path, monkeypatch,
                                          _idle_screening):
    """Missing registry → preview all fresh; run proceeds unfiltered."""
    import subprocess as _sub

    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(_sub, "Popen", lambda argv, **kw: _FakeProc())
    client = webui.app.test_client()
    payload = client.get("/api/screening/ledger_preview",
                         query_string={"words": "run,take"}).get_json()
    assert payload["fresh"] == ["run", "take"]
    assert payload["duplicate"] == []
    assert client.post("/api/screening/run",
                       json={"words": "run,take"}).status_code == 201
