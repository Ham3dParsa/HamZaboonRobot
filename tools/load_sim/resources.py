"""Resource probes for the 5k load simulation (locked plan scale/plan-load-sim-5k, T1).

Pure helpers with no I/O beyond ``os.stat`` (plus process introspection for
RSS). Tool-only: imported by ``tools.load_sim.driver.run_load_5k``; no
production modules touched.

Probes:
- :func:`rss_bytes` — current process RSS in bytes. Uses ``psutil`` when
  importable; otherwise falls back to ``resource.getrusage`` (``ru_maxrss``
  scaled to bytes) where available, else ``0``. ``psutil`` is OPTIONAL: this
  module must import cleanly without it (``try/except ImportError``, fallback
  noted here in the docstring).
- :func:`db_file_sizes` — ``(db_bytes, wal_bytes)`` for a SQLite path via
  ``os.stat``; missing files report ``0``.
- :func:`p95_ms` — nearest-rank p95 over a list of millisecond timings.
- :func:`percentile_summary` — p50/p90/p95/p99/max/count summary over a
  list of millisecond timings (same nearest-rank as ``p95_ms``).
- :func:`cpu_process_seconds` — total user+system CPU seconds for this
  process. ``psutil`` is OPTIONAL here too (same import-cleanly rule):
  ``psutil.Process().cpu_times()`` sum → ``resource.getrusage``
  ``ru_utime`` + ``ru_stime`` → ``None`` when neither source is available.
- :func:`probe_loop_lag_ms` / :func:`lag_probe_loop` — cooperative
  event-loop lag probes: sleep ``delay_s``/``interval_s`` and report the
  overshoot in ms. The driver runs :func:`lag_probe_loop` as a background
  task around the replay and takes the p95 of its samples.
"""

from __future__ import annotations

import asyncio
import math
import os
import sys

try:  # Optional dependency — import-cleanly without psutil (fallback below).
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - exercised when psutil is absent
    psutil = None  # type: ignore


def rss_bytes() -> int:
    """Return current process RSS in bytes (psutil if present, else fallback).

    Fallback chain (documented): ``psutil.Process().memory_info().rss`` →
    ``resource.getrusage(RUSAGE_SELF).ru_maxrss`` scaled to bytes (Linux
    reports KiB, macOS reports bytes — handled by an explicit
    ``sys.platform`` branch) → ``0`` when neither source is available.
    """
    if psutil is not None:
        try:
            return int(psutil.Process().memory_info().rss)
        except Exception:
            pass
    try:
        import resource

        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if maxrss <= 0:
            return 0
        # Explicit platform branch: Linux ru_maxrss is KiB, macOS is
        # bytes. (Magnitude sniffing mis-scaled Linux RSS above 1 GiB.)
        if sys.platform == "darwin":
            return int(maxrss)
        return int(maxrss * 1024)
    except Exception:
        return 0


def db_file_sizes(path: str) -> tuple[int, int]:
    """Return ``(db_bytes, wal_bytes)`` for the SQLite file at ``path``.

    Only ``os.stat`` I/O. A missing/unreadable file (or its ``-wal``
    sidecar) reports ``0`` for that slot. ``None``/non-str/empty paths
    (e.g. an unset ``db_path``) report ``(0, 0)`` instead of raising
    ``TypeError``.
    """
    if not isinstance(path, str) or not path:
        return (0, 0)
    try:
        db_bytes = int(os.stat(path).st_size)
    except OSError:
        db_bytes = 0
    try:
        wal_bytes = int(os.stat(path + "-wal").st_size)
    except OSError:
        wal_bytes = 0
    return db_bytes, wal_bytes


def _rank_index(frac: float, n: int) -> int:
    """Nearest-rank index for fraction ``frac`` over ``n`` samples."""
    return max(0, min(n - 1, math.ceil(frac * n) - 1))


def p95_ms(values: list[float]) -> float:
    """Nearest-rank p95 over millisecond timings (``0.0`` when empty)."""
    if not values:
        return 0.0
    return float(sorted(values)[_rank_index(0.95, len(values))])


def percentile_summary(values: list[float]) -> dict:
    """Nearest-rank p50/p90/p95/p99/max/count over ms timings.

    ``p95`` here always equals :func:`p95_ms` on the same input (shared
    rank helper); empty input reports ``0.0``/``0`` throughout.
    """
    if not values:
        return {
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
            "count": 0,
        }
    ordered = sorted(values)
    n = len(ordered)
    return {
        "p50": float(ordered[_rank_index(0.50, n)]),
        "p90": float(ordered[_rank_index(0.90, n)]),
        "p95": float(ordered[_rank_index(0.95, n)]),
        "p99": float(ordered[_rank_index(0.99, n)]),
        "max": float(ordered[-1]),
        "count": n,
    }


def cpu_process_seconds() -> float | None:
    """Return total user+system CPU seconds for this process, or ``None``.

    Fallback chain (documented): ``psutil.Process().cpu_times()``
    user+system sum → ``resource.getrusage(RUSAGE_SELF)`` ``ru_utime`` +
    ``ru_stime`` → ``None`` when neither source is available. Never
    raises — callers treat ``None`` as "CPU accounting unavailable" and
    still report wall-clock latencies. Values are absolute since process
    start, so callers take deltas around the replay window.
    """
    if psutil is not None:
        try:
            times = psutil.Process().cpu_times()
            return float(times.user + times.system)
        except Exception:
            pass
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        return float(usage.ru_utime + usage.ru_stime)
    except Exception:
        return None


async def probe_loop_lag_ms(delay_s: float = 0.02) -> float:
    """Measure one event-loop lag sample: overshoot beyond ``delay_s``, in ms."""
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await asyncio.sleep(delay_s)
    return max(0.0, (loop.time() - t0 - delay_s) * 1000.0)


async def lag_probe_loop(
    stop: asyncio.Event, interval_s: float, samples: list[float]
) -> None:
    """Append :func:`probe_loop_lag_ms` samples every ``interval_s`` until set."""
    while not stop.is_set():
        samples.append(await probe_loop_lag_ms(interval_s))
