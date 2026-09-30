"""Detached mechanical-run jobs: threads + status + results file.

Mirrors ``arbiter_jobs.py`` patterns (single-flight, disk fallback,
cooperative abort) with zero AI cost: the worker is pure CPU over the
vendor table via ``mechanical_runner``. Each run dir holds
``status.json`` + ``results.jsonl`` + ``run_log.jsonl`` (R5 RunLog —
one owner, reused by the arbiter worker too). ``status.json`` carries
``deferred_ids`` (R7 handoff) plus ``current_sense``/``started_at`` so
the UI can tell slow from hung.
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import uuid

from factory.webui.run_log import RunLog

_JOBS = {}
_ABORTS = set()
_LOCK = threading.Lock()


class ConflictError(ValueError):
    """Another mechanical run is already active (single-flight)."""


def reset_for_tests():
    """Clear in-memory jobs (test isolation only — same-process suites)."""
    with _LOCK:
        _JOBS.clear()
        _ABORTS.clear()


_RUN_ID_RX = None


def _run_id_ok(run_id):
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
    """``<data_root>/webui/mechanical_runs`` (created on launch)."""
    return os.path.join(_resolve_root(data_root), "webui", "mechanical_runs")


def _paths(run_id, data_root=None):
    base = os.path.join(runs_base(data_root), str(run_id))
    return (base, os.path.join(base, "status.json"),
            os.path.join(base, "results.jsonl"),
            os.path.join(base, "run_log.jsonl"))


def log_path(run_id, data_root=None):
    """Append-only run log path (R5 RunLog; mirrors arbiter_jobs)."""
    base, _s, _r, _l = _paths(str(run_id or ""), data_root)
    return os.path.join(base, "run_log.jsonl")


def _write_status(base, job):
    try:
        with open(os.path.join(base, "status.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=1)
    except OSError:
        pass


def launch(senses, index, data_root=None):
    """Start a detached mechanical run; return the job id.

    Single-flight: raises ``ConflictError`` when a run is active.
    ``senses`` are sense-feed items; ``index`` is the vendor-table
    index (both injected — no I/O here beyond the run dir).
    """
    wanted = [s for s in (senses or []) if isinstance(s, dict)]
    if not wanted:
        raise ValueError("no senses selected for this run")
    with _LOCK:
        for job in _JOBS.values():
            if job.get("status") == "running":
                raise ConflictError(
                    "a mechanical run is already active "
                    "(single-flight: one at a time)")
        run_id = "%s-%s" % (datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            uuid.uuid4().hex[:6])
        base, _s, _r, _l = _paths(run_id, data_root)
        os.makedirs(base, exist_ok=True)
        job = {"run_id": run_id, "status": "running",
               "started_at": _stamp(), "current_sense": "",
               "requested": len(wanted), "total": len(wanted),
               "done": 0, "approved": 0, "rejected": 0, "deferred": 0,
               "deferred_ids": [], "error": ""}
        _JOBS[run_id] = job
        _write_status(base, job)
    RunLog(os.path.join(base, "run_log.jsonl")).append(
        "info", "started", "senses=%d" % len(wanted))
    thread = threading.Thread(
        target=_worker,
        args=(run_id, wanted, index, data_root),
        daemon=True)
    thread.start()
    return run_id


def _worker(run_id, senses, index, data_root):
    from factory.linking import mechanical_runner as _mech

    base, _s, results_path, log_path = _paths(run_id, data_root)
    log = RunLog(log_path)
    try:
        with open(results_path, "w", encoding="utf-8"):
            pass
    except OSError:
        pass
    deferred = []
    try:
        for sense in senses:
            with _LOCK:
                if run_id in _ABORTS:
                    _settle(run_id, base, "aborted")
                    log.append("warn", "aborted",
                               "after %d senses" % _done_of(run_id))
                    return
                job = _JOBS.get(run_id)
                if job is not None:
                    job["current_sense"] = str(sense.get("sense_id")
                                              or "")
                    _write_status(base, job)
            log.append("info", "sense",
                       str(sense.get("sense_id") or ""))
            records = _mech.run_mechanical([sense], index)
            try:
                with open(results_path, "a", encoding="utf-8") as handle:
                    for rec in records:
                        handle.write(json.dumps(rec, ensure_ascii=False)
                                     + "\n")
            except OSError:
                pass
            for rec in records:
                if rec.get("verdict") == "deferred":
                    deferred.append(rec.get("sense_id") or "")
            with _LOCK:
                job = _JOBS.get(run_id)
                if job is None:
                    return
                job["done"] = int(job.get("done", 0)) + len(records)
                for rec in records:
                    verdict = rec.get("verdict")
                    if verdict in ("approved", "rejected", "deferred"):
                        job[verdict] = int(job.get(verdict, 0)) + 1
                job["current_sense"] = ""
                job["deferred_ids"] = list(deferred)
                _write_status(base, job)
    except Exception as exc:
        fail_job(run_id, "worker: %s: %s" % (type(exc).__name__, exc),
                 data_root)
        return
    with _LOCK:
        _settle(run_id, base, "done")
    log.append("info", "done", "deferred=%d" % len(deferred))


def _done_of(run_id):
    job = _JOBS.get(run_id) or {}
    try:
        return int(job.get("done", 0))
    except (TypeError, ValueError):
        return 0


def _settle(run_id, base, status, error=""):
    job = _JOBS.get(run_id)
    if job is None:
        return
    job["status"] = status
    job["current_sense"] = ""
    if error:
        job["error"] = error
    _write_status(base, job)
    _ABORTS.discard(run_id)


def fail_job(run_id, error, data_root=None):
    """Mark a run failed (worker-level catch-all path)."""
    if not _run_id_ok(run_id):
        return
    base, _s, _r, _l = _paths(run_id, data_root)
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
    """Live job, else last persisted status, else None."""
    name = str(run_id or "")
    if not _run_id_ok(name):
        return None
    with _LOCK:
        job = _JOBS.get(name)
        if job is not None:
            return dict(job)
    _base, status_path, _r, _l = _paths(name, data_root)
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
                        "(results written so far are kept)")
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


def load_results(run_id, data_root=None):
    """Result records written so far (``[]`` when none yet)."""
    if not _run_id_ok(run_id):
        return []
    _base, _s, results_path, _l = _paths(run_id, data_root)
    out = []
    try:
        with open(results_path, encoding="utf-8") as handle:
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
