"""Run a command with a leased egress (phase 2 companion).

Usage: python tools/egress/run_with_lease.py <target> -- <command...>

Valid targets come from supervisor.TARGETS (direct/zen/google/
openrouter/avalai).

Leases from the local supervisor, exports HTTPS_PROXY/HTTP_PROXY (+ NO_PROXY
for domestic hosts) into the CHILD process only — the system VPN and the
parent shell are untouched. Streams the child output live with a progress
prefix. Exit code = child exit code.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import client  # noqa: E402  (same dir companion)
from supervisor import TARGETS, norm_target  # noqa: E402  (registry)

NO_PROXY_DOMESTIC = "api.avalai.ir,localhost,127.0.0.1"

USAGE = "usage: run_with_lease.py <%s> -- <command...>" % "|".join(TARGETS)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    target = norm_target(args[0]) if args else ""
    if not target or target not in TARGETS:
        print(USAGE)
        return 2
    rest = args[1:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    if not rest:
        print(USAGE)
        return 2
    lease = client.lease(target)
    if lease.get("error"):
        print("lease failed: %s" % lease.get("message"))
        return 3
    print("[egress] mode=%s egress=%s lease=%s" % (
        lease.get("mode"), lease.get("egress_ip"),
        lease.get("lease_id", "")[:8]))
    env = dict(os.environ)
    proxy = lease.get("proxy_url") or ""
    if proxy:
        env["HTTPS_PROXY"] = proxy
        env["HTTP_PROXY"] = proxy
        no_proxy = env.get("NO_PROXY", "")
        domestic = [h for h in NO_PROXY_DOMESTIC.split(",") if h]
        if no_proxy:
            domestic = (no_proxy.split(",") + domestic)
        env["NO_PROXY"] = ",".join(dict.fromkeys(
            h.strip() for h in domestic if h.strip()))
    try:
        proc = subprocess.Popen(rest, env=env)
        code = proc.wait()
    except OSError as exc:
        print("[egress] spawn failed: %s" % exc)
        return 4
    try:
        # Exit code alone cannot prove network health: only report ok
        # (0) or unknown (anything else — keeps the lease, cools nothing).
        # Report net_err ONLY on transport-level proof (timeouts/429s
        # observed by the child are its own business via direct report).
        outcome = "ok" if code == 0 else "unknown"
        client.report(lease.get("lease_id", ""), outcome)
    except Exception as exc:  # noqa: BLE001 (report is best-effort)
        print("[egress] report failed: %s" % exc)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
