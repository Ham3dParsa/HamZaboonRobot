"""Precard network core (P0 part A): leases, legs, key order, TARGETS.

Single home for the precard line's network surface. Hermetic by design:
fake servers, an injectable clock, injected transports, and explicit env
maps keep every path testable with no network, no keys, and no W: drive.

- TARGETS: canonical lease-target table (moved here from
  tools/egress/supervisor.py; the supervisor imports it back and only
  attaches its live probe functions). Rows are exactly
  {provider, tunnel, probe}; probe is None here (the core never touches
  the network) and the supervisor fills in zen/google probes on import.
- NetConfig: servers + cooldowns + key values (in-memory only).
- resolve_key / require_key: --flag -> env -> factory/.env order for one
  key variable. Missing keys stop loudly naming the variable and the
  file; values are never logged, persisted, or interpolated into errors.
- lease_for / report_lease: cooldown-aware server picking with the same
  lease/report shapes as the egress supervisor (proxy attach stays in
  the supervisor/tunnel layer).
- call_leg: one LLM leg with KeyRing rotation. Rotation and abort
  meaning come from factory.core.llm_json.classify via the transport
  wrapper (this module never redefines the error table): 429/quota
  rotates to the next key, 401/403 stops loudly with no further
  attempts, and project-level quota (COOLDOWN_SWITCH, e.g. Google
  RESOURCE_EXHAUSTED) raises ProviderCooldown after exactly one
  attempt with no rotation. Progress flushing and telemetry stay with
  the caller, as they do for every other transport caller today.
- P1 whitelist home (moved verbatim from tools/egress/supervisor.py;
  the supervisor CLI calls these with zero logic rewrite):
  build_probe_rows (rank + top-N mark), order_pool_by_rank (alive
  ranked ids first), order_google_first (google-ok rows first),
  should_save_whitelist (never-overwrite-empty guard),
  write_pool_file (the ONLY egress_pool.json writer: refuses empty,
  strips link credentials), supervisor_health (R4 healthy/unhealthy
  hook for later auto-spawn; reporting only, no lifecycle change).

Stdlib + factory.precard.transport only (precard self-containment:
no factory.archive / factory.pipeline / factory.lexicon imports).
Leases carry server ids and provider names, never key strings.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import secrets
import threading
import time

from factory.precard.transport import (
    AuthError,
    KeyRing,
    ProviderCooldown,
    RateLimited,
    _call_with_rotation,
    _read_egress_env_key,
)

__all__ = [
    "AuthError",
    "KeyRing",
    "ProviderCooldown",
    "RateLimited",
    "MissingKeyError",
    "NetConfig",
    "TARGETS",
    "PROVIDER_KEY_VARS",
    "resolve_key",
    "require_key",
    "cool",
    "is_cool",
    "known_provider",
    "lease_for",
    "norm_provider",
    "norm_target",
    "report_lease",
    "call_leg",
    "target_spec",
    "PROBE_DEAD_MS",
    "build_probe_rows",
    "order_pool_by_rank",
    "order_google_first",
    "should_save_whitelist",
    "write_pool_file",
    "supervisor_health",
]

# Canonical lease-target table (moved from tools/egress/supervisor.py).
# tunnel False = direct mode (no server); True = needs a server pick.
# probe stays None here (hermetic core); the supervisor attaches its
# live zen/google probe functions to this same dict on import.
TARGETS = {
    "direct": {"provider": None, "tunnel": False, "probe": None},
    "zen": {"provider": "zen", "tunnel": True, "probe": None},
    "google": {"provider": "google", "tunnel": True,
               "probe": None},
    "openrouter": {"provider": "openrouter", "tunnel": True,
                   "probe": None},
    "avalai": {"provider": "avalai", "tunnel": False, "probe": None},
}

# Provider -> key variables in resolution order (primary first).
# Single owner of the provider/var pairing for the precard line.
PROVIDER_KEY_VARS = {
    "zen": ("OPENCODE_ZEN_API_KEY", "OPENCODE_ZEN_API_KEY_2"),
    "google": ("GOOGLE_AI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "avalai": ("AVALAI_API_KEY",),
}

_USE_DEFAULT = object()


class MissingKeyError(KeyError):
    """A required key variable is empty everywhere. Loud stop: the message
    names the variable and the file, never the value."""


def _default_factory_env():
    """Absolute factory/.env path (read for names on demand, never at
    import: hermetic callers pass explicit env maps / temp files)."""
    return str(pathlib.Path(__file__).resolve().parent.parent / ".env")


def norm_target(target):
    """Canonical target key: lowercase, stripped."""
    return str(target or "").strip().lower()


def norm_provider(provider):
    """Canonical provider key: lowercase, stripped, "" when absent."""
    return str(provider or "").strip().lower()


def target_spec(target):
    """TARGETS row for a lease target, or None when unknown."""
    return TARGETS.get(norm_target(target))


def _known_provider(provider):
    """True when provider is absent/None or a TARGETS provider.

    Guards the cooldown table: an arbitrary caller-supplied string must
    never mint junk (server, provider) keys.
    """
    if provider is None:
        return True
    want = norm_provider(provider)
    return any(spec["provider"] is not None
               and norm_provider(spec["provider"]) == want
               for spec in TARGETS.values())


def known_provider(provider):
    """Public alias of the TARGETS-membership guard (re-exported by the
    egress supervisor so ``from supervisor import known_provider`` keeps
    working; the table itself stays here)."""
    return _known_provider(provider)


def resolve_key(var, *, explicit="", env_map=None, file_paths=None):
    """Resolve one key variable without ever raising or logging values.

    Order: explicit --flag value, then the env mapping (os.environ by
    default), then each dotenv file path in order (factory/.env by
    default). Returns the value or "" when absent everywhere.
    """
    if explicit:
        return explicit
    env = os.environ if env_map is None else env_map
    try:
        hit = env.get(var, "")
    except AttributeError:
        hit = ""
    if hit:
        return hit
    paths = _USE_DEFAULT if file_paths is None else file_paths
    if paths is _USE_DEFAULT:
        paths = (_default_factory_env(),)
    for path in paths or ():
        if not path:
            continue
        hit = _read_egress_env_key(str(path), var)
        if hit:
            return hit
    return ""


def require_key(var, *, explicit="", env_map=None, file_paths=None,
                flag="", file_label="factory/.env"):
    """resolve_key that stops loudly when the variable is empty.

    Raises MissingKeyError naming the variable, the flag, and the file
    (never the value): a missing key must abort, never silently fall
    back to an empty credential.
    """
    value = resolve_key(var, explicit=explicit, env_map=env_map,
                        file_paths=file_paths)
    if value:
        return value
    hint = "pass %s, " % flag if flag else ""
    raise MissingKeyError(
        "no %s (%sset %s in the environment, or add it to %s) — "
        "aborting with no silent fallback" % (var, hint, var,
                                              file_label))


class NetConfig:
    """In-memory network state: servers, cooldowns, leases, key values.

    servers: [{id, host, port, ...}] (fake lists welcome; only "id"
    is required for picking). clock: now() seconds (injectable for
    hermetic tests). sleeper: sleep(seconds) between rotations.
    cooldown_s: per-(server, provider) cooldown after a 429 report.
    keys: {provider: [key values]} for call_leg (in-memory only,
    never persisted or logged).
    """

    def __init__(self, *, servers=None, clock=None, sleeper=None,
                 cooldown_s=300.0, keys=None):
        self.servers = [dict(s) for s in (servers or [])
                        if isinstance(s, dict)]
        self._clock = clock or time.time
        self._sleep = sleeper or time.sleep
        self.cooldown_s = float(cooldown_s)
        self.keys = {str(k): [v for v in (vals or []) if v]
                     for k, vals in dict(keys or {}).items()}
        self._lock = threading.RLock()
        self._cooldown_until = {}
        self._leases = {}
        self._lease_seq = 0


def cool(cfg, server_id, provider=None, seconds=None):
    """Mark (server, provider) as cooling. The ONLY cooldown writer."""
    if not server_id:
        return
    wait = cfg.cooldown_s if seconds is None else float(seconds)
    with cfg._lock:
        cfg._cooldown_until[(server_id,
                             norm_provider(provider))] = \
            cfg._clock() + wait


def is_cool(cfg, server_id, provider=None, now=None):
    """True while (server, provider) is still cooling. ``now`` is
    injectable for hermetic tests. The ONLY cooldown reader."""
    if not server_id:
        return False
    at = cfg._clock() if now is None else now
    with cfg._lock:
        return cfg._cooldown_until.get(
            (server_id, norm_provider(provider)), 0) > at


def lease_for(cfg, target):
    """Pick a lease for a target. Shapes mirror the egress supervisor:
    direct targets mint a direct lease; tunnel targets take the first
    non-cooling server; nothing usable parks with a message."""
    with cfg._lock:
        now = cfg._clock()
        spec = target_spec(target)
        if spec is None:
            return {"error": "park",
                    "message": "unknown target %r (want one of: %s)"
                               % (target, ", ".join(sorted(TARGETS)))}
        name = norm_target(target)
        if not spec["tunnel"]:
            lid = secrets.token_hex(8)
            cfg._leases[lid] = {"mode": "direct", "server": None,
                                "since": now,
                                "provider": spec["provider"],
                                "target": name}
            return {"lease_id": lid, "mode": "direct", "proxy_url": "",
                    "egress_ip": "direct",
                    "provider": spec["provider"], "target": name}
        avail = [s for s in cfg.servers
                 if s.get("id")
                 and not is_cool(cfg, s["id"], spec["provider"],
                                 now=now)]
        if not avail:
            return {"error": "park",
                    "message": "no server available "
                               "(all cooling or pool empty)"}
        picked = avail[0]
        lid = secrets.token_hex(8)
        cfg._leases[lid] = {"mode": "tunnel", "server": picked["id"],
                            "since": now, "provider": spec["provider"],
                            "target": name}
        return {"lease_id": lid, "mode": "tunnel",
                "server_id": picked["id"],
                "provider": spec["provider"], "target": name}


def report_lease(cfg, lease_id, outcome, provider=None):
    """Record a lease outcome. 429 cools the lease's server (next lease
    moves on); auth failures retire the lease; anything unrecognized
    keeps the lease and cools nothing. Mirrors supervisor.report."""
    with cfg._lock:
        lease = cfg._leases.get(lease_id)
        if lease is None:
            return {"action": "unknown-lease"}
        if not _known_provider(provider):
            return {"action": "keep"}
        eff = norm_provider(provider) if provider is not None \
            else lease.get("provider")
        if outcome == "http429" and lease.get("server"):
            cool(cfg, lease["server"], eff)
            return {"action": "switch"}
        if outcome in ("net_err",):
            return {"action": "switch"}
        if outcome == "auth_err":
            cfg._leases.pop(lease_id, None)
            return {"action": "reauth"}
        return {"action": "keep"}


# --- P1 whitelist home (moved verbatim from the egress supervisor) ---

# Dead-ping sentinel: probe code reports None for unreachable servers;
# ranking sorts them last with this stand-in (moved verbatim).
PROBE_DEAD_MS = 10 ** 9


def build_probe_rows(ranked, top_n):
    """Rank (ms, server) ping pairs into whitelist probe rows.

    Moved verbatim from supervisor.probe_pool (sort key, dead
    sentinel, and row shape unchanged): ascending latency, dead
    servers last with latency_ms None, top-N alive marked
    zen_candidate. Malformed pairs (not a 2-tuple, non-dict server,
    or a dict missing host/port/scheme/id) are skipped — the same
    filter the supervisor applies before calling — so a junk entry
    can never crash the probe with KeyError. Pure: no network, no
    clock, no I/O.
    """
    clean = []
    for pair in ranked or []:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            continue
        ms, s = pair
        if not isinstance(s, dict):
            continue
        if not s.get("id"):
            continue
        if not all(k in s for k in ("host", "port", "scheme")):
            continue
        clean.append((ms, s))
    ordered = sorted(clean, key=lambda pair: pair[0])
    return [{"host": s["host"], "port": s["port"], "scheme": s["scheme"],
             "id": s["id"],
             "latency_ms": (None if ms >= PROBE_DEAD_MS else ms),
             "alive": ms < PROBE_DEAD_MS,
             "zen_candidate": idx < top_n and ms < PROBE_DEAD_MS}
            for idx, (ms, s) in enumerate(ordered)]


def order_pool_by_rank(servers, ranked):
    """Whitelist choose: alive ranked ids first, every other server kept.

    Moved verbatim from supervisor Pool.load_ranked: ranked rows that
    are alive and still pooled move to the front in probe order;
    unknown (ghost) ids are ignored; everything else (dead,
    unranked) keeps its relative order after. Non-dict or id-less
    servers are skipped (both loops), so direct callers that bypass
    Pool.load's filter can never raise KeyError. Pure.
    """
    by_id = {s["id"]: s for s in (servers or [])
             if isinstance(s, dict) and s.get("id")}
    ordered = []
    for row in ranked or []:
        if not isinstance(row, dict):
            continue
        hit = by_id.get(row.get("id"))
        if row.get("alive") and hit is not None:
            ordered.append(hit)
    ordered_ids = {s["id"] for s in ordered}
    for s in servers or []:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        if s["id"] not in ordered_ids:
            ordered.append(s)
            ordered_ids.add(s["id"])
    return ordered


def order_google_first(rows, good_ids):
    """Google-choose: google-ok alive rows first, the rest after in order.

    Moved verbatim from the supervisor --probe-google block (serve
    mode then leases google-friendly servers first). NOTE (kept
    behavior, not a fix): a good id that is dead in ``rows`` lands in
    neither list, i.e. it drops out — in practice good ids always come
    from live pings of alive candidates, so the set is empty.
    Non-dict rows are skipped; dicts are read with .get so a row
    missing "id"/"alive" can never raise KeyError.
    """
    good = set(good_ids or ())
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    first = [r for r in rows if r.get("id") in good and r.get("alive")]
    first += [r for r in rows if r.get("id") not in good]
    return first


def should_save_whitelist(rows):
    """Never-overwrite-empty guard: True iff at least one row is alive.

    The ONLY whitelist-save decision (every supervisor save site calls
    this): an empty probe (failed refresh / dead network) must never
    clobber a good egress_pool.json. Pure.
    """
    return any(r.get("alive") for r in (rows or []))


def write_pool_file(path, servers):
    """The ONLY egress_pool.json writer. Refuses empty, strips secrets.

    Returns the saved server count, or 0 when ``servers`` holds no
    id-bearing entry — in which case the path is NOT touched (never
    overwrite a good whitelist with an empty probe). Persisted rows
    keep host/port/scheme/id only: links carry credentials and are
    never written (relink on refresh). Raises OSError to the caller
    (the supervisor prints it); no printing here. Synchronous I/O.
    The write is atomic: the payload goes to a temp file in the same
    directory and is then os.replace()d over the destination, so a
    crash mid-write can never leave a corrupt egress_pool.json behind
    (a stale reader keeps the previous good file). A failed write
    removes the temp file best-effort and still raises OSError.
    """
    live = [s for s in (servers or [])
            if isinstance(s, dict) and s.get("id")]
    if not live:
        return 0
    payload = {"saved_at": datetime.datetime.now(
        datetime.timezone.utc).isoformat(),
        "servers": [{k: s[k] for k in
                       ("scheme", "host", "port", "id")
                       if k in s} for s in live]}
    tmp_path = str(path) + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return len(live)


def supervisor_health(servers, leases):
    """R4 health hook for later auto-spawn: reporting only, no lifecycle.

    ``healthy`` is True iff at least one server is pooled (an empty
    pool cannot serve tunnel leases). ``ok``/``servers``/``leases``
    keep the exact /v1/health shape existing clients parse. Pure.
    """
    try:
        n_servers = len(servers)
    except TypeError:
        n_servers = 0
    try:
        n_leases = len(leases)
    except TypeError:
        n_leases = 0
    return {"ok": True, "servers": n_servers, "leases": n_leases,
            "healthy": n_servers > 0}


def call_leg(cfg, leg, prompt, *, transport, model, keys=None,
             key_var="", sleep_fn=None, state=None, label="",
             file_label="factory/.env"):
    """One LLM leg with KeyRing rotation. Returns (text, usage-or-None).

    leg selects the provider through TARGETS (e.g. "zen"); keys default
    to the config's key values for that provider. 429/quota rotates to
    the next key and retries the same call; when every key is exhausted
    the wrapper raises RateLimited. Project-level quota
    (COOLDOWN_SWITCH, e.g. Google RESOURCE_EXHAUSTED) raises
    ProviderCooldown (a RateLimited subclass, so existing flush+stop
    handlers stay safe) after exactly one attempt with no rotation.
    401/403 raises AuthError naming the
    key variable and file after exactly one attempt (no silent retry,
    no fallback). Progress flushing and telemetry stay with the caller,
    exactly as for every other transport caller today.
    """
    spec = target_spec(leg)
    if spec is None:
        raise ValueError(
            "unknown leg %r (want one of: %s)"
            % (leg, ", ".join(sorted(TARGETS))))
    provider = spec["provider"]
    var = key_var or (PROVIDER_KEY_VARS.get(provider or "", ("",))[0])
    ring_keys = ([k for k in (keys if keys is not None
                              else cfg.keys.get(provider or "", []))
                  if k])
    if provider is None:
        # Direct targets carry no keys: a single attempt, no rotation.
        return transport("", model, prompt)
    if not ring_keys:
        raise MissingKeyError(
            "no %s (set %s in the environment, or add it to "
            "%s) — aborting with no silent fallback"
            % (var or "keys", var or "keys", file_label))
    ring = KeyRing(ring_keys)
    if state is None:
        state = {}
    return _call_with_rotation(
        transport, ring, model, prompt, sleep_fn or cfg._sleep,
        state, label or ("%s/%s" % (model, norm_target(leg))),
        provider=provider or "zen", key_var=var,
        file_label=file_label)
