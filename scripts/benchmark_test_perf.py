#!/usr/bin/env python3
"""Benchmark the test suite: unittest (single process) vs pytest-xdist workers.

Usage:
    python scripts/benchmark_test_perf.py
    python scripts/benchmark_test_perf.py --workers 4 8 24

Requires: psutil (pip install psutil)
Reports wall-clock duration, CPU core usage (avg/peak), CPU utilization
percentage (avg/peak, relative to logical threads), and peak RAM for the
whole test process tree.
"""
import argparse
import os
import subprocess
import sys
import time

try:
    import psutil
except ModuleNotFoundError:
    sys.exit("psutil is required: pip install psutil")

INTERVAL = 0.5
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tree(pid):
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []
    try:
        return [root] + root.children(recursive=True)
    except psutil.NoSuchProcess:
        return [root]


def _sum_tree(pid):
    cpu = 0.0
    rss = 0
    for p in _tree(pid):
        try:
            t = p.cpu_times()
            cpu += t.user + t.system
            rss += p.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return cpu, rss


def _measure(cmd):
    start = time.perf_counter()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT
    )
    prev_cpu, _ = _sum_tree(proc.pid)
    prev_t = start
    acc_cpu = 0.0
    acc_t = 0.0
    peak_cores = 0.0
    peak_rss = 0
    while proc.poll() is None:
        time.sleep(INTERVAL)
        now = time.perf_counter()
        cpu, rss = _sum_tree(proc.pid)
        peak_rss = max(peak_rss, rss)
        dt = now - prev_t
        if dt > 0:
            delta = cpu - prev_cpu
            if delta >= 0:
                acc_cpu += delta
                acc_t += dt
                peak_cores = max(peak_cores, delta / dt)
        prev_cpu, prev_t = cpu, now
    duration = time.perf_counter() - start
    avg_cores = acc_cpu / acc_t if acc_t else 0.0
    return {
        "duration": duration,
        "avg_cores": avg_cores,
        "peak_cores": peak_cores,
        "peak_rss": peak_rss,
        "exit_code": proc.returncode,
    }


def _human_bytes(n):
    gb = 1024 ** 3
    if n >= gb:
        return f"{n / gb:.2f} GB"
    return f"{n / (1024 ** 2):.1f} MB"


def _row(label, m, total_cores):
    avg_pct = m["avg_cores"] / total_cores * 100
    peak_pct = m["peak_cores"] / total_cores * 100
    return (
        f"{label:<22} "
        f"{m['duration']:>7.1f}s "
        f"{m['avg_cores']:>4.1f}/{m['peak_cores']:>4.1f} "
        f"{avg_pct:>4.0f}%/{peak_pct:>4.0f}% "
        f"{_human_bytes(m['peak_rss']):>9}"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workers",
        type=int,
        nargs="+",
        default=None,
        help="pytest-xdist worker counts to benchmark (default: 4 8 <logical cores>)",
    )
    args = parser.parse_args(argv)

    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False) or 1
    if args.workers:
        workers = list(args.workers)
    else:
        workers = [4, 8, logical]

    commands = [
        (
            "unittest discover",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        )
    ]
    for n in workers:
        commands.append(
            (f"pytest -n {n}", [sys.executable, "-m", "pytest", "tests/", "-n", str(n)])
        )

    print(f"CPU: {physical} physical / {logical} logical threads")
    print(f"Sampling every {INTERVAL}s; full test suite, single run each.\n")
    header = (
        f"{'Command':<22} "
        f"{'Duration':>9} "
        f"{'CPU cores':>9} "
        f"{'CPU util%':>10} "
        f"{'Peak RAM':>9}"
    )
    print(header)
    print("-" * len(header))

    for label, cmd in commands:
        m = _measure(cmd)
        failed = "" if m["exit_code"] == 0 else f"  (exit {m['exit_code']})"
        print(_row(label, m, logical) + failed)
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
