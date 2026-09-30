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

from factory.webui.run_log import RunLog

_JOBS = {}
_ABORTS = set()
_LOCK = threading.Lock()

#: Hard per-run ceiling (single constant, documented): no arbiter run
#: ever takes more senses, whatever the request says.
ARBITER_RUN_MAX = 100

USAGE_FILENAME = "arbiter_usage.jsonl"


class ConflictError(ValueError):
    """Another arbiter run is already active (single-flight)."""


class QuotaExhausted(ValueError):
    """Preset quota cannot fit even one more sense (fail-fast)."""


def reset_for_tests():
    """Clear in-memory jobs (test isolation only — same-process suites)."""
    with _LOCK:
        _JOBS.clear()
        _ABORTS.clear()

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


def log_path(run_id, data_root=None):
    """Append-only run log path (R5 RunLog; screening wires later)."""
    base, _s, _v = _paths(str(run_id or ""), data_root)
    return os.path.join(base, "run_log.jsonl")


def usage_path(data_root=None):
    """Append-only usage ledger (counts only — never keys or answers)."""
    return os.path.join(_resolve_root(data_root), "webui",
                        USAGE_FILENAME)


def _to_record(raw):
    """Normalize one ledger line (None when malformed)."""
    if not isinstance(raw, dict):
        return None
    try:
        stamp = datetime.datetime.fromisoformat(str(raw.get("ts") or ""))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    return {"ts": stamp,
            "provider": str(raw.get("provider") or ""),
            "model": str(raw.get("model") or ""),
            "endpoint": str(raw.get("endpoint") or ""),
            "key_var": str(raw.get("key_var") or ""),
            "preset": str(raw.get("preset") or ""),
            "run_id": str(raw.get("run_id") or "")}


