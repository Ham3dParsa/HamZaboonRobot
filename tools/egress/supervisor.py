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
                                              egress_ip, provider, target}
  POST /v1/report {lease_id, outcome, provider?} -> {action}
Targets (TARGETS table): "direct" (no tunnel, provider None),
"avalai" (domestic: no tunnel, provider avalai), "zen" / "google" /
"openrouter" (tunnel, one provider each; "zen" is the historic tunnel
name and keeps working unchanged). Unknown targets park.
Outcomes: ok | http429 | net_err | auth_err | unknown (unknown keeps).
Cooldowns are per (server, provider): a 429 on zen never blocks google
on the same server. report() cools the lease's provider unless the
payload overrides it.
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
SUBS_VAR = "EGRESS_SUB_URLS"
TOKEN_VAR = "EGRESS_SUP_TOKEN"
DEFAULT_PORT = 18789
PROBE_TOP_N = 20
PROBE_TIMEOUT_S = 5.0
POOL_PATH = pathlib.Path(__file__).resolve().parent / "egress_pool.json"
COOLDOWN_S = 300


def norm_provider(provider):
    """Canonical provider key: lowercase, stripped, "" when absent."""
    return str(provider or "").strip().lower()


def norm_target(target):
    """Canonical target key: lowercase, stripped."""
    return str(target or "").strip().lower()


def target_spec(target):
    """TARGETS row for a lease target, or None when unknown."""
    return TARGETS.get(norm_target(target))


def known_provider(provider):
    """True when ``provider`` is a TARGETS provider (or absent/None).

    Guards the cooldown table: an arbitrary caller-supplied string must
    never mint junk (server, provider) keys.
    """
    if provider is None:
        return True
    want = norm_provider(provider)
    return any(spec["provider"] is not None
               and norm_provider(spec["provider"]) == want
               for spec in TARGETS.values())


def load_env():
    data = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip("'\"")
    for k in (SUB_VAR, SUBS_VAR, TOKEN_VAR):
        if k in os.environ and os.environ[k]:
            data[k] = os.environ[k]
    return data


def sub_sources(env):
    """All subscription sources: plural var (newline/whitespace separated)
    plus the legacy singular var. Commas are NOT split points (legal in
    URLs). Order preserved, empties dropped."""
    out = []
    for chunk in (env.get(SUBS_VAR, "") or "").split():
        chunk = chunk.strip()
        if chunk and chunk not in out:
            out.append(chunk)
    single = (env.get(SUB_VAR, "") or "").strip()
    if single and single not in out:
        out.append(single)
    return out


def parse_subscription(text):
    """Parse a v2ray subscription body into [{scheme, host, port, id}].

    One poisoned line never aborts the source: xrayconf.parse_link is
    the single parser (ValueError contract) and every per-line failure
    is skipped.
    """
    try:
        from . import xrayconf as _xc
    except ImportError:
        import xrayconf as _xc
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
        try:
            node = _xc.parse_link(line)
        except Exception:  # noqa: BLE001 (skip poisoned lines)
            continue
        servers.append({"scheme": node["scheme"], "host": node["address"],
                        "port": node["port"],
                        "id": hashlib.sha256(
                            line.encode()).hexdigest()[:8],
                        "link": line})
    return servers


