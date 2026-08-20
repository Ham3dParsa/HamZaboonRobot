"""R2 CI gate: run the test suite and assert peak combined RAM stays <= 2 GB.

Usage (local):  python scripts/run_with_ram_gate.py [-n 14]
Usage (CI):     python scripts/run_with_ram_gate.py -n 4

The wrapper launches pytest as a child process, samples the combined working
set (RSS) of every Python process in the run tree every 0.2s, and exits non-zero
if peak RAM exceeds the budget. pytest's own exit code is propagated, so this is
both the correctness gate and the RAM gate in one command.

Budget: 2048 MB (the TEST SAFETY CONTRACT resource target). 14 workers are the
measured cap (16 approaches the limit); do not raise workers without re-running
this gate.
"""

import argparse
import os
import subprocess
import sys
import time

try:
    import psutil
except ImportError:  # pragma: no cover - fail-closed handled in main()
    psutil = None

RAM_BUDGET_MB = 2048
SAMPLE_INTERVAL = 0.2


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--workers", default="14")
    args, rest = parser.parse_known_args()

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
    peak = max(peak, _peak_rss_mb(proc.pid))
    print(f"\n[RAM-GATE] wall={elapsed:.1f}s peak_combined_rss={peak:.0f}MB "
          f"(budget={RAM_BUDGET_MB}MB)")
    if peak <= 0:
        print("[RAM-GATE] FAIL: could not sample process RAM (psutil missing). "
              "The 2GB budget cannot be enforced; install psutil.",
              file=sys.stderr)
        return 2
    if peak > RAM_BUDGET_MB:
        print("[RAM-GATE] FAIL: peak RAM exceeds the 2GB budget.", file=sys.stderr)
        return 1
    print("[RAM-GATE] OK: within budget.")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())