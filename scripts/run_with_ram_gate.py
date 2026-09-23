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
Do not raise workers without re-running this gate.

Preflight (R1 serialize rule): the full parallel suite and a LOADED LM-Studio
model must never run together. Before launching pytest, the wrapper refuses
(exit 1) when a model server on 127.0.0.1:1234 reports a non-empty
`/v1/models` list (or the list cannot be read — fail-closed) while
workers > 4, or when free system RAM is below 20% of total RAM. An idle
server (port open, zero models loaded) is allowed: it holds ~50MB, not
gigabytes. Escape hatch for CI/exotic runners: `--skip-preflight` or
`HAMZABAN_SKIP_PREFLIGHT=1` (default: enforce). CI safety: CI runners have
no :1234 listener, run with -n 2 (below the workers > 4 trigger), and have
>20% free — so the preflight cannot fire there; the escape hatch covers
the rest.
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
MIN_FREE_RAM_FRACTION = 0.20
SKIP_PREFLIGHT_ENV_VAR = "HAMZABAN_SKIP_PREFLIGHT"


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
    """Fail-fast serialize guard (R1). Returns 1 on refusal, else None.

    Refuses when (a) a LOADED model server answers on 127.0.0.1:1234 while
    workers > 4 (idle server with zero models is allowed), or (b) free
    system RAM is below 20% of total RAM. An unreadable model list fails
    closed (treated as loaded). psutil missing -> RAM check skipped here
    (main() still fails closed with exit 2 after the run). Never suggests
    lowering workers (R4).
    """
    if workers > SERIALIZE_WORKER_THRESHOLD and _model_server_is_up():
        count = _loaded_model_count()
        if count is None:
            print(
                "[RAM-GATE] REFUSE: model server detected on "
                f"{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT} while requesting "
                f"{workers} workers, and its /v1/models list is unreadable "
                "(fail-closed). Stop the model server, then re-run.",
                file=sys.stderr,
            )
            return 1
        if count > 0:
            print(
                "[RAM-GATE] REFUSE: model server on "
                f"{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT} has {count} loaded "
                f"model(s) while requesting {workers} workers. Unload the "
                "model(s), then re-run. A loaded model and the full parallel "
                "suite must never run together.",
                file=sys.stderr,
            )
            return 1
        print(
            "[RAM-GATE] idle model server on "
            f"{MODEL_SERVER_HOST}:{MODEL_SERVER_PORT} (0 models loaded) — "
            "proceeding.",
            file=sys.stderr,
        )
    free = _free_ram_bytes()
    total = _total_ram_bytes()
    if free is not None and total:
        if free < MIN_FREE_RAM_FRACTION * total:
            print(
                f"[RAM-GATE] REFUSE: free system RAM is {free / (1024 ** 3):.1f}GB "
                f"({100.0 * free / total:.0f}% of {total / (1024 ** 3):.1f}GB total), "
                "below the 20% floor. Free RAM, then re-run.",
                file=sys.stderr,
            )
            return 1
    return None


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
    else:
        try:
            workers = int(args.workers)
        except (TypeError, ValueError):
            workers = 0
        refusal = run_preflight_checks(workers)
        if refusal is not None:
            return refusal

    cmd = [sys.executable, "-m", "pytest", "tests/", "-n", args.workers, "-q"]
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
