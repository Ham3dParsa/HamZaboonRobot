"""Run a command with a leased egress (phase 2 companion).

Usage: python tools/egress/run_with_lease.py <direct|zen> -- <command...>

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

NO_PROXY_DOMESTIC = "api.avalai.ir,localhost,127.0.0.1"


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("direct", "zen"):
        print("usage: run_with_lease.py <direct|zen> -- <command...>")
        return 2
    target = args[0]
    rest = args[1:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    if not rest:
        print("usage: run_with_lease.py <direct|zen> -- <command...>")
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
        outcome = "ok" if code == 0 else "net_err"
        client.report(lease.get("lease_id", ""), outcome)
    except Exception as exc:  # noqa: BLE001 (report is best-effort)
        print("[egress] report failed: %s" % exc)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
