"""R2 CI gate: run the test suite and assert peak combined RAM stays <= 2600 MB.

Usage (local):  python scripts/run_with_ram_gate.py [-n 8]
Usage (CI):     python scripts/run_with_ram_gate.py -n 4

The wrapper launches pytest as a child process, samples the combined working
set (RSS) of every Python process in the run tree every 0.2s, and exits non-zero
if peak RAM exceeds the budget. pytest's own exit code is propagated, so this is
both the correctness gate and the RAM gate in one command.

Budget: 2600 MB (the TEST SAFETY CONTRACT resource target). 14 workers are the
measured cap (16 approaches the limit); 8 is the daily default (peak ~2.0GB,
~75% of budget) and 14 stays available as explicit opt-in for quiet machines.
Measured cost is ~260MB/worker (clean-tree -n 10 peaks 2.3-2.4GB), which is
also the preflight auto-cap unit. Do not raise workers without re-running
this gate.

Preflight (R1 serialize rule): the full parallel suite and a LOADED LM-Studio
model must never run together. Before launching pytest, the wrapper refuses
(exit 1) when a model server on 127.0.0.1:1234 reports a non-empty
`/v1/models` list (or the list cannot be read — fail-closed) while the
EFFECTIVE workers > 4, or when free RAM fits fewer than 2 workers.
Otherwise RAM auto-caps workers (~260MB each, measured): 3GB free runs up
to 11, 2.2GB runs 8, 1GB runs 3 — with a notice, never a refusal. An idle
server (port open, zero models loaded) is allowed: it holds ~50MB, not
gigabytes. Serial runs (-n 0/1) always proceed. Escape hatch for CI/exotic
runners: `--skip-preflight` or `HAMZABAN_SKIP_PREFLIGHT=1`
(default: enforce). CI safety: CI runners have no :1234 listener and run
with -n 2 (below the workers > 4 trigger) — so the preflight cannot fire
there; the escape hatch covers the rest.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

try:
    import psutil
except ImportError:  # pragma: no cover - fail-closed handled in main()
    psutil = None

RAM_BUDGET_MB = 2600
SAMPLE_INTERVAL = 0.2

MODEL_SERVER_HOST = "127.0.0.1"
MODEL_SERVER_PORT = 1234
MODEL_SERVER_TIMEOUT_S = 1.0
MODEL_LIST_TIMEOUT_S = 1.0
SERIALIZE_WORKER_THRESHOLD = 4
MAX_WORKERS = 14
MIN_WORKERS_FOR_RUN = 2
PER_WORKER_RSS_MB = 260
SKIP_PREFLIGHT_ENV_VAR = "HAMZABAN_SKIP_PREFLIGHT"
INCLUDE_RESEARCH_ENV_VAR = "HAMZABAN_INCLUDE_RESEARCH"


def _preflight_skip_requested(cli_skip: bool) -> bool:
    if cli_skip:
        return True
    return os.environ.get(SKIP_PREFLIGHT_ENV_VAR, "") == "1"


def _model_server_is_up() -> bool:
    try:
        with socket.create_connection(
            (MODEL_SERVER_HOST, MODEL_SERVER_PORT),
            timeout=MODEL_SERVER_TIMEOUT_S,
        ):
            return True
    except OSError:
        return False


def _free_ram_bytes():
    if psutil is None:
        return None
    try:
        return psutil.virtual_memory().available
    except Exception:
        return None


def _total_ram_bytes():
    if psutil is None:
        return None
    try:
        return psutil.virtual_memory().total
    except Exception:
        return None


def _loaded_model_count():
    """Number of models loaded on the local server, or None when unknown.

    Queries GET /v1/models (LM-Studio OpenAI-compatible metadata endpoint;
    no model call, no tokens). Any error (timeout, refused, bad JSON)
    returns None so the caller can fail closed.
    """
    url = f"http://{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=MODEL_LIST_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        return len(data) if isinstance(data, list) else None
    except Exception:
        return None


def run_preflight_checks(workers: int):
    """Fail-fast serialize guard (R1) + RAM worker auto-cap.

    Returns the EFFECTIVE worker count to run, or None on refusal.

    Refuses when (a) a LOADED model server answers on 127.0.0.1:1234 while
    effective workers > 4 (idle server with zero models is allowed), or
    (b) free RAM fits fewer than MIN_WORKERS_FOR_RUN workers. An
    unreadable model list fails closed (treated as loaded). Serial runs
    (-n 0/1) always proceed. RAM auto-caps: effective = min(requested,
    free // PER_WORKER_RSS_MB, MAX_WORKERS), announced on stderr when it
    bites — a notice, never a "lower your workers" advice (R4).
    psutil missing -> RAM check skipped here (main() still fails closed
    with exit 2 after the run).
    """
    free = _free_ram_bytes()
    total = _total_ram_bytes()
    if workers >= MIN_WORKERS_FOR_RUN and free is not None:
        cap = min(free // (PER_WORKER_RSS_MB * 1024 * 1024), MAX_WORKERS)
        if cap < MIN_WORKERS_FOR_RUN:
            total_gb = (f" of {total / (1024 ** 3):.1f}GB total"
                        if total else "")
            print(
                f"[RAM-GATE] REFUSE: free system RAM is {free / (1024 ** 3):.1f}GB"
                f"{total_gb}, fitting fewer than {MIN_WORKERS_FOR_RUN} workers. "
                "Free RAM, then re-run.",
                file=sys.stderr,
            )
            return None
        effective = min(workers, cap)
    else:
        effective = workers
    if effective > SERIALIZE_WORKER_THRESHOLD and _model_server_is_up():
        count = _loaded_model_count()
        if count is None:
            print(
                "[RAM-GATE] REFUSE: model server detected on "
                f"{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT} while requesting "
                f"{workers} workers, and its /v1/models list is unreadable "
                "(fail-closed). Stop the model server, then re-run.",
                file=sys.stderr,
            )
            return None
        if count > 0:
            print(
                "[RAM-GATE] REFUSE: model server on "
                f"{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT} has {count} loaded "
                f"model(s) while requesting {workers} workers. Unload the "
                "model(s), then re-run. A loaded model and the full parallel "
                "suite must never run together.",
                file=sys.stderr,
            )
            return None
        print(
            "[RAM-GATE] idle model server on "
            f"{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT} (0 models loaded) — "
            "proceeding.",
            file=sys.stderr,
        )
    if effective != workers:
        free_gb = (f"{free / (1024 ** 3):.1f}GB free"
                   if free is not None else "unknown free RAM")
        print(
            f"[RAM-GATE] RAM allows {effective} workers ({free_gb}); "
            f"capping requested {workers}.",
            file=sys.stderr,
        )
    return effective


def _peak_rss_mb(pid: int) -> float:
    if psutil is None:
        return 0.0
    try:
        root = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0
    seen = {root.pid}
    try:
        total = root.memory_info().rss
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0
    for child in root.children(recursive=True):
        if child.pid in seen:
            continue
        seen.add(child.pid)
        try:
            total += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total / (1024 * 1024)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--workers", default="8")
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Bypass the RAM-preflight serialize guard (CI/exotic runners; "
        "also via HAMZABAN_SKIP_PREFLIGHT=1). Default: enforce.",
    )
    args, rest = parser.parse_known_args(argv)

    if _preflight_skip_requested(args.skip_preflight):
        print("[RAM-GATE] preflight skipped via escape hatch.", file=sys.stderr)
        try:
            workers = int(args.workers)
        except (TypeError, ValueError):
            workers = 0
    else:
        try:
            workers = int(args.workers)
        except (TypeError, ValueError):
            workers = 0
        effective = run_preflight_checks(workers)
        if effective is None:
            return 1
        workers = effective

    cmd = [sys.executable, "-m", "pytest", "tests/", "-n", str(workers), "-q"]
    if ("-m" not in rest
            and os.environ.get(INCLUDE_RESEARCH_ENV_VAR, "") != "1"):
        # R&D-only tests (marked research) stay out of default runs;
        # explicit -m from the caller, or HAMZABAN_INCLUDE_RESEARCH=1, wins.
        cmd += ["-m", "not research"]
    cmd += rest
    proc = subprocess.Popen(cmd, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    peak = 0.0
    start = time.monotonic()
    while proc.poll() is None:
        peak = max(peak, _peak_rss_mb(proc.pid))
        time.sleep(SAMPLE_INTERVAL)

    proc.wait()
    elapsed = time.monotonic() - start
    print(f"\n[RAM-GATE] wall={elapsed:.1f}s peak_combined_rss={peak:.0f}MB "
          f"(budget={RAM_BUDGET_MB}MB)")
    if psutil is None:
        print(f"[RAM-GATE] FAIL: psutil not installed; the {RAM_BUDGET_MB}MB budget cannot "
              "be enforced. Install psutil (pip install psutil).",
              file=sys.stderr)
        return 2
    if peak <= 0:
        # Preserve pytest's exit code; handle signal termination distinctly.
        rc = proc.returncode
        sig_info = ""
        if rc is not None and rc < 0:
            sig_info = f" (terminated by signal {-rc})"
        if elapsed < SAMPLE_INTERVAL * 2:
            print(f"[RAM-GATE] FAIL: pytest exited very quickly ({elapsed:.1f}s) before "
                  f"any RAM sample could be collected (pytest exit code {rc}{sig_info}). "
                  "Check pytest output for collection/import errors.", file=sys.stderr)
        else:
            print("[RAM-GATE] FAIL: could not sample process RAM (no valid "
                  f"sample collected, pytest exit code {rc}{sig_info}). "
                  "Check psutil permissions.", file=sys.stderr)
        # Normalize signal to 128+sig for shell convention, but preserve non-zero
        if rc is None:
            return 2
        if rc < 0:
            return 128 - rc
        return rc or 2
    if peak > RAM_BUDGET_MB:
        print(f"[RAM-GATE] FAIL: peak RAM exceeds the {RAM_BUDGET_MB}MB budget.", file=sys.stderr)
        return 1
    print("[RAM-GATE] OK: within budget.")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
