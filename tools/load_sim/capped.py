"""Capped load-sim runner (locked plan scale/plan-load-sim-capacity, T4 C1).

Harness-only: runs the ``tools.load_sim`` replays under Windows Job Object
caps using ``ctypes`` ONLY (stdlib, zero downloads, zero new dependencies).
No production module is touched; this module only imports production code
inside the child thunks, exactly like the existing load-sim flow tests.

What Windows Job Objects CAN do (used here):

- CPU hard cap via ``JOBOBJECT_CPU_RATE_CONTROL_INFORMATION`` (class 15,
  ``CONTROL_ENABLE | CONTROL_HARD_CAP``, ``CpuRate = percent * 100``).
  The cap is a rate limit over short scheduling quanta: the job's threads
  are throttled to roughly ``percent`` of one logical CPU set... in
  practice of total CPU. There is NO ``nr_throttled``-style counter, so a
  tripped CPU cap is observable only indirectly as timing dilation (this
  module reports a ``cpu_throttled`` heuristic against an optional
  caller-supplied baseline wall time, otherwise ``None``).
- Per-process committed-memory limit via
  ``JOBOBJECT_EXTENDED_LIMIT_INFORMATION`` (class 9,
  ``JOB_OBJECT_LIMIT_PROCESS_MEMORY``, ``ProcessMemoryLimit``). Exceeding
  it fails the committing allocation (Python typically raises
  ``MemoryError`` or the runtime aborts) — it does NOT cleanly SIGKILL a
  chosen victim the way the Linux OOM killer does.

Honest Job Objects vs Linux cgroups comparison (documented limitation):

- No I/O throttling (no ``fsync``/blkio throttle): SQLite ``fsync``
  latency is uncapped, so DB-write tails are NOT box-faithful.
- No page-cache isolation: the file cache is system-wide, so replay I/O
  can look faster than on a real small box with a cold cache.
- Memory accounting is per-process commit, not container RSS: shared
  pages (notably the Python interpreter + imported extension modules)
  count against every capped process, and there is no memory-pressure
  reclaim signal — the limit is a hard commit wall.
- CPU rate control has no throttle counters (see above) and no
  deadline/period tuning like ``cpu.max``; short bursty handler slices
  are smoothed, not shaped.
- Job assignment issticky: once the CURRENT process joins a job, the
  limits can only ever tighten for its lifetime. That is why
  :func:`run_capped` defaults to ``use_child=True``: the cap (and any OOM
  death) happens in a spawned child while the test runner survives and
  reports ``killed=True``.

Fallback (honest labeling, never faked caps): when Job Objects are
unavailable (non-Windows platform, or any API failure) and
``fallback_affinity=True``, the child is restricted with CPU affinity to
a single core and the envelope reports ``mode="affinity-estimate"`` with
``caps_enforced=False`` and ``cap_error`` naming the exact API that
failed. Affinity is NOT a cap (a single-threaded replay on one core runs
at full speed; RAM is entirely unenforced) — results in this mode are
estimates only. With ``fallback_affinity=False`` the original
:data:`CapUnavailableError` propagates.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import multiprocessing as mp
import os
import sys
import time
from unittest.mock import MagicMock, patch

from tools.load_sim.resources import percentiles_ms, rss_bytes

# Locked T4 caps.
TINY_BOX = {"cpu_percent": 15, "ram_bytes": 256 * 1024**2}
SAFE_ZONE = {"cpu_percent": 50, "ram_bytes": 512 * 1024**2}

# Mock-sleep scale applied to every capped replay (documented C2 scaling):
# Telegram send 2-8ms -> 0.5-2ms, AI fake 10-30ms -> 2.5-7.5ms,
# 429 retry_after 10-50ms -> 2.5-12.5ms. Batch stagger (10ms) and the
# 50ms loop-lag probe are left unscaled. The scale changes harness timing
# values only: journey mix (plan_mix seeds), RNG draw sequences, retry
# paths, and correctness counters are untouched. Grade latency percentiles
# are therefore harness-relative, not production-latency predictions.
SLEEP_SCALE = 0.25

_JOB_EXTENDED_LIMIT_INFO = 9
_JOB_CPU_RATE_CONTROL_INFO = 15
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
_CPU_ENABLE = 0x1
_CPU_HARD_CAP = 0x4

# Handles are kept alive process-wide: closing the last handle to a job
# object can tear the job down, so in-process caps pin their handles here.
_OPEN_JOB_HANDLES: list[int] = []


class CapError(Exception):
    """Base error for the capped runner."""


class CapUnavailableError(CapError):
    """Raised when a Job Object cap cannot be applied.

    The message ALWAYS names the exact API that failed (or the platform
    reason), so a fallback decision is auditable — never a silent fake.
    """


def _validate(cpu_percent: int, ram_bytes: int) -> None:
    if not isinstance(cpu_percent, int) or not 1 <= cpu_percent <= 100:
        raise ValueError(f"cpu_percent must be int 1..100, got {cpu_percent!r}")
    if not isinstance(ram_bytes, int) or ram_bytes <= 0:
        raise ValueError(f"ram_bytes must be a positive int, got {ram_bytes!r}")


def _kernel32():
    """Return kernel32 via ctypes, or raise naming the exact failure."""
    if sys.platform != "win32":
        raise CapUnavailableError(
            f"Job Objects require Windows (sys.platform={sys.platform!r}); "
            "use fallback_affinity=True for an honestly-labeled estimate"
        )
    try:
        return ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    except Exception as exc:
        raise CapUnavailableError(f"WinDLL(kernel32) load failed: {exc!r}")


class _BasicLimitInfo(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("AffinityMask", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _ExtendedLimitInfo(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInfo),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _CpuRateControlInfo(ctypes.Structure):
    # Second slot is a union (CpuRate DWORD for hard-cap mode); two
    # DWORDs give the correct 8-byte size for the hard-cap use here.
    _fields_ = [
        ("ControlFlags", ctypes.c_uint32),
        ("CpuRate", ctypes.c_uint32),
    ]


def _last_error() -> int:
    try:
        return ctypes.get_last_error()  # type: ignore[attr-defined]
    except Exception:
        return -1


def apply_job_cap(cpu_percent: int, ram_bytes: int) -> dict:
    """Assign the CURRENT process to a new Job Object with the given caps.

    Sticky for the process lifetime (limits can only tighten afterwards).
    Returns ``{"job_handle", "cpu_percent", "ram_bytes", "mode",
    "caps_enforced"}``. Raises :data:`CapUnavailableError` naming the
    exact failing API, or ``ValueError`` for out-of-range caps.
    """
    _validate(cpu_percent, ram_bytes)
    k32 = _kernel32()
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    k32.SetInformationJobObject.restype = ctypes.c_int32
    k32.GetCurrentProcess.argtypes = []
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.AssignProcessToJobObject.restype = ctypes.c_int32

    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise CapUnavailableError(
            f"CreateJobObjectW failed (err={_last_error()})"
        )
    try:
        ext = _ExtendedLimitInfo()
        ext.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_PROCESS_MEMORY
        ext.ProcessMemoryLimit = ram_bytes
        if not k32.SetInformationJobObject(
            job, _JOB_EXTENDED_LIMIT_INFO, ctypes.byref(ext), ctypes.sizeof(ext)
        ):
            raise CapUnavailableError(
                "SetInformationJobObject(JobObjectExtendedLimitInformation) "
                f"failed (err={_last_error()})"
            )
        cpu = _CpuRateControlInfo()
        cpu.ControlFlags = _CPU_ENABLE | _CPU_HARD_CAP
        cpu.CpuRate = cpu_percent * 100
        if not k32.SetInformationJobObject(
            job, _JOB_CPU_RATE_CONTROL_INFO, ctypes.byref(cpu), ctypes.sizeof(cpu)
        ):
            raise CapUnavailableError(
                "SetInformationJobObject(JobObjectCpuRateControlInformation) "
                f"failed (err={_last_error()})"
            )
        if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
            raise CapUnavailableError(
                "AssignProcessToJobObject failed "
                f"(err={_last_error()}; process may already be in a job)"
            )
    except CapUnavailableError:
        try:
            k32.CloseHandle(job)
        except Exception:
            pass
        raise
    _OPEN_JOB_HANDLES.append(int(job))
    return {
        "job_handle": int(job),
        "cpu_percent": cpu_percent,
        "ram_bytes": ram_bytes,
        "mode": "job-objects",
        "caps_enforced": True,
    }


def query_job_cap(job_handle: int) -> dict:
    """Read back the triplet from a job handle (proves the cap applied)."""
    k32 = _kernel32()
    k32.QueryInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    k32.QueryInformationJobObject.restype = ctypes.c_int32
    ext = _ExtendedLimitInfo()
    if not k32.QueryInformationJobObject(
        ctypes.c_void_p(job_handle),
        _JOB_EXTENDED_LIMIT_INFO,
        ctypes.byref(ext),
        ctypes.sizeof(ext),
        None,
    ):
        raise CapUnavailableError(
            "QueryInformationJobObject(JobObjectExtendedLimitInformation) "
            f"failed (err={_last_error()})"
        )
    cpu = _CpuRateControlInfo()
    if not k32.QueryInformationJobObject(
        ctypes.c_void_p(job_handle),
        _JOB_CPU_RATE_CONTROL_INFO,
        ctypes.byref(cpu),
        ctypes.sizeof(cpu),
        None,
    ):
        raise CapUnavailableError(
            "QueryInformationJobObject(JobObjectCpuRateControlInformation) "
            f"failed (err={_last_error()})"
        )
    return {
        "process_memory_limit": int(ext.ProcessMemoryLimit),
        "cpu_rate": int(cpu.CpuRate),
        "cpu_control_flags": int(cpu.ControlFlags),
    }


def _apply_affinity_estimate() -> str:
    """Best-effort single-core affinity; returns a description of what held.

    This is NOT a cap (documented): a single-threaded replay on one core
    still runs at full speed, and RAM is entirely unenforced.
    """
    if sys.platform == "win32":
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.SetProcessAffinityMask.argtypes = [
                ctypes.c_void_p,
                ctypes.c_size_t,
            ]
            k32.SetProcessAffinityMask.restype = ctypes.c_int32
            if k32.SetProcessAffinityMask(k32.GetCurrentProcess(), 1):
                return "SetProcessAffinityMask(cpu0)"
        except Exception as exc:
            return f"affinity unavailable ({exc!r}); no restriction applied"
        return "SetProcessAffinityMask failed; no restriction applied"
    sched = getattr(os, "sched_setaffinity", None)
    if sched is not None:
        try:
            sched(0, {0})
            return "sched_setaffinity(cpu0)"
        except Exception as exc:
            return f"affinity unavailable ({exc!r}); no restriction applied"
    return "no affinity API on this platform; no restriction applied"


@contextlib.contextmanager
def scaled_mock_sleeps(scale: float):
    """Scale the load-sim mock sleeps by ``scale`` (documented C2 scaling).

    Patches the driver send/retry bounds plus a wrapper around the global
    ``time.sleep`` for short (0.5ms-60ms) blocking sleeps — the AI fake's
    10-30ms ``time.sleep``. ``asyncio.sleep`` never touches ``time.sleep``
    (event-loop clock), so coroutine scheduling, the 10ms batch stagger,
    and the 50ms loop-lag probe are unaffected and unscaled.
    """
    import time as _time_mod

    from tools.load_sim import driver as _drv

    orig_sleep = _time_mod.sleep

    def _sleep(seconds):
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return orig_sleep(seconds)
        if 0.0005 <= value <= 0.06:
            value *= scale
        return orig_sleep(value)

    with (
        patch.object(_time_mod, "sleep", _sleep),
        patch.object(_drv, "_SEND_LO_S", _drv._SEND_LO_S * scale),
        patch.object(_drv, "_SEND_HI_S", _drv._SEND_HI_S * scale),
        patch.object(_drv, "_RETRY_AFTER_LO_S", _drv._RETRY_AFTER_LO_S * scale),
        patch.object(_drv, "_RETRY_AFTER_HI_S", _drv._RETRY_AFTER_HI_S * scale),
    ):
        yield


# ---------------------------------------------------------------------------
# Child thunks (module-level so ``spawn`` can pickle them; heavy production
# imports stay INSIDE the functions so importing this module is cheap).
# Percentile summaries use the canonical tools.load_sim.resources owner
# (imported above) — no local duplicate.
# ---------------------------------------------------------------------------


def apply_and_report(cpu_percent: int, ram_bytes: int) -> dict:
    """Child thunk: cap self, read the triplet back, return it."""
    applied = apply_job_cap(cpu_percent, ram_bytes)
    readback = query_job_cap(applied["job_handle"])
    return {"applied": applied, "readback": readback}


def child_allocate_mb(mb: int) -> str:
    """Child thunk: commit ``mb`` MiB (touched pages) to trip a RAM cap."""
    size = int(mb) * 1024 * 1024
    buf = bytearray(size)
    step = 4096
    for off in range(0, size, step):
        buf[off] = 0xAB
    return f"allocated {mb}MiB without tripping the cap"


def echo_counters(payload: dict) -> dict:
    """Child thunk: return ``payload`` verbatim (proves counters flow)."""
    return dict(payload)


def replay_100(db_path: str, seed: int = 7, sleep_scale: float = 1.0, n: int = 100) -> dict:
    """Child thunk: 100-user replay (locked seed 7) against ``db_path``."""
    from tools.load_sim.driver import run_load

    with scaled_mock_sleeps(sleep_scale):
        # Zero-real-token guard, mirroring test_load_sim_100_flow.py.
        with patch(
            "services.ai.ai.ask_card",
            new=MagicMock(side_effect=AssertionError("real AI must not run")),
        ):
            return asyncio.run(run_load(n=n, seed=seed, db_path=db_path))


def replay_5k(
    db_path: str,
    n: int = 2800,
    seed: int = 7,
    concurrency: int = 50,
    sleep_scale: float = 1.0,
) -> dict:
    """Child thunk: 5k peak-slice replay against ``db_path``."""
    from tools.load_sim.driver import run_load_5k

    with scaled_mock_sleeps(sleep_scale):
        # Zero-real-token guards, mirroring test_load_sim_5k_flow.py.
        with (
            patch(
                "services.ai.ai.ask_card",
                new=MagicMock(side_effect=AssertionError("real AI must not run")),
            ),
            patch(
                "services.ai.llm_services._call_ai_limited",
                new=MagicMock(side_effect=AssertionError("real AI must not run")),
            ),
        ):
            return asyncio.run(
                run_load_5k(n=n, seed=seed, db_path=db_path, concurrency=concurrency)
            )


def _child_main(result_path, fn, args, kwargs, cpu_percent, ram_bytes, fallback_affinity):
    """Spawn target: cap self, run ``fn``, pickle the envelope to ``result_path``.

    File transport (not a ``multiprocessing.Queue``): replay payloads hold
    thousands of latency samples and exceed the pipe buffer, which deadlocks
    ``queue.put`` when the parent is still in ``join`` with no concurrent
    reader. The parent polls for the file instead.

    ``result_path`` lives in a private ``mkdtemp`` dir (0700 per
    ``tempfile.mkdtemp``), and the
    child writes a ``.part`` file with ``O_CREAT|O_EXCL`` (mode 0600) then
    atomically renames it — no shared-/tmp symlink race, no partial reads.
    """

    def _store(envelope: dict) -> None:
        import pickle

        try:
            data = pickle.dumps(envelope, protocol=4)
        except Exception:
            # Pickle can fail on exotic fn returns: keep the envelope,
            # degrade the payload to repr (metrics dicts always survive).
            envelope = dict(envelope)
            envelope["result"] = {"unpicklable": repr(envelope.get("result"))[:2000]}
            try:
                data = pickle.dumps(envelope, protocol=4)
            except Exception:
                return
        part_path = result_path + ".part"
        try:
            fd = os.open(part_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError:
            return
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except Exception:
            try:
                os.remove(part_path)
            except OSError:
                pass
            return
        try:
            os.replace(part_path, result_path)
        except OSError:
            try:
                os.remove(part_path)
            except OSError:
                pass

    mode = "none"
    caps_enforced = False
    cap_error = None
    rss_before = rss_bytes()

    try:
        apply_job_cap(cpu_percent, ram_bytes)
        mode = "job-objects"
        caps_enforced = True
    except CapUnavailableError as exc:
        cap_error = str(exc)
        if fallback_affinity:
            detail = _apply_affinity_estimate()
            mode = "affinity-estimate"
            cap_error = f"{cap_error} | fallback: {detail}"
        else:
            _store(
                {
                    "ok": False,
                    "result": None,
                    "error": f"CapUnavailableError: {exc}",
                    "wall_s": 0.0,
                    "rss_before": rss_before,
                    "rss_after": rss_bytes(),
                    "cpu_percent": cpu_percent,
                    "ram_cap_bytes": ram_bytes,
                    "headroom_bytes": None,
                    "killed": False,
                    "timed_out": False,
                    "cpu_throttled": None,
                    "throttle_baseline_s": None,
                    "caps_enforced": False,
                    "mode": "none",
                    "cap_error": str(exc),
                }
            )
            return
    wall_s = 0.0
    ok = True
    result = None
    error = None
    t0 = time.perf_counter()
    try:
        outcome = fn(*args, **kwargs)
        if asyncio.iscoroutine(outcome):
            outcome = asyncio.run(outcome)
        result = outcome
    except Exception as exc:  # noqa: BLE001 - envelope must survive any fn failure
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    finally:
        wall_s = time.perf_counter() - t0
    rss_after = rss_bytes()
    _store(
        {
            "ok": ok,
            "result": result,
            "error": error,
            "wall_s": wall_s,
            "rss_before": rss_before,
            "rss_after": rss_after,
            "cpu_percent": cpu_percent,
            "ram_cap_bytes": ram_bytes,
            "headroom_bytes": ram_bytes - rss_after,
            "killed": False,
            "timed_out": False,
            "cpu_throttled": None,
            "throttle_baseline_s": None,
            "caps_enforced": caps_enforced,
            "mode": mode,
            "cap_error": cap_error,
        }
    )


def _finalize_throttle(envelope: dict, baseline_wall_s: float | None) -> dict:
    """Fill the timing-dilation CPU-throttle heuristic (documented).

    Job Objects expose no throttle counter, so ``cpu_throttled`` is True
    only when a caller baseline is given and the capped wall exceeds it
    by >30%; without a baseline it stays None (unknown, not False).
    """
    envelope["throttle_baseline_s"] = baseline_wall_s
    wall = envelope.get("wall_s") or 0.0
    if baseline_wall_s and baseline_wall_s > 0 and wall > 0:
        envelope["cpu_throttled"] = wall > 1.3 * baseline_wall_s
    else:
        envelope["cpu_throttled"] = None
    return envelope


def run_capped(
    fn,
    *args,
    cpu_percent: int,
    ram_bytes: int,
    use_child: bool = True,
    timeout_s: float = 600,
    baseline_wall_s: float | None = None,
    fallback_affinity: bool = True,
    **kwargs,
) -> dict:
    """Run ``fn(*args, **kwargs)`` under a CPU/RAM cap; return an envelope.

    Child mode (default): a ``spawn`` child caps ITSELF, so an OOM death
    kills only the child and the parent reports ``killed=True`` (no result
    payload, nonzero exit). A live-but-silent child past ``timeout_s`` is
    terminated and reported with ``timed_out=True`` (distinct from
    ``killed``). ``fn`` must be a module-level (picklable) callable;
    coroutine functions are awaited via ``asyncio.run`` in the child.

    In-process mode (``use_child=False``): the cap is applied to the
    CURRENT process and is sticky for its lifetime — use generous caps.
    """
    _validate(cpu_percent, ram_bytes)
    if not use_child:
        rss_before = rss_bytes()
        mode = "none"
        caps_enforced = False
        cap_error = None
        try:
            apply_job_cap(cpu_percent, ram_bytes)
            mode = "job-objects"
            caps_enforced = True
        except CapUnavailableError as exc:
            cap_error = str(exc)
            if fallback_affinity:
                detail = _apply_affinity_estimate()
                mode = "affinity-estimate"
                cap_error = f"{cap_error} | fallback: {detail}"
            else:
                raise
        t0 = time.perf_counter()
        try:
            outcome = fn(*args, **kwargs)
            if asyncio.iscoroutine(outcome):
                outcome = asyncio.run(outcome)
            envelope = {
                "ok": True,
                "result": outcome,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - envelope must survive any fn failure
            envelope = {
                "ok": False,
                "result": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
        rss_after = rss_bytes()
        envelope.update(
            {
                "wall_s": time.perf_counter() - t0,
                "rss_before": rss_before,
                "rss_after": rss_after,
                "cpu_percent": cpu_percent,
                "ram_cap_bytes": ram_bytes,
                "headroom_bytes": ram_bytes - rss_after,
                "killed": False,
                "timed_out": False,
                "caps_enforced": caps_enforced,
                "mode": mode,
                "cap_error": cap_error,
            }
        )
        return _finalize_throttle(envelope, baseline_wall_s)

    # Child mode: the child pickles its envelope to a result file (never a
    # Queue — large replay payloads exceed the pipe buffer and deadlock
    # put() while the parent is still in join). The parent polls for the
    # file with a 1s cadence so a finished-but-unreaped child is picked up
    # promptly; a missing file at deadline means hang (terminate,
    # timed_out) or death (killed). The result file lives in a private
    # mkdtemp dir (0700 per tempfile.mkdtemp), so no shared-/tmp entry
    # can be pre-placed.
    import pickle
    import shutil
    import tempfile

    ctx = mp.get_context("spawn")
    result_dir = tempfile.mkdtemp(prefix="capped_result_")
    result_path = os.path.join(result_dir, "envelope.pkl")
    try:
        return _run_capped_child(
            ctx,
            result_path,
            fn,
            args,
            kwargs,
            cpu_percent,
            ram_bytes,
            timeout_s,
            baseline_wall_s,
            fallback_affinity,
        )
    finally:
        shutil.rmtree(result_dir, ignore_errors=True)


def _run_capped_child(
    ctx,
    result_path,
    fn,
    args,
    kwargs,
    cpu_percent,
    ram_bytes,
    timeout_s,
    baseline_wall_s,
    fallback_affinity,
) -> dict:
    """Spawn the capped child and translate its result file into an envelope."""
    import pickle

    proc = ctx.Process(
        target=_child_main,
        args=(result_path, fn, args, kwargs, cpu_percent, ram_bytes, fallback_affinity),
    )
    proc.start()
    deadline = time.perf_counter() + timeout_s
    envelope = None
    while time.perf_counter() < deadline:
        if os.path.isfile(result_path):
            break
        if not proc.is_alive():
            break
        time.sleep(1.0)
    proc.join(5)
    if os.path.isfile(result_path):
        try:
            with open(result_path, "rb") as fh:
                envelope = pickle.load(fh)
        except Exception as exc:
            envelope = None
            load_error = f"result file unreadable ({exc!r})"
        else:
            load_error = None
    else:
        load_error = None
    if envelope is not None:
        return _finalize_throttle(envelope, baseline_wall_s)
    if proc.is_alive():
        try:
            proc.terminate()
        finally:
            proc.join(30)
        return _finalize_throttle(
            {
                "ok": False,
                "result": None,
                "error": f"timed out after {timeout_s}s; child terminated",
                "wall_s": float(timeout_s),
                "rss_before": rss_bytes(),
                "rss_after": rss_bytes(),
                "cpu_percent": cpu_percent,
                "ram_cap_bytes": ram_bytes,
                "headroom_bytes": None,
                "killed": False,
                "timed_out": True,
                "caps_enforced": False,
                "mode": "unknown",
                "cap_error": None,
            },
            baseline_wall_s,
        )
    # Child is dead and left no (readable) result file: OOM kill (or a
    # hard crash) under the cap. Parent survives — that is the point.
    detail = f"exitcode={proc.exitcode}"
    if load_error:
        detail += f"; {load_error}"
    return _finalize_throttle(
        {
            "ok": False,
            "result": None,
            "error": f"child died with no result file ({detail}); OOM kill likely under a RAM cap",
            "wall_s": 0.0,
            "rss_before": rss_bytes(),
            "rss_after": 0,
            "cpu_percent": cpu_percent,
            "ram_cap_bytes": ram_bytes,
            "headroom_bytes": None,
            "killed": True,
            "timed_out": False,
            "caps_enforced": True,
            "mode": "job-objects",
            "cap_error": None,
        },
        baseline_wall_s,
    )
