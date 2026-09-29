"""Detached arbiter-run jobs (P3): threads + status + verdicts file.

Owns NOTHING about providers or keys (the route layer resolves the
preset and builds the transport via existing seams) and NOTHING about
prompt wording (the runner owns that). This module only tracks runs:

- ``launch(preset, senses, transport)`` spawns a daemon thread and
  returns the job id immediately (never blocks the HTTP worker).
- progress (``done``/``abstained``) lives in memory and in
  ``status.json`` beside the verdicts; ``get_job`` falls back to disk
  so a restarted console still reports the last persisted state.
- abort is cooperative (checked between senses); partial verdicts stay
  on disk and remain replayable.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import uuid

_JOBS = {}
_ABORTS = set()
_LOCK = threading.Lock()

_RUN_ID_RX = None


def _run_id_ok(run_id):
    """Strict run-id shape (timestamp-hex); rejects traversal junk."""
    import re

    global _RUN_ID_RX
    if _RUN_ID_RX is None:
        _RUN_ID_RX = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
    return bool(_RUN_ID_RX.match(str(run_id or "")))


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _resolve_root(data_root=None):
    if isinstance(data_root, str) and data_root.strip():
        return data_root.strip()
    from factory.core.env_loader import data_root as _root

    return _root()


def runs_base(data_root=None):
    """``<data_root>/webui/arbiter_runs`` (created on launch)."""
    return os.path.join(_resolve_root(data_root), "webui", "arbiter_runs")


def _paths(run_id, data_root=None):
    base = os.path.join(runs_base(data_root), str(run_id))
    return base, os.path.join(base, "status.json"), os.path.join(
        base, "verdicts.jsonl")


def _write_status(base, job):
    try:
        with open(os.path.join(base, "status.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=1)
    except OSError:
        pass


def launch(preset, senses, transport, data_root=None):
    """Start a detached run; return the job id (status ``running``)."""
    run_id = "%s-%s" % (datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:6])
    base, _status_path, _verdicts_path = _paths(run_id, data_root)
    os.makedirs(base, exist_ok=True)
    job = {"run_id": run_id,
           "preset": str((preset or {}).get("name") or ""),
           "provider": str((preset or {}).get("provider") or ""),
           "model": str((preset or {}).get("model") or ""),
           "status": "running", "started_at": _stamp(),
           "total": len(senses or []), "done": 0, "abstained": 0,
           "error": ""}
    with _LOCK:
        _JOBS[run_id] = job
    _write_status(base, job)
    thread = threading.Thread(
        target=_worker,
        args=(run_id, preset or {}, list(senses or []), transport,
              data_root),
        daemon=True)
    thread.start()
    return run_id


def _worker(run_id, preset, senses, transport, data_root):
    from factory.linking import arbiter_runner as _runner

    base, _status_path, verdicts_path = _paths(run_id, data_root)
    try:
        with open(verdicts_path, "w", encoding="utf-8"):
            pass
    except OSError:
        pass
    for sense in senses:
        with _LOCK:
            if run_id in _ABORTS:
                _settle(run_id, base, "aborted")
                return
        try:
            records = _runner.run_arbiter([sense], preset, transport)
        except Exception as exc:
            fail_job(run_id, "worker: %s: %s" % (type(exc).__name__, exc),
                     data_root)
            return
        written = 0
        try:
            with open(verdicts_path, "a", encoding="utf-8") as handle:
                for rec in records:
                    handle.write(json.dumps(rec, ensure_ascii=False)
                                 + "\n")
                    written += 1
        except OSError:
            pass
        with _LOCK:
            job = _JOBS.get(run_id)
            if job is None:
                return
            job["done"] = int(job.get("done", 0)) + written
            job["abstained"] = int(job.get("abstained", 0)) + sum(
                1 for rec in records[:written] if rec.get("needs_review"))
            _write_status(base, job)
    with _LOCK:
        _settle(run_id, base, "done")


def _settle(run_id, base, status, error=""):
    job = _JOBS.get(run_id)
    if job is None:
        return
    job["status"] = status
    if error:
        job["error"] = error
    _write_status(base, job)
    _ABORTS.discard(run_id)


def fail_job(run_id, error, data_root=None):
    """Mark a run failed (worker-level catch-all path)."""
    if not _run_id_ok(run_id):
        return
    base, _s, _v = _paths(run_id, data_root)
    with _LOCK:
        _settle(run_id, base, "failed", error)


def request_abort(run_id):
    """Ask a running job to stop after the current sense."""
    if not _run_id_ok(run_id):
        return False
    with _LOCK:
        if run_id not in _JOBS:
            return False
        if _JOBS[run_id].get("status") != "running":
            return False
        _ABORTS.add(run_id)
        return True


def get_job(run_id, data_root=None):
    """Live job, else last persisted status, else None.

    A persisted ``running`` with no live worker (console restarted
    mid-run) reads back as ``interrupted`` — never a forever-running
    lie. The file itself is untouched (audit trail).
    """
    name = str(run_id or "")
    if not _run_id_ok(name):
        return None
    with _LOCK:
        job = _JOBS.get(name)
        if job is not None:
            return dict(job)
    base, status_path, _verdicts = _paths(name, data_root)
    try:
        with open(status_path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    if str(doc.get("status") or "") == "running":
        doc = dict(doc)
        doc["status"] = "interrupted"
        doc["error"] = ("console restarted mid-run; worker gone "
                        "(verdicts written so far are kept)")
    return doc


def list_jobs(data_root=None):
    """Live jobs overlaid on persisted run dirs (memory wins)."""
    with _LOCK:
        live = {run_id: dict(job) for run_id, job in _JOBS.items()}
    try:
        names = sorted(os.listdir(runs_base(data_root)))
    except OSError:
        names = []
    out = []
    seen = set()
    for name in names:
        if not _run_id_ok(name):
            continue
        if name in live:
            out.append(live[name])
        else:
            doc = get_job(name, data_root)
            if isinstance(doc, dict):
                out.append(doc)
        seen.add(name)
    for run_id, job in live.items():
        if run_id not in seen:
            out.append(job)
    return out


def load_verdicts(run_id, data_root=None):
    """Verdict records written so far (``[]`` when none yet)."""
    if not _run_id_ok(run_id):
        return []
    _base, _status, verdicts_path = _paths(run_id, data_root)
    out = []
    try:
        with open(verdicts_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out
