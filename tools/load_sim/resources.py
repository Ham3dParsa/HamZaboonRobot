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


def p95_ms(values: list[float]) -> float:
    """Nearest-rank p95 over millisecond timings (``0.0`` when empty)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return float(ordered[idx])


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
