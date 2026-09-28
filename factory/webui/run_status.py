"""Cabin-parametric run-status store for the factory web consoles (T04/T05).

Single owner of ``<DATA_ROOT>/webui/<cabin>_run_status.json`` (latest-run
pointer per cabin) and of the ``<DATA_ROOT>/webui/<cabin>_runs/`` history
scan. No Flask imports, so the server stays a thin caller.

Status file schema (written on spawn, updated on settle)::

    {run_id, pid, started_iso, out_dir, out_name, words_hash, status}

with ``status`` in ``running|completed|failed|aborted``. Writes are
atomic tmp+replace with fsync; reads never raise (missing/corrupt →
``None``). ``pid`` is a liveness probe only — never kill-by-guess (the
server keeps its existing abort path).

History (T05) is a READ view over run dirs + the status file — no new
write path here. Each immediate subdir of ``<cabin>_runs/`` holding a
``run.json`` record ``{run_id, out_name, out_dir, started_iso, status,
kept_total, dropped_total}`` contributes one row; the T04 status file
for the same cabin is merged in (it wins on equal ``run_id`` — it is
the freshest). Newest last. Unreadable records are skipped with a
count (never a 500). Capped at ``HISTORY_LIMIT`` (``truncated: true``
beyond, newest kept).

Cabin allowlisting (which cabins exist) is intentionally NOT owned
here — the store accepts any safe cabin key and the HTTP layer maps
unknown cabins to 400. That keeps the store generic while the console
stays honest about unregistered cabins.
"""

from __future__ import annotations

import json
import os
import re

#: History cap: at most this many records per response (newest kept).
HISTORY_LIMIT = 500

#: Per-run record filename inside each ``<cabin>_runs/<run_id>/`` dir.
RUN_FILENAME = "run.json"

#: Safe cabin key: filesystem-safe, no traversal, no surprises.
_CABIN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: Terminal states (informational; the store passes any status through).
TERMINAL_STATUSES = frozenset({"completed", "failed", "aborted"})


def validate_cabin(cabin: str) -> str:
    """Stripped cabin key or raises ``ValueError`` (traversal-proof)."""
    clean = str(cabin or "").strip()
    if not _CABIN_RE.match(clean):
        raise ValueError("unknown cabin: %s" % (clean or cabin,))
    return clean


def status_path(data_root: str, cabin: str) -> str:
    """Absolute ``<cabin>_run_status.json`` path (never creates dirs)."""
    key = validate_cabin(cabin)
    return os.path.join(str(data_root or ""), "webui",
                        "%s_run_status.json" % key)


def runs_dir(data_root: str, cabin: str) -> str:
    """Absolute ``<cabin>_runs/`` dir path (never creates dirs)."""
    key = validate_cabin(cabin)
    return os.path.join(str(data_root or ""), "webui",
                        "%s_runs" % key)


def _atomic_write_json(path: str, payload: dict) -> None:
    """Atomic tmp+replace JSON write with fsync (raises OSError)."""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def write(data_root: str, cabin: str, record: dict) -> dict:
    """Persist the latest-run pointer for ``cabin`` (atomic, fsynced).

    ``record`` must be a dict with a non-empty ``run_id``; all other
    keys pass through verbatim (the T04 schema is a server-side
    contract documented above). Returns the stored record.
    """
    key = validate_cabin(cabin)
    if not isinstance(record, dict):
        raise ValueError("record must be a dict")
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("record needs a non-empty run_id")
    stored = dict(record)
    _atomic_write_json(status_path(data_root, key), stored)
    return stored


def read(data_root: str, cabin: str):
    """Latest-run record for ``cabin`` (missing/corrupt → ``None``)."""
    try:
        path = status_path(data_root, cabin)
    except ValueError:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return None
    return payload


def _coerce_int(value):
    """Small int or ``None`` (honest empty, never invented zeros)."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_record(raw) -> dict | None:
    """``run.json`` blob → history row, or ``None`` when corrupt."""
    if not isinstance(raw, dict):
        return None
    run_id = raw.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return None
    status = raw.get("status")
    row = {
        "run_id": run_id.strip(),
        "out_name": (raw.get("out_name") if isinstance(
            raw.get("out_name"), str) else ""),
        "out_dir": (raw.get("out_dir") if isinstance(
            raw.get("out_dir"), str) else ""),
        "started_iso": (raw.get("started_iso") if isinstance(
            raw.get("started_iso"), str) else ""),
        "status": (status.strip() if isinstance(status, str)
                   and status.strip() else "unknown"),
        "kept_total": _coerce_int(raw.get("kept_total")),
        "dropped_total": _coerce_int(raw.get("dropped_total")),
    }
    return row


def _read_run_record(path: str):
    """(row_or_None, corrupt_bool) for one ``run.json`` path."""
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return None, True
    row = _coerce_record(raw)
    return (row, False) if row is not None else (None, True)


def history(data_root: str, cabin: str, limit: int = HISTORY_LIMIT) -> dict:
    """``{cabin, runs, skipped, truncated}`` newest-last (never raises).

    ``limit`` bounds the returned rows (newest kept); non-positive or
    non-numeric falls back to ``HISTORY_LIMIT``.
    """
    key = validate_cabin(cabin)
    try:
        cap = int(limit)
    except (TypeError, ValueError):
        cap = HISTORY_LIMIT
    if cap <= 0:
        cap = HISTORY_LIMIT
    rows: list = []
    skipped = 0
    try:
        names = sorted(os.listdir(runs_dir(data_root, key)))
    except OSError:
        names = []
    for name in names:
        entry = os.path.join(runs_dir(data_root, key), name)
        try:
            is_dir = os.path.isdir(entry)
        except OSError:
            continue
        if not is_dir:
            continue
        row, corrupt = _read_run_record(os.path.join(entry, RUN_FILENAME))
        if row is None:
            skipped += 1
            continue
        rows.append(row)
    live = read(data_root, key)
    live_row = _coerce_record(live) if live is not None else None
    if live_row is not None:
        rows = [r for r in rows if r["run_id"] != live_row["run_id"]]
        rows.append(live_row)
    rows.sort(key=lambda r: (r["started_iso"] or "", r["run_id"]))
    truncated = len(rows) > cap
    if truncated:
        rows = rows[-cap:]
    return {"cabin": key, "runs": rows, "skipped": skipped,
            "truncated": truncated}
