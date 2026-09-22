"""Egress supervisor (Design B, phase 1) — loopback lease service.

Owns the server pool; pipelines lease an egress instead of touching the
system VPN. Phase 1: subscription parsing + direct-mode leases (domestic
targets like AvalAI need no tunnel and no VPN) + Bearer auth. Phase 2
(xray children per server + 429 rotation) hooks into lease/report.

Contract lock 2026-09-06: B1 tools/egress, B2 loopback HTTP lease/report,
B3 secrets in tools/egress/.env (EGRESS_SUB_URL, EGRESS_SUP_TOKEN).

Endpoints (127.0.0.1 only):
  GET  /v1/health                          -> {ok, servers, leases, healthy}
  POST /v1/lease  {target}                 -> {lease_id, mode, proxy_url,
                                              egress_ip, provider, target}
  POST /v1/report {lease_id, outcome, provider?} -> {action}
Targets (TARGETS table, owned by factory/precard/provider_lease_policy.py
and imported
here — this module only attaches its live zen/google probe functions):
"direct" (no tunnel, provider None),
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
import concurrent.futures
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

try:
    from factory.precard.provider_lease_policy import (
        CLEAN_CACHE_TTL_S,
        TARGETS,
        NetConfig,
        build_probe_rows,
        clean_cache_candidates,
        default_clean_cache_path,
        direct_probe_event,
        format_cache_line,
        known_provider,
        lease_for,
        load_clean_cache,
        norm_provider,
        norm_target,
        order_google_first,
        order_pool_by_rank,
        record_clean_success,
        save_clean_cache,
        should_save_whitelist,
        supervisor_health,
        target_spec,
        write_pool_file,
    )
    from factory.precard.provider_lease_policy import cool as net_cool
except ImportError:  # top-level script run: repo root is not on sys.path
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent
                             .parent.parent))
    from factory.precard.provider_lease_policy import (
        CLEAN_CACHE_TTL_S,
        TARGETS,
        NetConfig,
        build_probe_rows,
        clean_cache_candidates,
        default_clean_cache_path,
        direct_probe_event,
        format_cache_line,
        known_provider,
        lease_for,
        load_clean_cache,
        norm_provider,
        norm_target,
        order_google_first,
        order_pool_by_rank,
        record_clean_success,
        save_clean_cache,
        should_save_whitelist,
        supervisor_health,
        target_spec,
        write_pool_file,
    )
    from factory.precard.provider_lease_policy import cool as net_cool

ENV_PATH = pathlib.Path(__file__).resolve().parent / ".env"
SUB_VAR = "EGRESS_SUB_URL"
SUBS_VAR = "EGRESS_SUB_URLS"
TOKEN_VAR = "EGRESS_SUP_TOKEN"
DEFAULT_PORT = 18789
PROBE_TOP_N = 20
PROBE_TIMEOUT_S = 5.0
POOL_PATH = pathlib.Path(__file__).resolve().parent / "egress_pool.json"
CLEAN_CACHE_PATH = (
    pathlib.Path(__file__).resolve().parent / "clean_cache.json")
COOLDOWN_S = 300

# Env knobs for the R7 cache-first lease path (phase 03). Secret-free:
# a TTL float and a cache-file path only (keys never ride env reads
# here — probe_key owns key resolution). run.py forwards the resolved
# --clean-ttl/--cache into auto-spawned supervisors through these; a
# running supervisor keeps whatever env it started with.
CLEAN_TTL_VAR = "EGRESS_CLEAN_TTL"
CLEAN_CACHE_PATH_VAR = "EGRESS_CLEAN_CACHE_PATH"

# R7 lease-path probe budget (phase 03): /v1/lease runs on the
# single-threaded HTTPServer handler, so cache pings are capped in
# count (fastest-first) and time — excess rows fall through to the
# classic pick instead of stalling leases/health for N x timeout.
LEASE_PING_TIMEOUT_S = 2.0
LEASE_PING_MAX_ROWS = 3


def _clean_ttl_from_env():
    """Supervisor-side cache TTL: EGRESS_CLEAN_TTL when finite and
    positive, else CLEAN_CACHE_TTL_S (the net home default). Garbage
    never raises and never disables expiry (an unset/unparseable var
    is the default window, not infinity)."""
    try:
        value = float(os.environ.get(CLEAN_TTL_VAR, "") or 0)
    except (TypeError, ValueError):
        return CLEAN_CACHE_TTL_S
    if not (value > 0) or not (value < float("inf")):
        return CLEAN_CACHE_TTL_S
    return value


def _clean_cache_path():
    """Effective clean-cache file: EGRESS_CLEAN_CACHE_PATH when set
    (an explicit --cache forwarded at spawn), else the beside-pool
    default. Never empty (empty falls back to the default)."""
    try:
        raw = (os.environ.get(CLEAN_CACHE_PATH_VAR, "") or "").strip()
    except AttributeError:
        raw = ""
    return raw or str(CLEAN_CACHE_PATH)


def _server_tcp_ping(server, timeout=LEASE_PING_TIMEOUT_S):
    """net.lease_for ping_fn over the PR-0 TCP probe (seam untouched:
    passed as a callable, internals unchanged). Truthy ms means
    reachable; None means dead (a 0 ms loopback reads as dead and
    costs one full probe — deferred OC [info], left alone).
    ``timeout`` is the lease-path budget (2s), not the 5s probe
    default: the single-threaded /v1/lease handler must never stall
    N x 5s on dead rows."""
    return tcp_ping(server.get("host"), server.get("port"), timeout)


# Append-only lease audit (R10): every lease/report decision appends one
# JSON line here (never rewritten, never truncated by this module).
# Secret-free by construction: lease ids truncate to 8 chars (same as
# the console line), proxy URLs and keys are never recorded. Probe
# logic is untouched (parallel PR-0 owns it).
# Retention (enforced): the file has no reader inside the repo — audit
# only, every line self-contained with its own ts — so on startup it
# is trimmed to the newest LEASES_TAIL_LINES lines (atomic tmp+replace,
# best-effort, never fails startup; per-lease appends stay O(1) and it
# is still safe to rotate/truncate/delete externally at any time).
LEASES_PATH = pathlib.Path(__file__).resolve().parent / "leases.jsonl"
LEASES_TAIL_LINES = 20000
_LEASES_TRIM_BYTES = 2000000


def _append_lease_event(event):
    """Append one lease/report audit line (best-effort, never raises).

    The supervisor must never fail a lease or report because the audit
    file is unwritable — IO errors are swallowed silently (the lease /
    report result itself is the contract, the audit line is not).
    ``LEASES_PATH`` is module-level so hermetic tests can point it at
    tmp_path.
    """
    try:
        import datetime as _dt
        rec = {"ts": _dt.datetime.now(_dt.timezone.utc).isoformat()}
        rec.update(dict(event or {}))
        with open(LEASES_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except (OSError, ValueError, TypeError):
        pass


def _trim_leases_file():
    """Trim leases.jsonl to the newest LEASES_TAIL_LINES (best-effort).

    Startup-only upkeep so a long-lived supervisor grows disk bounded:
    files under _LEASES_TRIM_BYTES are untouched (no read cost);
    larger ones keep their newest lines via atomic tmp+replace. Never
    raises — audit upkeep must never fail startup or a lease/report.
    """
    try:
        if LEASES_PATH.stat().st_size <= _LEASES_TRIM_BYTES:
            return
    except OSError:
        return
    try:
        lines = LEASES_PATH.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return
    if len(lines) <= LEASES_TAIL_LINES:
        return
    tmp = str(LEASES_PATH) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines[-LEASES_TAIL_LINES:]) + "\n")
        os.replace(tmp, LEASES_PATH)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def note_clean_success(server_id, provider, latency_ms, now=None,
                       path=CLEAN_CACHE_PATH):
    """Write-back one clean-server success (R7 minimal hook).

    Thin over the net home (load -> record_clean_success -> save):
    empty results never touch the file (save refuses empty, so an
    empty probe clobbers neither pool nor cache). Best-effort on I/O,
    corrupt-cache, and unserializable-payload failures (OSError,
    ValueError, TypeError: save already removed its tmp file before
    raising) — cache upkeep must never fail a lease or startup for
    those. Other programming errors (wrong shapes: AttributeError)
    propagate out of this helper so typos never hide as cache
    silence (the one production caller, Pool.lease, additionally
    wraps the call best-effort so a minted lease never fails on
    upkeep). ``path``
    defaults to the pool-side clean_cache.json (hermetic
    tests point it at tmp_path).
    """
    try:
        at = time.time() if now is None else now
        entries = load_clean_cache(path)
        updated = record_clean_success(entries, server_id, provider,
                                       latency_ms, at)
        save_clean_cache(path, updated)
    except (OSError, ValueError, TypeError):
        pass


def load_env():
    data = {}
    last_key = None
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                k, v = stripped.split("=", 1)
                k = k.strip()
                if not k.isidentifier():
                    # Not a KEY=value line (e.g. a continuation URL with
                    # a query string): it belongs to the previous value
                    # only for subscription vars — a stray line after the
                    # token must never corrupt it.
                    if last_key in (SUB_VAR, SUBS_VAR):
                        data[last_key] += "\n" + stripped
                    continue
                data[k] = v.strip().strip("'\"")
                last_key = k
            elif last_key in (SUB_VAR, SUBS_VAR):
                # Continuation line: a bare URL on its own line belongs
                # to the previous value (multi-line EGRESS_SUB_URLS).
                data[last_key] += "\n" + stripped
    for k in (SUB_VAR, SUBS_VAR, TOKEN_VAR):
        if k in os.environ and os.environ[k]:
            data[k] = os.environ[k]
    # Factory-file fallback (single loader): the same key resolves via
    # the unified lease-policy resolver with factory/.env first, so an
    # operator who keeps egress secrets in factory/.env needs no second
    # copy in tools/egress/.env. Values never logged — emptiness only.
    try:
        from factory.precard.provider_lease_policy import (
            resolve_key as _resolve,
        )
    except ImportError:
        _resolve = None
    if _resolve is not None:
        for k in (SUB_VAR, SUBS_VAR, TOKEN_VAR):
            if not data.get(k):
                try:
                    hit = _resolve(k, env_map=dict(os.environ),
                                   file_paths=[str(FACTORY_DOTENV)])
                except Exception:
                    hit = ""
                if hit:
                    data[k] = hit
    return data


def sub_sources(env):
    """All subscription sources: plural var (commas AND newlines split)
    plus the legacy singular var. Order preserved, empties dropped.

    Limitation: a link containing a literal comma is unsupported (it
    is treated as a split point)."""
    out = []
    raw = (env.get(SUBS_VAR, "") or "").replace(",", " ")
    for chunk in raw.split():
        chunk = chunk.strip()
        if chunk and chunk not in out:
            out.append(chunk)
    single = (env.get(SUB_VAR, "") or "").strip()
    if single and single not in out:
        out.append(single)
    return out


FACTORY_DOTENV = (pathlib.Path(__file__).resolve().parent.parent
                   .parent / "factory" / ".env")


def probe_key(var, explicit="", env_map=None, extra_files=()):
    """Probe key order: explicit value -> os.environ -> factory/.env ->
    extra files (egress .env last for google). Returns "" when absent
    everywhere. Keys never ride CLI flags (no --*-key options): they come
    from the environment or dotenv files only. Never prints or logs
    values — callers only test for emptiness and name the variable +
    file on failure."""
    try:
        from factory.precard.provider_lease_policy import resolve_key as _resolve
    except ImportError:  # top-level script run (same fallback as above)
        import sys as _sys2
        _sys2.path.insert(0, str(pathlib.Path(__file__).resolve().parent
                                 .parent.parent))
        from factory.precard.provider_lease_policy import resolve_key as _resolve
    files = [str(FACTORY_DOTENV)] + [str(p) for p in (extra_files or ())
                                     if p]
    return _resolve(var, explicit=explicit or "",
                    env_map=os.environ if env_map is None else env_map,
                    file_paths=files)


def parse_subscription(text):
    """Parse a v2ray subscription body into [{scheme, host, port, id}].

    One poisoned line never aborts the source: xrayconf.parse_link is
    the single parser (ValueError contract) and every per-line failure
    is skipped. Exact-duplicate links collapse to one server (public
    subs repeat configs; cross-source dupes additionally collapse in
    Pool.load by id). Plain-text bodies (e.g. xirix-style non-base64)
    are used as-is: a base64 decode that yields no link line is
    discarded, since single-line raw bodies can spuriously decode into
    garbage.
    """
    try:
        from . import xrayconf as _xc
    except ImportError:
        import xrayconf as _xc
    servers = []
    seen = set()
    blob = (text or "").strip()
    if not blob:
        return servers
    try:
        decoded = base64.b64decode(
            blob + "=" * (-len(blob) % 4)).decode("utf-8", "replace")
        if "://" in decoded:
            blob = decoded
    except (ValueError, binascii.Error):
        pass
    for line in blob.splitlines():
        line = line.strip()
        if "://" not in line or line in seen:
            continue
        seen.add(line)
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
        """Replace pool order with a ranked probe list (whitelist).

        Thin caller over the net home (factory.precard.provider_lease_policy):
        ordering lives there, this only assigns under the lock."""
        with self._lock:
            self.servers = order_pool_by_rank(self.servers, ranked)

    def save_pool(self, path=POOL_PATH):
        """Persist the whitelist via the net home's single writer.

        Thin caller: write_pool_file owns the bytes (refuses empty,
        strips link credentials, writes atomically); the lock is held
        across the write (pre-move semantics) so concurrent save_pool
        calls serialize and a stale snapshot can never overwrite a
        newer one. OSError still prints here."""
        with self._lock:
            servers = list(self.servers)
            try:
                write_pool_file(path, servers)
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

    def retarget_lease(self, lease_id, server_id):
        """Point a minted lease at the actual tunnel server (the hint
        lost a cooling race between lease and acquire): reports must
        cool the server carrying traffic. No-op on unknown leases.
        The switch is audit-logged (append-only, secret-free like the
        lease line) so post-mortem forensics reads the tunnel server,
        not the stale hint."""
        with self._lock:
            lease = self.leases.get(lease_id)
            if lease is not None and server_id:
                lease["server"] = server_id
                _append_lease_event(
                    {"event": "retarget",
                     "lease": str(lease_id)[:8],
                     "server": server_id,
                     "provider": lease.get("provider") or "",
                     "target": lease.get("target") or ""})

    def lease(self, target):
        with self._lock:
            now = time.time()
            spec = target_spec(target)
            if spec is None:
                _append_lease_event(
                    {"event": "park", "target": str(target),
                     "reason": "unknown-target"})
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
                _append_lease_event(
                    {"event": "lease", "lease": lid[:8], "mode": "direct",
                     "server": "", "provider": spec["provider"],
                     "target": name})
                return {"lease_id": lid, "mode": "direct", "proxy_url": "",
                        "egress_ip": "direct",
                        "provider": spec["provider"], "target": name}
            provider = spec["provider"]
            snap_servers = [dict(s) for s in self.servers
                            if isinstance(s, dict) and s.get("id")
                            and s.get("link")]
            snap_cool = dict(self.cooldown_until)
        # R7 cache-first (phase 03): the ONE production caller of the
        # net home's cache seam — load → lease_for(..., clean_cache,
        # ping_fn=tcp_ping, clean_ttl) → note_clean_success on success.
        # File + ping I/O run OUTSIDE the lock (a slow ping must never
        # serialize lease callers); the decision below is re-checked
        # and minted under the lock. lease_for's own mint goes to a
        # throwaway NetConfig (decision only); the real lease lives in
        # self.leases with the historic shape + audit lines.
        cache_path = _clean_cache_path()
        entries = load_clean_cache(cache_path)
        ttl = _clean_ttl_from_env()
        # Probe budget: ping at most the first LEASE_PING_MAX_ROWS
        # fresh rows (candidates() sorts fastest-first); the rest
        # fall through to the classic pick inside lease_for — N dead
        # rows must never stall this handler for N x timeout.
        entries = clean_cache_candidates(entries, provider, now,
                                         ttl)[:LEASE_PING_MAX_ROWS]
        closet = NetConfig(servers=snap_servers, clock=lambda: now,
                           cooldown_s=COOLDOWN_S)
        for (sid, prov), exp in snap_cool.items():
            if exp > now:
                net_cool(closet, sid, prov, seconds=exp - now)
        seen_ms = {}

        def _ping(server):
            ms = _server_tcp_ping(server,
                                  timeout=LEASE_PING_TIMEOUT_S)
            if ms:
                seen_ms[server.get("id")] = ms
            return ms

        res = lease_for(closet, name, clean_cache=entries,
                        clean_ttl=ttl, ping_fn=_ping, now=now)
        with self._lock:
            fresh = time.time()
            hint = res.get("server_id") if isinstance(res, dict) \
                else None
            live = {s["id"] for s in self.servers
                    if isinstance(s, dict) and s.get("id")
                    and s.get("link")}
            if hint is not None and hint in live and not self.is_cool(
                    hint, provider, fresh) \
                    and isinstance(res, dict) and res.get("cache_hit"):
                picked, cache_hit = hint, True
            else:
                avail = [s for s in self.servers
                         if isinstance(s, dict) and s.get("id")
                         and s.get("link")
                         and not self.is_cool(s["id"], provider, fresh)]
                if not avail:
                    _append_lease_event(
                        {"event": "park", "target": name,
                         "reason": "no-server"})
                    return {"error": "park",
                            "message": "no link-bearing server available "
                                       "(refresh the subscription)"}
                picked, cache_hit = avail[0]["id"], False
            lid = secrets.token_hex(8)
            self.leases[lid] = {"mode": "tunnel", "server": picked,
                                "since": fresh, "provider": provider,
                                "target": name}
            _append_lease_event(
                {"event": "lease", "lease": lid[:8], "mode": "tunnel",
                 "server": picked, "provider": provider,
                 "target": name})
            result = {"lease_id": lid, "mode": "tunnel",
                      "server_id": picked, "provider": provider,
                      "target": name}
        # Outside the lock: the CACHE HIT/MISS console line plus the
        # write-back (local file I/O never blocks lease callers and
        # never fails the lease — note_clean_success is best-effort).
        # Verified-only write-back: a hit answered a real ping
        # (measured ms in seen_ms). A miss minted an unprobed server —
        # lease is not success, so it must never be cached as clean.
        print(format_cache_line(cache_hit, picked, provider))
        if cache_hit:
            try:
                note_clean_success(picked, provider,
                                   seen_ms.get(picked),
                                   now=fresh, path=cache_path)
            except Exception:  # noqa: BLE001 (OC round-6: cache upkeep
                # never fails a minted lease — the helper stays narrow
                # for debuggability, this call site stays best-effort)
                pass
        return result

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
                _append_lease_event(
                    {"event": "report", "lease": str(lease_id)[:8],
                     "outcome": outcome, "provider": eff,
                     "server": lease.get("server") or "",
                     "action": "switch"})
                return {"action": "switch"}
            if outcome in ("net_err",):
                _append_lease_event(
                    {"event": "report", "lease": str(lease_id)[:8],
                     "outcome": outcome, "provider": eff,
                     "server": lease.get("server") or "",
                     "action": "switch"})
                return {"action": "switch"}
            if outcome == "auth_err":
                # Rejected credentials never succeed on retry: retire the
                # lease so the caller re-authenticates instead of looping.
                self.leases.pop(lease_id, None)
                _append_lease_event(
                    {"event": "report", "lease": str(lease_id)[:8],
                     "outcome": outcome, "provider": eff,
                     "server": lease.get("server") or "",
                     "action": "reauth"})
                return {"action": "reauth"}
            # "unknown" (e.g. child exit code with no network signal):
            # keep the lease, cool nothing. App failure is not proof of
            # a bad egress.
            _append_lease_event(
                {"event": "report", "lease": str(lease_id)[:8],
                 "outcome": outcome, "provider": eff,
                 "server": lease.get("server") or "",
                 "action": "keep"})
            return {"action": "keep"}

    def health(self):
        """Thin caller over the net home: /v1/health shape + the R4
        ``healthy`` hook (True iff a server is pooled) for later
        auto-spawn. Reporting only, no lifecycle change."""
        with self._lock:
            return supervisor_health(self.servers, self.leases)


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

    def acquire(self, provider=None, prefer=None):
        """Start (or reuse) the tunnel for the best server. Returns
        (proxy_url, egress_ip, server_id) or raises RuntimeError.

        Availability skips only servers cooling for ``provider``: a
        zen-429 never blocks a google lease on the same server.
        ``prefer`` (a leased cache hint) wins while it is still live,
        link-bearing, and not cooling — the lease and the tunnel must
        name the same server, or a later http429 report cools the
        wrong one. Otherwise the classic first-avail pick applies
        (the caller syncs the lease record to it). A live tunnel for
        the wanted server is reused BEFORE any probing, so steady
        reuse pays no probe wall and a ping flake can never cool a
        working tunnel. Spawn/egress-check failures carry the failed
        server id as ``failed_server_id`` on the raised error, so the
        /v1/lease handler cools the server that actually failed
        (never the stale hint).
        """
        try:
            from . import tunnel as _tunnel_mod
        except ImportError:  # top-level script run
            import tunnel as _tunnel_mod
        with self._lock:
            now = time.time()
            avail = [s for s in self._pool.servers
                     if isinstance(s, dict) and s.get("id")
                     and not self._pool.is_cool(s["id"], provider, now)
                     and s.get("link")]
            if not avail:
                raise RuntimeError("no link-bearing server available")
            wanted = avail[0]
            if prefer is not None:
                hinted = [s for s in avail if s.get("id") == prefer]
                if hinted:
                    wanted = hinted[0]
            if self._tunnel is not None and self._server_id == wanted["id"] \
                    and self._tunnel.proc is not None \
                    and self._tunnel.proc.poll() is None:
                return (self._tunnel.proxy_url,
                        self._tunnel.egress_ip(), self._server_id)
            # Probe-batch (2026-09-17): never spawn xray on an unprobed
            # server. Ping the first 8 in parallel (8 workers x 2s ping
            # ~= 2s wall), keep pool order, cool the dead for this
            # provider so the next lease skips them. Servers past the
            # first 8 stay as unprobed fallback (never cooled): a big
            # pool never loses healthy servers it did not probe. A
            # fully dead pool parks fast here instead of burning the
            # 25s spawn timeout per attempt behind the 60s client lease
            # timeout (the pile-up that orphaned xray children).
            # Budget: ~2s probe + 25s Tunnel.start + 15s egress check
            # ~= 42s worst case < 60s client lease timeout.
            cands = avail[:8]

            def _live(server):
                try:
                    return bool(_server_tcp_ping(server))
                except Exception:
                    return False

            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=8) as _ex:
                _ok = dict(zip([s["id"] for s in cands],
                               _ex.map(_live, cands)))
            live_ids = {sid for sid, ok in _ok.items() if ok}
            for sid in [s["id"] for s in cands if s["id"] not in live_ids]:
                self._pool.cool(sid, provider, seconds=600)
            avail = [s for s in cands if s["id"] in live_ids] \
                + avail[len(cands):]
            if not avail:
                raise RuntimeError("no live server (probed %d, all dead)"
                                   % len(cands))
            wanted = avail[0]
            if prefer is not None:
                hinted = [s for s in avail if s.get("id") == prefer]
                if hinted:
                    wanted = hinted[0]
            if self._tunnel is not None and self._server_id == wanted["id"] \
                    and self._tunnel.proc is not None \
                    and self._tunnel.proc.poll() is None:
                return (self._tunnel.proxy_url,
                        self._tunnel.egress_ip(), self._server_id)
            self._drop_locked()
            server = wanted
            try:
                tun = _tunnel_mod.Tunnel(server, server["link"])
                proxy = tun.start()
            except (RuntimeError, ValueError, OSError) as exc:
                exc.failed_server_id = server["id"]
                raise
            try:
                ip = tun.egress_ip()
            except Exception:
                tun.stop()
                err = RuntimeError("tunnel up but egress check failed")
                err.failed_server_id = server["id"]
                raise err
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
                    proxy, ip, sid = TUNNELS.acquire(
                        provider=data.get("provider"),
                        prefer=data.get("server_id"))
                except (RuntimeError, ValueError, OSError) as exc:
                    # Acquire failed: cool the server that actually
                    # failed (surfaced as failed_server_id) so the next
                    # lease moves on instead of retrying the same dead
                    # egress; fall back to the hint only when unknown
                    # (e.g. all-dead probe, already cooled 600s each).
                    # Drop the minted lease (no orphan records) and park
                    # with a message.
                    failed = getattr(exc, "failed_server_id", "") \
                        or data.get("server_id", "")
                    try:
                        POOL.cool(failed, data.get("provider"),
                                  seconds=1800)
                    except Exception:
                        pass
                    POOL.discard_lease(data.get("lease_id", ""))
                    return self._send(200, {"error": "park",
                                            "message": str(exc)})
                if sid != data.get("server_id"):
                    # Hint lost a cooling race between lease and
                    # acquire: sync the response + record to the
                    # actual tunnel server so reports cool it.
                    data["server_id"] = sid
                    POOL.retarget_lease(data.get("lease_id", ""), sid)
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


def fetch_sub(url, attempts=2):
    """Fetch a subscription URL with a browser UA (raw hosts 403 the
    default urllib agent). Two attempts with a short backoff; raises
    the last error when all attempts fail (URL itself never logged)."""
    last = RuntimeError("fetch failed")
    for i in range(max(1, attempts)):
        req = urllib.request.Request(
            url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64)",
                "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 (retry then raise)
            last = exc
            if i + 1 < max(1, attempts):
                time.sleep(1.0)
    raise last


def _source_label(src):
    """Redacted per-source label (host only, never the full URL/body).

    hostname (not netloc): netloc keeps userinfo, so credential-bearing
    subscription URLs would leak secrets into stdout logs."""
    if not (src or "").startswith("http"):
        return "inline"
    try:
        return urllib.parse.urlparse(src).hostname or "sub"
    except Exception:  # noqa: BLE001 (label is best-effort)
        return "sub"


def refresh_subscription(env):
    sources = sub_sources(env)
    if not sources:
        print("subscription refresh: no sources configured")
        return
    for src in sources:
        label = _source_label(src)
        body = src
        if body.startswith("http"):
            try:
                body = fetch_sub(body)
            except Exception as exc:  # noqa: BLE001 (per-source)
                print("sub %s: failed (%s)" % (label,
                                               type(exc).__name__))
                continue
        try:
            servers = parse_subscription(body)
        except Exception:  # noqa: BLE001 (one bad body never aborts)
            print("sub %s: failed (parse error)" % label)
            continue
        POOL.load(servers)
        print("sub %s: ok %d servers" % (label, len(servers)))


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


# Live probes attach here: net.TARGETS ships probe=None (hermetic core
# owns the table); the supervisor owns the probe functions and fills
# them into this same dict, so `from supervisor import TARGETS` keeps
# working unchanged (including probe identity).
TARGETS["zen"]["probe"] = zen_probe
TARGETS["google"]["probe"] = google_probe


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
        # \r rewrites share one line: pad to the longest line so far or
        # a short line leaves ghosts of the previous long one.
        width = 0
        for future in _fut.as_completed(future_of):
            done += 1
            ms, server = future.result()
            if not isinstance(server, dict) or not server.get("id") \
                    or not server.get("host") or not server.get("port"):
                continue
            line = "probing %d/%d: %s:%s %s" % (
                done, len(servers), server.get("host"),
                server.get("port"),
                ("%dms" % ms) if ms < 10 ** 9 else "dead")
            width = max(width, len(line))
            print("\r" + line.ljust(width), end="", flush=True)
            ranked.append((ms, server))
        print("")
    # Ranking/row-building lives in the net home (zero logic rewrite:
    # same sort key, dead sentinel, row shape, top-N flag).
    return build_probe_rows(ranked, top_n)


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
                         "take one real Zen ping each (needs "
                         "OPENCODE_ZEN_API_KEY env or factory/.env). "
                         "Slow by design.")
    ap.add_argument("--probe-google", type=int, default=0, metavar="N",
                    help="tunnel the top-N alive servers one by one and "
                         "take one free Google models:list ping each "
                         "(needs GOOGLE_AI_API_KEY env, "
                         "factory/.env, or tools/egress/.env). Google-ok "
                         "servers move to "
                         "the front of the whitelist, so serve mode "
                         "leases them first. Slow by design.")
    args = ap.parse_args(argv)
    if args.gen_token:
        print(secrets.token_hex(24))
        return 0
    env = load_env()
    _trim_leases_file()  # startup-only audit cap (best-effort)
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
        if should_save_whitelist(rows):
            POOL.save_pool()
            print("whitelist saved: %d servers -> %s" % (
                len(POOL.servers), POOL_PATH))
        else:
            # Never overwrite a good whitelist with an empty probe
            # (failed refresh / dead network). Old file stays intact.
            print("probe found 0 alive servers: whitelist NOT overwritten")
        if args.probe_zen:
            key = probe_key("OPENCODE_ZEN_API_KEY")
            if not key:
                print("probe-zen needs OPENCODE_ZEN_API_KEY "
                      "env or factory/.env")
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
            if should_save_whitelist(rows):
                # Same empty-probe rule as above: never overwrite a good
                # whitelist after a probe that found 0 alive servers.
                POOL.save_pool()
            else:
                print("zen probe skipped: whitelist NOT overwritten")
        if args.probe_google:
            key = probe_key("GOOGLE_AI_API_KEY",
                            extra_files=(ENV_PATH,))
            if not key:
                print("probe-google needs GOOGLE_AI_API_KEY "
                      "env, factory/.env, or tools/egress/.env")
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
                # Google-choose lives in the net home (google-ok rows
                # first, serve mode leases them first). Zero rewrite.
                ranked = order_google_first(rows, good)
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