class Pool:
    """Ranked server pool with per-(server, provider) cooldowns.

    Thread-safe (RLock: cool()/is_cool() are called both directly and
    from inside lease()/report() while the lock is held).
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.servers = []
        self.cooldown_until = {}
        self.leases = {}

    def load(self, servers):
        with self._lock:
            known = {s["id"] for s in self.servers if isinstance(s, dict)}
            for s in servers:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                if s["id"] not in known:
                    self.servers.append(dict(s))
                    known.add(s["id"])

    def load_ranked(self, ranked):
        """Replace pool order with a ranked probe list (whitelist)."""
        with self._lock:
            by_id = {s["id"]: s for s in self.servers
                     if isinstance(s, dict) and s.get("id")}
            ordered = []
            for row in ranked or []:
                if not isinstance(row, dict):
                    continue
                hit = by_id.get(row.get("id"))
                if row.get("alive") and hit is not None:
                    ordered.append(hit)
            for s in self.servers:
                if s["id"] not in {r["id"] for r in ordered}:
                    ordered.append(s)
            self.servers = ordered

    def save_pool(self, path=POOL_PATH):
        import datetime as _dt
        with self._lock:
            payload = {"saved_at": _dt.datetime.now(
                _dt.timezone.utc).isoformat(),
                # links carry credentials: never persisted, only
                # host/port/scheme/id (relink on refresh).
                "servers": [{k: s[k] for k in
                              ("scheme", "host", "port", "id")
                              if k in s} for s in self.servers]}
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        except OSError as exc:
            print("pool save failed: %s" % exc)

    def load_pool(self, path=POOL_PATH):
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return 0
        servers = payload.get("servers") if isinstance(payload, dict) \
            else None
        if not isinstance(servers, list):
            return 0
        valid = [s for s in servers
                 if isinstance(s, dict) and s.get("id")
                 and s.get("host") and s.get("port")]
        self.load(valid)
        # Restore the saved rank order (load() only appends).
        order = [s["id"] for s in valid]
        with self._lock:
            rank = {sid: idx for idx, sid in enumerate(order)}
            self.servers.sort(
                key=lambda s: rank.get(s.get("id"), len(order)))
        return len(valid)

    def cool(self, server_id, provider=None, seconds=COOLDOWN_S):
        """Mark (server, provider) as cooling for ``seconds``.

        The ONLY writer of cooldown_until (lease/report/rotate/probes
        all route through here). Falsy server_id is a no-op.
        """
        if not server_id:
            return
        with self._lock:
            self.cooldown_until[(server_id,
                                 norm_provider(provider))] = \
                time.time() + seconds

    def is_cool(self, server_id, provider=None, now=None):
        """True while (server, provider) is still cooling (unusable).

        The ONLY reader of cooldown_until for availability. ``now``
        is injectable for hermetic tests.
        """
        if not server_id:
            return False
        if now is None:
            now = time.time()
        with self._lock:
            return self.cooldown_until.get(
                (server_id, norm_provider(provider)), 0) > now

    def provider_of(self, lease_id):
        """Provider recorded on a lease, or None for unknown leases."""
        with self._lock:
            lease = self.leases.get(lease_id)
            return lease.get("provider") if lease else None

    def discard_lease(self, lease_id):
        """Drop a minted lease (acquire-failure cleanup) under the lock."""
        with self._lock:
            self.leases.pop(lease_id, None)

    def lease(self, target):
        with self._lock:
            now = time.time()
            spec = target_spec(target)
            if spec is None:
                return {"error": "park",
                        "message": "unknown target %r (want one of: %s)"
                                   % (target, ", ".join(TARGETS))}
            name = norm_target(target)
            if not spec["tunnel"]:
                lid = secrets.token_hex(8)
                self.leases[lid] = {"mode": "direct", "server": None,
                                    "since": now,
                                    "provider": spec["provider"],
                                    "target": name}
                return {"lease_id": lid, "mode": "direct", "proxy_url": "",
                        "egress_ip": "direct",
                        "provider": spec["provider"], "target": name}
            avail = [s for s in self.servers
                     if not self.is_cool(s["id"], spec["provider"], now)
                     and s.get("link")]
            if not avail:
                return {"error": "park",
                        "message": "no link-bearing server available "
                                   "(refresh the subscription)"}
            s = avail[0]
            lid = secrets.token_hex(8)
            self.leases[lid] = {"mode": "tunnel", "server": s["id"],
                                "since": now, "provider": spec["provider"],
                                "target": name}
            return {"lease_id": lid, "mode": "tunnel",
                    "server_id": s["id"], "provider": spec["provider"],
                    "target": name}

    def report(self, lease_id, outcome, provider=None):
        with self._lock:
            lease = self.leases.get(lease_id)
            if lease is None:
                return {"action": "unknown-lease"}
            if not known_provider(provider):
                # Unvalidated provider strings must never mint cooldown
                # keys: ignore the outcome, keep the lease.
                return {"action": "keep"}
            eff = norm_provider(provider) if provider is not None \
                else lease.get("provider")
            if outcome == "http429" and lease.get("server"):
                self.cool(lease["server"], eff)
                return {"action": "switch"}
            if outcome in ("net_err",):
                return {"action": "switch"}
            if outcome == "auth_err":
                # Rejected credentials never succeed on retry: retire the
                # lease so the caller re-authenticates instead of looping.
                self.leases.pop(lease_id, None)
                return {"action": "reauth"}
            # "unknown" (e.g. child exit code with no network signal):
            # keep the lease, cool nothing. App failure is not proof of
            # a bad egress.
            return {"action": "keep"}

    def health(self):
        with self._lock:
            return {"ok": True, "servers": len(self.servers),
                    "leases": len(self.leases)}


class TunnelOwner:
    """Single active xray tunnel, owned by the supervisor process.

    lease("zen") starts the best available server's tunnel and returns
    its proxy_url + verified egress IP; report(http429) stops it, cools
    the server down, and the next lease starts the next server. One
    egress at a time (owner's choice: predictable, no parallel burn).
    """

    def __init__(self, pool):
        self._pool = pool
        self._lock = threading.Lock()
        self._tunnel = None
        self._server_id = None

    def acquire(self, provider=None):
        """Start (or reuse) the tunnel for the best server. Returns
        (proxy_url, egress_ip, server_id) or raises RuntimeError.

        Availability skips only servers cooling for ``provider``: a
        zen-429 never blocks a google lease on the same server.
        """
        try:
            from . import tunnel as _tunnel_mod
        except ImportError:  # top-level script run
            import tunnel as _tunnel_mod
        with self._lock:
            now = time.time()
            avail = [s for s in self._pool.servers
                     if not self._pool.is_cool(s["id"], provider, now)
                     and s.get("link")]
            if not avail:
                raise RuntimeError("no link-bearing server available")
            if self._tunnel is not None and self._server_id == avail[0]["id"] \
                    and self._tunnel.proc is not None \
                    and self._tunnel.proc.poll() is None:
                return (self._tunnel.proxy_url,
                        self._tunnel.egress_ip(), self._server_id)
            self._drop_locked()
            server = avail[0]
            tun = _tunnel_mod.Tunnel(server, server["link"])
            proxy = tun.start()
            try:
                ip = tun.egress_ip()
            except Exception:
                tun.stop()
                raise RuntimeError("tunnel up but egress check failed")
            self._tunnel = tun
            self._server_id = server["id"]
            return proxy, ip, server["id"]

    def rotate(self, reason="", provider=None):
        """Stop the current tunnel (429/quit); next acquire() moves on.

        Cools the stopped server for ``provider`` via Pool.cool().
        """
        with self._lock:
            if self._server_id:
                self._pool.cool(self._server_id, provider)
            self._drop_locked()

    def _drop_locked(self):
        if self._tunnel is not None:
            try:
                self._tunnel.stop()
            except Exception:  # noqa: BLE001 (stop must not raise)
                pass
            self._tunnel = None
            self._server_id = None

    def stop(self):
        with self._lock:
            self._drop_locked()


POOL = Pool()
TUNNELS = TunnelOwner(POOL)
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
            data = POOL.lease(data.get("target", ""))
            if data.get("mode") == "tunnel":
                try:
                    proxy, ip, _sid = TUNNELS.acquire(
                        provider=data.get("provider"))
                except (RuntimeError, ValueError, OSError) as exc:
                    # Acquire failed: drop the minted lease (no orphan
                    # records) and park with a message.
                    POOL.discard_lease(data.get("lease_id", ""))
                    return self._send(200, {"error": "park",
                                            "message": str(exc)})
                data["proxy_url"] = proxy
                data["egress_ip"] = ip
            return self._send(200, data)
        if self.path == "/v1/report":
            res = POOL.report(data.get("lease_id", ""),
                              data.get("outcome", ""),
                              data.get("provider"))
            if res.get("action") == "switch":
                TUNNELS.rotate("reported " + str(data.get("outcome", "")),
                               provider=data.get("provider")
                               if data.get("provider") is not None
                               else POOL.provider_of(data.get("lease_id",
                                                              "")))
            return self._send(200, res)
        return self._send(404, {"error": "not-found"})

    def log_message(self, *args):  # quieter stdout; rolling log is phase 2
        pass


def fetch_sub(url):
    """Fetch a subscription URL with a browser UA (raw hosts 403 the
    default urllib agent)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def refresh_subscription(env):
    for src in sub_sources(env):
        body = src
        if body.startswith("http"):
            try:
                body = fetch_sub(body)
            except Exception:  # noqa: BLE001 (best-effort; URL is secret)
                print("subscription refresh failed (network error)")
                continue
        POOL.load(parse_subscription(body))


def tcp_ping(host, port, timeout=PROBE_TIMEOUT_S):
    """TCP handshake latency in ms, or None when unreachable."""
    import socket as _socket
    import time as _time
    try:
        port = int(port or 0)
    except (TypeError, ValueError):
        return None
    if not host or not port:
        return None
    start = _time.time()
    try:
        conn = _socket.create_connection((host, port), timeout=timeout)
    except Exception:  # noqa: BLE001 (best-effort probe: any failure = dead)
        return None
    try:
        conn.close()
    except OSError:
        pass
    return int((_time.time() - start) * 1000)


def _proxy_opener(proxy_url):
    """Explicit proxy opener (Request.set_proxy is dead on the shared
    global opener — verified live)."""
    return urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": proxy_url, "https": proxy_url}))


def zen_probe(proxy_url, api_key, timeout=60):
    """One minimal Zen call through proxy_url. Returns (code, ms, note)."""
    import time as _time
    body = json.dumps({
        "model": "muse-spark-1.3-contributor-free",
        "input": "Reply with the single word: ok",
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 16,
    }).encode()
    req = urllib.request.Request(
        "https://opencode.ai/zen/v1/responses", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key,
                 "User-Agent": "HamZaban-factory/1.0"})
    opener = _proxy_opener(proxy_url)
    start = _time.time()
    try:
        with opener.open(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            return code, int((_time.time() - start) * 1000), "live"
    except Exception as exc:  # noqa: BLE001 (probe reports, not raises)
        ms = int((_time.time() - start) * 1000)
        raw = getattr(exc, "code", "?")
        code = raw if isinstance(raw, int) and not isinstance(raw, bool) \
            else "?"
        hint = {429: "quota out", 401: "bad key",
                403: "forbidden"}.get(code, "net/unknown")
        return code, ms, hint


GOOGLE_MODELS_URL = ("https://generativelanguage.googleapis.com/"
                      "v1beta/models?pageSize=1&key=")


def google_probe(proxy_url, api_key, timeout=60, opener=None):
    """One free models:list call through proxy_url. Returns (code, ms,
    note): live | location-blocked (sanctioned egress country) |
    bad-key | bad-request | forbidden | quota | net/unknown.

    ``code`` is ``int`` for HTTP responses and ``"?"`` for non-HTTP
    failures (DNS/timeout/refused); callers must ``==``-compare ints
    only and ``%s``-format for display."""
    import time as _time
    open_fn = opener or _proxy_opener(proxy_url)
    req = urllib.request.Request(
        GOOGLE_MODELS_URL + api_key.strip(),
        headers={"User-Agent": "HamZaban-factory/1.0"})
    start = _time.time()
    try:
        with open_fn.open(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            return code, int((_time.time() - start) * 1000), "live"
    except Exception as exc:  # noqa: BLE001 (probe reports, not raises)
        ms = int((_time.time() - start) * 1000)
        raw = getattr(exc, "code", "?")
        code = raw if isinstance(raw, int) and not isinstance(raw, bool) \
            else "?"
        body = ""
        try:
            body = (exc.read(2048) or b"").decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 (body is best-effort)
            pass
        if code == 400 and "not supported for the API use" in body:
            return code, ms, "location-blocked"
        if code == 400 and ("API key not valid" in body
                            or "API_KEY_INVALID" in body):
            return code, ms, "bad-key"
        hint = {400: "bad-request", 401: "bad-key", 403: "forbidden",
                429: "quota"}.get(code, "net/unknown")
        return code, ms, hint


def geo_country(proxy_url, ip, timeout=15, opener=None):
    """Egress country via ip-api (best-effort, '?' on failure).

    NOTE: free tier is http-only, so the egress IP is visible on the
    wire by design (factory diagnostics, not learner traffic)."""
    if not ip:
        return "?"
    open_fn = opener or _proxy_opener(proxy_url)
    req = urllib.request.Request(
        "http://ip-api.com/json/%s?fields=country"
        % urllib.parse.quote(str(ip), safe=""),
        headers={"User-Agent": "HamZaban-factory/1.0"})
    try:
        with open_fn.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
            return data.get("country") or "?"
    except Exception:  # noqa: BLE001 (best-effort label)
        return "?"


# Canonical lease-target table (C4b): the single owner of target ->
# provider/tunnel/probe mapping. ``tunnel`` False = direct mode (no
# server, domestic); True = tunnel mode (needs a link-bearing server).
# ``probe`` is the per-target liveness fn, or None when TCP ranking is
# all there is (no probe exists for that provider yet). "zen" is the
# historic tunnel name: it keeps leasing tunnels unchanged.
TARGETS = {
    "direct": {"provider": None, "tunnel": False, "probe": None},
    "zen": {"provider": "zen", "tunnel": True, "probe": zen_probe},
    "google": {"provider": "google", "tunnel": True,
               "probe": google_probe},
    "openrouter": {"provider": "openrouter", "tunnel": True,
                   "probe": None},
    "avalai": {"provider": "avalai", "tunnel": False, "probe": None},
}


def probe_pool(top_n=PROBE_TOP_N, workers=20):
    """Rank pool servers by TCP latency; Zen-liveness needs a tunnel
    (phase 2) so it is NOT probed here — ranking is reachability only,
    and live 429 feedback (report/cooldown) does the rest at runtime.
    Probes run concurrently (sequential 5s timeouts would hang on big
    subscription lists)."""
    import concurrent.futures as _fut
    servers = list(POOL.servers)

    def one(server):
        ms = tcp_ping(server.get("host"), server.get("port"))
        return (ms if ms is not None else 10 ** 9, server)

    with _fut.ThreadPoolExecutor(max_workers=workers) as pool:
        future_of = {pool.submit(one, s): s for s in servers
                     if isinstance(s, dict)}
        ranked = []
        done = 0
        for future in _fut.as_completed(future_of):
            done += 1
            ms, server = future.result()
            if not isinstance(server, dict) or not server.get("id") \
                    or not server.get("host") or not server.get("port"):
                continue
            print("\rprobing %d/%d: %s:%s %s" % (
                done, len(servers), server.get("host"),
                server.get("port"),
                ("%dms" % ms) if ms < 10 ** 9 else "dead"),
                end="", flush=True)
            ranked.append((ms, server))
        print("")
        ranked.sort(key=lambda pair: pair[0])
    return [{"host": s["host"], "port": s["port"], "scheme": s["scheme"],
             "id": s["id"],
             "latency_ms": (None if ms >= 10 ** 9 else ms),
             "alive": ms < 10 ** 9,
             "zen_candidate": idx < top_n and ms < 10 ** 9}
            for idx, (ms, s) in enumerate(ranked)]


def main(argv=None):
    global TOKEN
    import argparse
    ap = argparse.ArgumentParser(description="Egress supervisor (phase 1)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--gen-token", action="store_true",
                    help="print a fresh token and exit")
    ap.add_argument("--probe", action="store_true",
                    help="rank pool servers by TCP latency and exit "
                         "(top-N marked zen_candidate)")
    ap.add_argument("--top-n", type=int, default=PROBE_TOP_N)
    ap.add_argument("--probe-zen", type=int, default=0, metavar="N",
                    help="tunnel the top-N alive servers one by one and "
                         "take one real Zen ping each (needs --zen-key "
                         "or ZEN_API_KEY env). Slow by design.")
    ap.add_argument("--zen-key", default="",
                    help="Zen API key for --probe-zen (or ZEN_API_KEY env)")
    ap.add_argument("--probe-google", type=int, default=0, metavar="N",
                    help="tunnel the top-N alive servers one by one and "
                         "take one free Google models:list ping each "
                         "(needs --google-key, GOOGLE_AI_API_KEY env, or "
                         "tools/egress/.env). Google-ok servers move to "
                         "the front of the whitelist, so serve mode "
                         "leases them first. Slow by design.")
    ap.add_argument("--google-key", default="",
                    help="Google AI key for --probe-google (or "
                         "GOOGLE_AI_API_KEY env)")
    args = ap.parse_args(argv)
    if args.gen_token:
        print(secrets.token_hex(24))
        return 0
    env = load_env()
    if args.probe:
        refresh_subscription(env)
        rows = probe_pool(top_n=args.top_n)
        alive = [r for r in rows if r["alive"]]
        print("servers=%d alive=%d (top-%d marked *)" % (
            len(rows), len(alive), args.top_n))
        for row in rows:
            if not row["alive"]:
                continue
            mark = "*" if row["zen_candidate"] else " "
            print("%s %-5s %-40s %dms" % (
                mark, row["scheme"],
                "%s:%s" % (row["host"], row["port"]),
                row["latency_ms"]))
        POOL.load_ranked(rows)
        if alive:
            POOL.save_pool()
            print("whitelist saved: %d servers -> %s" % (
                len(POOL.servers), POOL_PATH))
        else:
            # Never overwrite a good whitelist with an empty probe
            # (failed refresh / dead network). Old file stays intact.
            print("probe found 0 alive servers: whitelist NOT overwritten")
        if args.probe_zen:
            key = args.zen_key or os.environ.get("ZEN_API_KEY", "")
            if not key:
                print("probe-zen needs --zen-key or ZEN_API_KEY env")
                return 2
            try:
                from . import tunnel as _tunnel_mod
            except ImportError:
                import tunnel as _tunnel_mod
            cands = [r for r in rows if r["alive"]][
                :max(0, args.probe_zen)]
            print("zen ping: %d tunneled servers" % len(cands))
            for idx, row in enumerate(cands, 1):
                server = next((s for s in POOL.servers
                               if s["id"] == row["id"] and s.get("link")),
                              None)
                if server is None:
                    print("[%d/%d] %s: no link (relink)" % (
                        idx, len(cands), row["host"]))
                    continue
                tun = None
                try:
                    tun = _tunnel_mod.Tunnel(server, server["link"])
                    proxy = tun.start()
                    ip = tun.egress_ip()
                    code, ms, note = TARGETS["zen"]["probe"](proxy, key)
                    print("[%d/%d] %s -> egress %s zen=%s %dms (%s)" % (
                        idx, len(cands), row["host"], ip, code, ms,
                        note))
                    if code == 429:
                        POOL.cool(server["id"], "zen")
                except Exception as exc:  # noqa: BLE001 (per-server)
                    print("[%d/%d] %s: tunnel failed (%s)" % (
                        idx, len(cands), row["host"], exc))
                finally:
                    if tun is not None:
                        tun.stop()
            if alive:
                # Same empty-probe rule as above: never overwrite a good
                # whitelist after a probe that found 0 alive servers.
                POOL.save_pool()
            else:
                print("zen probe skipped: whitelist NOT overwritten")
        if args.probe_google:
            key = args.google_key or os.environ.get(
                "GOOGLE_AI_API_KEY", "") or env.get(
                    "GOOGLE_AI_API_KEY", "")
            if not key:
                print("probe-google needs --google-key, GOOGLE_AI_API_KEY "
                      "env, or tools/egress/.env")
                return 2
            try:
                from . import tunnel as _tunnel_mod
            except ImportError:
                import tunnel as _tunnel_mod
            cands = [r for r in rows if r["alive"]][
                :max(0, args.probe_google)]
            print("google ping: %d tunneled servers" % len(cands))
            good = []
            for idx, row in enumerate(cands, 1):
                server = next((s for s in POOL.servers
                               if s["id"] == row["id"] and s.get("link")),
                              None)
                if server is None:
                    print("[%d/%d] %s: no link (relink)" % (
                        idx, len(cands), row["host"]))
                    continue
                tun = None
                try:
                    tun = _tunnel_mod.Tunnel(server, server["link"])
                    proxy = tun.start()
                    ip = tun.egress_ip()
                    code, ms, note = TARGETS["google"]["probe"](proxy,
                                                                key)
                    country = geo_country(proxy, ip) \
                        if note == "live" else "?"
                    print("[%d/%d] %s -> egress %s (%s) google=%s "
                          "%dms (%s)" % (
                              idx, len(cands), row["host"], ip,
                              country, code, ms, note))
                    if note == "live":
                        good.append(row["id"])
                except Exception as exc:  # noqa: BLE001 (per-server)
                    print("[%d/%d] %s: tunnel failed (%s)" % (
                        idx, len(cands), row["host"], exc))
                finally:
                    if tun is not None:
                        tun.stop()
            if good:
                ranked = [r for r in rows
                          if r["id"] in good and r["alive"]]
                ranked += [r for r in rows if r["id"] not in good]
                POOL.load_ranked(ranked)
                POOL.save_pool()
                print("google-ok first: %d servers -> %s" % (
                    len(good), POOL_PATH))
            else:
                print("no google-ok server found")
        return 0
    TOKEN = env.get(TOKEN_VAR, "")
    if not TOKEN:
        print("missing %s in %s (run --gen-token, paste it there)"
              % (TOKEN_VAR, ENV_PATH))
        return 2
    refresh_subscription(env)
    n_saved = POOL.load_pool()
    if n_saved:
        print("pool loaded: %d servers from whitelist" % n_saved)
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print("egress supervisor on 127.0.0.1:%d (%d servers)" % (
        args.port, POOL.health()["servers"]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        TUNNELS.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