def read_usage(data_root=None):
    """Ledger records (newest last); unreadable lines skipped."""
    out = []
    try:
        with open(usage_path(data_root), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return out
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        norm = _to_record(rec)
        if norm is not None:
            out.append(norm)
    return out


def record_use(entry, data_root=None):
    """Append one usage record (best-effort, never raises)."""
    try:
        path = usage_path(data_root)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        blob = dict(entry or {})
        blob["ts"] = _stamp()
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(blob, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def scope_key(scope, *, provider="", model="", endpoint="", key_var=""):
    """(dim, key) for one rate scope (unknown scopes read as model)."""
    scope = str(scope or "").strip().lower()
    if scope == "address":
        return ("address", endpoint or provider)
    if scope == "account":
        return ("account", key_var or provider)
    return ("model", model or provider)


def _dims_of(rec):
    return {("provider", rec["provider"]), ("model", rec["model"]),
            ("address", rec["endpoint"]), ("account", rec["key_var"])}


def summarize(records, now):
    """{(dim, key): {minute, hour, day}} over normalized records."""
    out = {}
    for rec in records or []:
        if not isinstance(rec, dict) or not isinstance(
                rec.get("ts"), datetime.datetime):
            continue
        for dim in _dims_of(rec):
            bucket = out.setdefault(
                dim, {"minute": 0, "hour": 0, "day": 0})
            age = (now - rec["ts"]).total_seconds()
            if age < 0:
                continue
            if age < 60:
                bucket["minute"] += 1
            if age < 3600:
                bucket["hour"] += 1
            if rec["ts"].date() == now.date():
                bucket["day"] += 1
    return out


def quota_remaining(caps, scope_tuple, records, now):
    """{hour, day} remaining (None when that cap is 0 = unlimited)."""
    counts = summarize(records, now).get(tuple(scope_tuple),
                                         {"hour": 0, "day": 0})
    out = {}
    for window, cap_key in (("hour", "max_rph"), ("day", "max_daily")):
        try:
            cap = int((caps or {}).get(cap_key) or 0)
        except (TypeError, ValueError):
            cap = 0
        out[window] = None if cap <= 0 else max(0, cap - counts[window])
    return out


def _write_status(base, job):
    try:
        with open(os.path.join(base, "status.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _accounting_of(accounting):
    """Normalized accounting dict (all keys present, safe defaults)."""
    acc = dict(accounting or {})
    try:
        max_rpm = int(acc.get("max_rpm") or 0)
    except (TypeError, ValueError):
        max_rpm = 0
    try:
        max_rph = int(acc.get("max_rph") or 0)
    except (TypeError, ValueError):
        max_rph = 0
    try:
        max_daily = int(acc.get("max_daily") or 0)
    except (TypeError, ValueError):
        max_daily = 0
    return {"provider": str(acc.get("provider") or ""),
            "model": str(acc.get("model") or ""),
            "endpoint": str(acc.get("endpoint") or ""),
            "key_var": str(acc.get("key_var") or ""),
            "scope": str(acc.get("scope") or "model").strip().lower()
            or "model",
            "preset": str(acc.get("preset") or ""),
            "max_rpm": max(0, max_rpm), "max_rph": max(0, max_rph),
            "max_daily": max(0, max_daily)}


def launch(preset, senses, transport, data_root=None, accounting=None,
           now=None):
    """Start a detached run; return the job id (status ``running``).

    Enforces, in order: single-flight (one active run — ConflictError),
    quota fail-fast (hour/day remaining by scope — QuotaExhausted when
    nothing fits), per-run ceiling (ARBITER_RUN_MAX, clamped with the
    requested count kept on the job for honesty).
    """
    requested = list(senses or [])
    acc = _accounting_of(accounting)
    moment = now or datetime.datetime.now(datetime.timezone.utc)
    with _LOCK:
        for job in _JOBS.values():
            if job.get("status") == "running":
                raise ConflictError(
                    "an arbiter run is already active "
                    "(single-flight: one at a time)")
        scope = scope_key(acc["scope"], provider=acc["provider"],
                          model=acc["model"], endpoint=acc["endpoint"],
                          key_var=acc["key_var"])
        remaining = quota_remaining(
            {"max_rph": acc["max_rph"], "max_daily": acc["max_daily"]},
            scope, read_usage(data_root), moment)
        fits = [n for n in (remaining["hour"], remaining["day"])
                if n is not None]
        granted = list(requested)
        if fits:
            granted = granted[:max(0, min(fits))]
        granted = granted[:ARBITER_RUN_MAX]
        if not granted:
            raise QuotaExhausted(
                "preset quota exhausted (remaining hour=%s day=%s) — "
                "nothing fits" % (remaining["hour"], remaining["day"]))
        run_id = "%s-%s" % (moment.strftime("%Y%m%dT%H%M%SZ"),
                            uuid.uuid4().hex[:6])
        base, _status_path, _verdicts_path = _paths(run_id, data_root)
        os.makedirs(base, exist_ok=True)
        job = {"run_id": run_id,
               "preset": str((preset or {}).get("name") or ""),
               "provider": acc["provider"],
               "model": str((preset or {}).get("model") or ""),
               "status": "running", "started_at": _stamp(),
               "current_sense": "",
               "requested": len(requested),
               "total": len(granted), "done": 0, "abstained": 0,
               "error": ""}
        _JOBS[run_id] = job
        _write_status(base, job)
    RunLog(os.path.join(base, "run_log.jsonl")).append(
        "info", "started", "senses=%d" % len(granted))
    thread = threading.Thread(
        target=_worker,
        args=(run_id, preset or {}, granted, transport, data_root, acc),
        daemon=True)
    thread.start()
    return run_id


def _minute_wait(run_id, acc, data_root):
    """Sleep (abort-aware) while this minute's budget is spent."""
    import time as _time

    cap = int(acc.get("max_rpm") or 0)
    if cap <= 0:
        return True
    while True:
        with _LOCK:
            if run_id in _ABORTS:
                return False
        moment = datetime.datetime.now(datetime.timezone.utc)
        spent = summarize(read_usage(data_root), moment).get(
            scope_key(acc.get("scope"), provider=acc.get("provider"),
                      model=acc.get("model"), endpoint=acc.get("endpoint"),
                      key_var=acc.get("key_var")),
            {"minute": 0})["minute"]
        if spent < cap:
            return True
        _time.sleep(1.0)


def _worker(run_id, preset, senses, transport, data_root, acc=None):
    from factory.linking import arbiter_runner as _runner

    acc = _accounting_of(acc)
    base, _status_path, verdicts_path = _paths(run_id, data_root)
    log = RunLog(os.path.join(base, "run_log.jsonl"))
    try:
        with open(verdicts_path, "w", encoding="utf-8"):
            pass
    except OSError:
        pass
    for sense in senses:
        with _LOCK:
            if run_id in _ABORTS:
                _settle(run_id, base, "aborted")
                log.append("warn", "aborted", "")
                return
            job = _JOBS.get(run_id)
            if job is not None:
                job["current_sense"] = str((sense or {}).get("sense_id")
                                          or "")
                _write_status(base, job)
        log.append("info", "sense",
                   str((sense or {}).get("sense_id") or ""))
        if not _minute_wait(run_id, acc, data_root):
            with _LOCK:
                _settle(run_id, base, "aborted")
            log.append("warn", "aborted", "")
            return
        import time as _time

        _t0 = _time.perf_counter()
        try:
            records = _runner.run_arbiter([sense], preset, transport)
        except Exception as exc:
            fail_job(run_id, "worker: %s: %s" % (type(exc).__name__, exc),
                     data_root)
            return
        _dt_ms = int(round((_time.perf_counter() - _t0) * 1000))
        for _rec in records:
            if isinstance(_rec, dict) and "duration_ms" not in _rec:
                _rec["duration_ms"] = _dt_ms
        written = 0
        try:
            with open(verdicts_path, "a", encoding="utf-8") as handle:
                for rec in records:
                    handle.write(json.dumps(rec, ensure_ascii=False)
                                 + "\n")
                    written += 1
        except OSError:
            pass
        for _rec in records[:written]:
            record_use({"provider": acc["provider"],
                        "model": str(preset.get("model") or ""),
                        "endpoint": acc["endpoint"],
                        "key_var": acc["key_var"],
                        "preset": str(preset.get("name") or ""),
                        "run_id": run_id}, data_root)
        with _LOCK:
            job = _JOBS.get(run_id)
            if job is None:
                return
            job["done"] = int(job.get("done", 0)) + written
            job["abstained"] = int(job.get("abstained", 0)) + sum(
                1 for rec in records[:written] if rec.get("needs_review"))
            job["current_sense"] = ""
            _write_status(base, job)
    with _LOCK:
        _settle(run_id, base, "done")
    log.append("info", "done", "")


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
