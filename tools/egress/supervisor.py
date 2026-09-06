"""Egress supervisor (Design B, phase 1) — loopback lease service.

Owns the server pool; pipelines lease an egress instead of touching the
system VPN. Phase 1: subscription parsing + direct-mode leases (domestic
targets like AvalAI need no tunnel and no VPN) + Bearer auth. Phase 2
(xray children per server + 429 rotation) hooks into lease/report.

Contract lock 2026-09-06: B1 tools/egress, B2 loopback HTTP lease/report,
B3 secrets in tools/egress/.env (EGRESS_SUB_URL, EGRESS_SUP_TOKEN).

Endpoints (127.0.0.1 only):
  GET  /v1/health                          -> {ok, servers, leases}
  POST /v1/lease  {target}                 -> {lease_id, mode, proxy_url,
                                              egress_ip}
  POST /v1/report {lease_id, outcome}      -> {action}
Targets: "direct" (no tunnel) or "zen" (needs a tunnel; phase 1 parks
with a clear message when no tunnel backend exists).
Outcomes: ok | http429 | net_err | auth_err.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

ENV_PATH = pathlib.Path(__file__).resolve().parent / ".env"
SUB_VAR = "EGRESS_SUB_URL"
TOKEN_VAR = "EGRESS_SUP_TOKEN"
DEFAULT_PORT = 18789


def load_env():
    data = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip("'\"")
    for k in (SUB_VAR, TOKEN_VAR):
        if k in os.environ and os.environ[k]:
            data[k] = os.environ[k]
    return data


def parse_subscription(text):
    """Parse a v2ray subscription body into [{scheme, host, port, id}]."""
    servers = []
    blob = (text or "").strip()
    if not blob:
        return servers
    try:
        blob = base64.b64decode(blob + "=" * (-len(blob) % 4)).decode(
            "utf-8", "replace")
    except (ValueError, binascii.Error):
        pass
    for line in blob.splitlines():
        line = line.strip()
        if "://" not in line:
            continue
        scheme, rest = line.split("://", 1)
        scheme = scheme.lower()
        if scheme not in ("vmess", "vless", "trojan", "ss", "ssr"):
            continue
        host, port = "", 0
        try:
            if scheme == "vmess":
                payload = json.loads(base64.b64decode(
                    rest + "=" * (-len(rest) % 4)).decode("utf-8",
                                                          "replace"))
                host, port = payload.get("add", ""), int(
                    payload.get("port", 0) or 0)
            else:
                at = rest.rfind("@")
                hp = rest[at + 1:].split("?")[0].split("#")[0].split("/")
                host = hp[0].rsplit(":", 1)[0] if hp else ""
                try:
                    port = int(hp[0].rsplit(":", 1)[1]) if hp else 0
                except (ValueError, IndexError):
                    port = 0
        except (ValueError, KeyError, IndexError):
            continue
        if host:
            servers.append({"scheme": scheme, "host": host, "port": port,
                            "id": hashlib.sha256(
                                line.encode()).hexdigest()[:8]})
    return servers


class Pool:
    """Ranked server pool with cooldowns. Thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self.servers = []
        self.cooldown_until = {}
        self.leases = {}

    def load(self, servers):
        with self._lock:
            known = {s["id"] for s in self.servers}
            for s in servers:
                if s["id"] not in known:
                    self.servers.append(dict(s))
                    known.add(s["id"])

    def lease(self, target):
        with self._lock:
            now = time.time()
            if target == "direct":
                lid = secrets.token_hex(8)
                self.leases[lid] = {"mode": "direct", "server": None,
                                    "since": now}
                return {"lease_id": lid, "mode": "direct", "proxy_url": "",
                        "egress_ip": "direct"}
            avail = [s for s in self.servers
                     if self.cooldown_until.get(s["id"], 0) <= now]
            if not avail:
                return {"error": "park",
                        "message": "no tunnel backend in phase 1: "
                                   "use target=direct (AvalAI/domestic) "
                                   "or wait for phase 2 (xray children)"}
            s = avail[0]
            lid = secrets.token_hex(8)
            self.leases[lid] = {"mode": "tunnel", "server": s["id"],
                                "since": now}
            return {"lease_id": lid, "mode": "tunnel-pending",
                    "proxy_url": "", "egress_ip": s["host"],
                    "server_id": s["id"],
                    "note": "phase 2 wires the xray child proxy here"}

    def report(self, lease_id, outcome):
        with self._lock:
            lease = self.leases.get(lease_id)
            if lease is None:
                return {"action": "unknown-lease"}
            if outcome == "http429" and lease.get("server"):
                self.cooldown_until[lease["server"]] = time.time() + 300
                return {"action": "switch"}
            if outcome in ("net_err",):
                return {"action": "switch"}
            if outcome == "auth_err":
                # Rejected credentials never succeed on retry: retire the
                # lease so the caller re-authenticates instead of looping.
                self.leases.pop(lease_id, None)
                return {"action": "reauth"}
            return {"action": "keep"}

    def health(self):
        with self._lock:
            return {"ok": True, "servers": len(self.servers),
                    "leases": len(self.leases)}


POOL = Pool()
TOKEN = ""


class Handler(BaseHTTPRequestHandler):
    server_version = "EgressSup/1"

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if not TOKEN:
            return False
        auth = self.headers.get("Authorization", "")
        return hmac.compare_digest(auth, "Bearer " + TOKEN)

    def do_GET(self):
        if self.path != "/v1/health":
            return self._send(404, {"error": "not-found"})
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        return self._send(200, POOL.health())

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = 0
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8")
                              or "{}")
        except ValueError:
            return self._send(400, {"error": "bad-json"})
        if self.path == "/v1/lease":
            return self._send(200, POOL.lease(data.get("target", "")))
        if self.path == "/v1/report":
            return self._send(200, POOL.report(data.get("lease_id", ""),
                                               data.get("outcome", "")))
        return self._send(404, {"error": "not-found"})

    def log_message(self, *args):  # quieter stdout; rolling log is phase 2
        pass


def refresh_subscription(env):
    sub = env.get(SUB_VAR, "")
    if sub.startswith("http"):
        try:
            with urllib.request.urlopen(sub, timeout=30) as resp:
                sub = resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 (refresh is best-effort)
            print("subscription refresh failed: %s" % exc)
            return
    POOL.load(parse_subscription(sub))


def main(argv=None):
    global TOKEN
    import argparse
    ap = argparse.ArgumentParser(description="Egress supervisor (phase 1)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--gen-token", action="store_true",
                    help="print a fresh token and exit")
    args = ap.parse_args(argv)
    if args.gen_token:
        print(secrets.token_hex(24))
        return 0
    env = load_env()
    TOKEN = env.get(TOKEN_VAR, "")
    if not TOKEN:
        print("missing %s in %s (run --gen-token, paste it there)"
              % (TOKEN_VAR, ENV_PATH))
        return 2
    refresh_subscription(env)
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print("egress supervisor on 127.0.0.1:%d (%d servers)" % (
        args.port, POOL.health()["servers"]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
