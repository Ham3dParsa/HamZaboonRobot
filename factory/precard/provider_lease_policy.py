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
- LEG_FALLBACKS: single owner of every precard model chain
  (R5: the AvalAI/Google precard consts live here; the
  legs hold zero lists). Rows are ((model, cost), ...) in step-down
  order with per-entry cost labels ("paid": D-zen-retire PR-A
  retired the free chain, so every run leg is paid).
- call_leg: one single-model LLM attempt with KeyRing rotation.
  Rotation and abort meaning come from
  factory.core.llm_json.classify via the transport wrapper (this
  module never redefines the error table): 429/quota rotates to the
  next key, 401/403 stops loudly with no further attempts, and
  project-level quota (COOLDOWN_SWITCH, e.g. Google
  RESOURCE_EXHAUSTED) raises ProviderCooldown after exactly one
  attempt with no rotation. T6: the attempt executes behind the
  tunnel-selection seam (select / prove / remember over an
  ephemeral per-provider seed) with byte-identical caller-visible
  behavior. The model step-down walk lives in the
  leg batch loops (judge/topics), which read their chains through
   leg_chain/leg_entries; switch_plan gives those loops the ordered
   R6 provider list (no free provider remains on the run line after
   D-zen-retire PR-A, so every leg stops for a resume on
   ProviderCooldown). Progress flushing and telemetry
  otherwise stay with the caller, as they do for every other
  transport caller today.
- P1 whitelist home (moved verbatim from tools/egress/supervisor.py;
  the supervisor CLI calls these with zero logic rewrite):
  build_probe_rows (rank + top-N mark), order_pool_by_rank (alive
  ranked ids first), order_google_first (google-ok rows first),
  should_save_whitelist (never-overwrite-empty guard),
  write_pool_file (the ONLY egress_pool.json writer: refuses empty,
  strips link credentials), supervisor_health (R4 healthy/unhealthy
  hook for later auto-spawn; reporting only, no lifecycle change).
- R7 clean-server cache (phase 03): clean_cache.json beside the pool
  ([{server_id, provider, last_ok_ts, latency_ms}]); lease_for tries
  fresh (TTL, default 24h) + non-cooling rows first behind one
  real-ping gate each, full probe only on miss; successes write back
  via record_clean_success + save_clean_cache (refuses empty: an
  empty probe clobbers neither pool nor cache). I/O stays with the
  caller (run/supervisor); this module only gates + mints.
- R8 direct-first AvalAI (phase 03): direct_probe_event gives the
  leaseless-then-fallback telemetry shape; format_cache_line owns the
  CACHE HIT/MISS console text (ids only, never keys/links).

Stdlib + factory.precard.provider_transport only (precard self-containment:
no factory.archive / factory.pipeline / factory.lexicon imports).
Leases carry server ids and provider names, never key strings.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import pathlib
import secrets
import threading
import time

from factory.core.llm_json import cooldown_for
from factory.precard.provider_transport import (
    AuthError,
    KeyRing,
    LocationBlocked,
    ProviderCooldown,
    RateLimited,
    _call_with_rotation,
    _read_egress_env_key,
)
from factory.net.tunnel_selection import (
    KeyedProviderProbe,
    NoTunnelExit,
    ProviderProbe,
    SubscriptionSource,
    TunnelSelector,
)

__all__ = [
    "AuthError",
    "KeyRing",
    "LocationBlocked",
    "ProviderCooldown",
    "RateLimited",
    "MissingKeyError",
    "NetConfig",
    "TARGETS",
    "PROVIDER_KEY_VARS",
    "LEGS",
    "FREE_PROVIDERS",
    "PAID_PROVIDERS",
    "SWITCH_ORDER",
    "AVALAI_PRECARD_MODEL",
    "AVALAI_CHAT_URL",
    "GOOGLE_PRECARD_MODEL",
    "GOOGLE_MODELS_URL",
    "LEG_FALLBACKS",
    "leg_chain",
    "leg_entries",
    "may_auto_switch",
    "switch_plan",
    "target_for",
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
    "CLEAN_CACHE_TTL_S",
    "CLEAN_CACHE_FILENAME",
    "default_clean_cache_path",
    "load_clean_cache",
    "save_clean_cache",
    "clean_cache_candidates",
    "record_clean_success",
    "order_cache_exits",
    "direct_probe_event",
    "format_cache_line",
]

# Canonical lease-target table (moved from tools/egress/supervisor.py).
# tunnel False = direct mode (no server); True = needs a server pick.
# probe stays None here (hermetic core); the supervisor attaches its
# live zen/google probe functions to this same dict on import.
# NOTE (D-zen-retire PR-A): the precard run line no longer selects zen
# (pipeline/run require avalai|google), but the "zen" row STAYS: the
# egress supervisor (tools/egress/supervisor.py, out of scope) attaches
# its live zen probe to TARGETS["zen"] and serves zen tunnel leases.
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
# NOTE (D-zen-retire PR-A): no zen entry — the run line never resolves
# a zen key (pipeline/run require avalai|google fail-closed).
PROVIDER_KEY_VARS = {
    "google": ("GOOGLE_AI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "avalai": ("AVALAI_API_KEY",),
}

# --- P2 LEG_FALLBACKS home (R5): single owner of every precard model
# chain (moved here; the legs hold zero lists and read through
# leg_chain/LEG_FALLBACKS). Avalai/Google precard consts only
# (D-zen-retire PR-A: the zen free-model chain is retired from the
# run line, so no zen rows remain).
AVALAI_PRECARD_MODEL = "glm-5.3-flash"

AVALAI_CHAT_URL = "https://api.avalai.ir/v1/chat/completions"

GOOGLE_PRECARD_MODEL = "gemini-3.5-flash-lite"

GOOGLE_MODELS_URL = ("https://generativelanguage.googleapis.com/v1beta/"
                     "models/%s:generateContent")

# Pipeline LLM legs (mirrors pipeline.LLM_LEGS; the tuple lives here so
# the table keys stay valid even for callers that never import the
# pipeline).
LEGS = ("inflection_review", "sense_judge", "topic_vectors",
        "topic_label")

# R6 cost tiers (D-zen-retire PR-A): every precard run leg is paid
# (avalai/google legs; google direct exposes no usage counters, so
# its spend is cost-unknown, never a silent zero). No free provider
# remains on the run line, so no leg auto-switches: ProviderCooldown
# stops for a resume. (The egress supervisor's zen tunnel target is a
# separate seam and keeps its own TARGETS row above.)
FREE_PROVIDERS = frozenset()
PAID_PROVIDERS = frozenset({"avalai", "google"})

# Provider switch order for free-leg COOLDOWN_SWITCH (R6). No free
# provider remains on the run line (may_auto_switch is always False),
# so this order is never walked by precard legs; it stays as the
# paid-provider enumeration for readers.
SWITCH_ORDER = ("avalai", "google")


# LEG_FALLBACKS[(provider, leg)] = ((model, cost), ...) in step-down
# order. Avalai/google legs are single paid defaults (the remap
# transports substitute the actual model, telemetry keeps the
# requested name).
LEG_FALLBACKS = {
    ("avalai", "inflection_review"): ((AVALAI_PRECARD_MODEL, "paid"),),
    ("avalai", "sense_judge"): ((AVALAI_PRECARD_MODEL, "paid"),),
    ("avalai", "topic_vectors"): ((AVALAI_PRECARD_MODEL, "paid"),),
    ("avalai", "topic_label"): ((AVALAI_PRECARD_MODEL, "paid"),),
    ("google", "inflection_review"): ((GOOGLE_PRECARD_MODEL, "paid"),),
    ("google", "sense_judge"): ((GOOGLE_PRECARD_MODEL, "paid"),),
    ("google", "topic_vectors"): ((GOOGLE_PRECARD_MODEL, "paid"),),
    ("google", "topic_label"): ((GOOGLE_PRECARD_MODEL, "paid"),),
}


def leg_entries(provider, leg):
    """Raw ((model, cost), ...) chain for (provider, leg) ([] unknown)."""
    return list(LEG_FALLBACKS.get(
        (norm_provider(provider), leg), ()))


def leg_chain(provider, leg):
    """Model names for (provider, leg) in step-down order ([] unknown)."""
    return [model for model, _cost in leg_entries(provider, leg)]


def may_auto_switch(provider):
    """True iff a leg on provider may auto-switch on COOLDOWN_SWITCH.

    R6 gate: free legs only. D-zen-retire PR-A retired the only free
    provider, so this is False for every run provider. Paid legs stop
    (flush + resume) — the caller treats ProviderCooldown as
    stop+resume either way.
    """
    return norm_provider(provider) in FREE_PROVIDERS


def switch_plan(provider, step):
    """Ordered providers a leg tries for one step (R6 free-switch).

    A free leg tries its own provider first, then the rest of
    SWITCH_ORDER that own this step's chain; paid (or unknown)
    providers try only themselves (a cooldown stops for a resume).
    D-zen-retire PR-A: every run provider is paid, so run legs always
    try only themselves. Legs additionally keep only providers they
    hold a ring for, so a switched attempt always presents that
    provider's own key — never another provider's.
    """
    base = norm_provider(provider)
    if step not in LEGS:
        raise ValueError(
            "unknown step %r (want one of: %s)" % (step, ", ".join(LEGS)))
    if may_auto_switch(base):
        return [base] + [p for p in SWITCH_ORDER
                         if p != base and (p, step) in LEG_FALLBACKS]
    return [base]


def target_for(provider):
    """TARGETS target whose provider matches (leg-loop routing seam).

    Lets the leg batch loops route every model attempt through
    call_leg with their real provider ("avalai"/"google" are the run
    targets; "zen" stays a TARGETS key for the egress supervisor
    tunnel seam, out of scope). Unknown providers fall back to
    "avalai" (direct: no server pick, fail-closed downstream).
    """
    want = norm_provider(provider)
    for name, spec in TARGETS.items():
        if spec.get("provider") is not None \
                and norm_provider(spec["provider"]) == want:
            return name
    return "avalai"

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
    cooldown_s: explicit per-(server, provider) cooldown override
    (e.g. --cooldown-secs); None (default) resolves per-provider via
    cooldown_for. keys: {provider: [key values]} for call_leg
    (in-memory only, never persisted or logged).
    """

    def __init__(self, *, servers=None, clock=None, sleeper=None,
                 cooldown_s=None, keys=None):
        self.servers = [dict(s) for s in (servers or [])
                        if isinstance(s, dict)]
        self._clock = clock or time.time
        self._sleep = sleeper or time.sleep
        self.cooldown_s = (None if cooldown_s is None
                           else float(cooldown_s))
        self.keys = {str(k): [v for v in (vals or []) if v]
                     for k, vals in dict(keys or {}).items()}
        self._lock = threading.RLock()
        self._cooldown_until = {}
        self._leases = {}
        self._lease_seq = 0


def cool(cfg, server_id, provider=None, seconds=None):
    """Mark (server, provider) as cooling. The ONLY cooldown writer.

    An explicit seconds wins; else the config override (cooldown_s,
    e.g. --cooldown-secs) wins; else the per-provider table.
    """
    if not server_id:
        return
    if seconds is not None:
        wait = float(seconds)
    else:
        wait = cooldown_for(
            provider, override=getattr(cfg, "cooldown_s", None))
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


def lease_for(cfg, target, *, clean_cache=None, clean_ttl=None,
                ping_fn=None, now=None, selector_fn=None):
    """Pick a lease for a target. Shapes mirror the egress supervisor:
    direct targets mint a direct lease; tunnel targets take the first
    non-cooling server; nothing usable parks with a message.

    R7 cache-first (phase 03) through the tunnel-selection seam (T6):
    fresh (TTL, default 24h) + non-cooling rows for this provider are
    ordered by ``order_cache_exits`` (provider namespaces never leak —
    another provider's rows never order here), then the exit is served
    via ``select`` (preference), verified row by row in that order via
    ``prove`` (each behind exactly one real-ping gate, early stop at
    the first clean — keep=1 single-winner override), and the winner
    stabilizes via ``remember``. ``selector_fn(provider, adapter)``
    injects the seam (tests pass fakes); the default wires a real
    ``TunnelSelector`` over an ephemeral per-provider seed (no files,
    no durable write — the caller still owns write-back via
    ``record_clean_success`` + ``save_clean_cache``, single-writer
    rule preserved). A MISS (no rows, all stale/cooling/missing/
    ping-dead, or a ``NoTunnelExit`` preference) falls through to the
    classic first-avail pick with ``cache_hit`` False — the caller runs
    its full probe only on that miss. ``now`` is injectable for
    hermetic tests. Every result carries ``cache_hit`` (False on
    direct/park rows too).

    Concurrency: candidate snapshots are taken under the pool lock,
    but ``ping_fn`` (network I/O, behind ``prove``) always runs
    WITHOUT the lock — a slow/hung ping must never serialize all
    lease callers. The first ping-ok row is re-checked for cooling
    under the lock before the lease is minted (a row cooled mid-ping
    falls through to the classic pick). ``clean_ttl`` garbage
    (non-numeric, non-finite, or non-positive) falls back to
    ``CLEAN_CACHE_TTL_S`` — the run entry rejects such values with
    exit 2, library callers get the safe default and never an
    exception.
    """
    with cfg._lock:
        at = cfg._clock() if now is None else now
        spec = target_spec(target)
        if spec is None:
            return {"error": "park",
                    "message": "unknown target %r (want one of: %s)"
                               % (target, ", ".join(sorted(TARGETS))),
                    "cache_hit": False}
        name = norm_target(target)
        if not spec["tunnel"]:
            lid = secrets.token_hex(8)
            cfg._leases[lid] = {"mode": "direct", "server": None,
                                "since": at,
                                "provider": spec["provider"],
                                "target": name}
            return {"lease_id": lid, "mode": "direct", "proxy_url": "",
                    "egress_ip": "direct",
                    "provider": spec["provider"], "target": name,
                    "cache_hit": False}
        ttl = _clean_ttl(clean_ttl)
        ordered = []
        snapshots = {}
        if clean_cache and ping_fn is not None:
            by_id = {s["id"]: dict(s) for s in cfg.servers
                     if isinstance(s, dict) and s.get("id")}
            avail = [sid for sid in by_id
                     if not is_cool(cfg, sid, spec["provider"], now=at)]
            ordered = order_cache_exits(clean_cache, spec["provider"],
                                        avail, at, ttl)
            snapshots = {sid: by_id[sid] for sid in ordered
                         if sid in by_id}
    winner = None
    winner_latency = 0.0
    if ordered:
        ping_detail: dict = {}
        adapter = _PingProbe(
            check_fn=_ping_check_fn(ping_fn, snapshots, ping_detail))
        if selector_fn is not None:
            selector = selector_fn(spec["provider"], adapter)
        else:
            selector = _default_leg_selector(
                spec["provider"], adapter, ordered,
                clock=lambda: at, batch=5, keep=1,
                paid=True)
        try:
            selection = selector.select(spec["provider"])
        except NoTunnelExit:
            selection = None
        if selection is not None:
            proof = selector.prove(spec["provider"], ordered)
            if proof.clean:
                winner = proof.clean[0]
                winner_latency = _ping_latency(ping_detail, winner)
                try:
                    selector.remember(spec["provider"], winner,
                                      winner_latency)
                except Exception:  # noqa: BLE001 (upkeep never fails)
                    pass
    with cfg._lock:
        if winner is not None and not is_cool(
                cfg, winner, spec["provider"], now=at):
            lid = secrets.token_hex(8)
            cfg._leases[lid] = {"mode": "tunnel", "server": winner,
                                "since": at,
                                "provider": spec["provider"],
                                "target": name}
            return {"lease_id": lid, "mode": "tunnel",
                    "server_id": winner,
                    "provider": spec["provider"], "target": name,
                    "cache_hit": True}
        avail = [s for s in cfg.servers
                 if s.get("id")
                 and not is_cool(cfg, s["id"], spec["provider"],
                                 now=at)]
        if not avail:
            return {"error": "park",
                    "message": "no server available "
                               "(all cooling or pool empty)",
                    "cache_hit": False}
        picked = avail[0]
        lid = secrets.token_hex(8)
        cfg._leases[lid] = {"mode": "tunnel", "server": picked["id"],
                            "since": at, "provider": spec["provider"],
                            "target": name}
        return {"lease_id": lid, "mode": "tunnel",
                "server_id": picked["id"],
                "provider": spec["provider"], "target": name,
                "cache_hit": False}


def report_lease(cfg, lease_id, outcome, provider=None):
    """Record a lease outcome. 429 cools the lease's server (next lease
    moves on); a location block cools the pair the same way but keeps
    the lease (never reaped); auth failures retire the lease; anything
    unrecognized keeps the lease and cools nothing. Mirrors
    supervisor.report."""
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
        if outcome == "location-blocked" and lease.get("server"):
            # Persistent egress condition (not transient quota): exile
            # on the persistent (generic) scale unless the operator
            # override (cfg.cooldown_s) says otherwise.
            cool(cfg, lease["server"], eff, seconds=cooldown_for(
                "generic", override=getattr(cfg, "cooldown_s", None)))
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


# --- R7 clean-server cache home (phase 03) ---

# Default freshness for a cached clean server (24h; the run entry
# resolves --clean-ttl/EGRESS_CLEAN_TTL over this, never beside it).
CLEAN_CACHE_TTL_S = 86400.0

# File beside the pool (tools/egress/clean_cache.json): rows are
# {server_id, provider, last_ok_ts, latency_ms} only — ids and timing,
# never links/keys (same secret-free rule as the pool writer).
CLEAN_CACHE_FILENAME = "clean_cache.json"


def _clean_ttl(value):
    """Finite positive TTL seconds; anything else -> the default.

    ``None`` (unset) means ``CLEAN_CACHE_TTL_S``; non-numeric,
    non-finite (inf/nan), or non-positive values also fall back to it.
    The run entry rejects such values loudly (exit 2); library-level
    callers get the safe default and never an exception, and a NaN
    TTL can never invert freshness (``age > NaN`` is always False,
    which used to make stale rows look fresh).
    """
    try:
        ttl = CLEAN_CACHE_TTL_S if value is None else float(value)
    except (TypeError, ValueError):
        return CLEAN_CACHE_TTL_S
    if not math.isfinite(ttl) or ttl <= 0:
        return CLEAN_CACHE_TTL_S
    return ttl


def _clean_ts(value):
    """last_ok_ts float normalization (write path mirrors load).

    Non-numeric or non-finite (nan/inf) timestamps become 0.0 (epoch:
    always stale) so the writer never emits NaN/Infinity payloads.
    """
    try:
        ts = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return ts if math.isfinite(ts) else 0.0


def _clean_latency(value):
    """latency_ms int/None normalization (write path mirrors load).

    Truncates floats/numeric strings to int; None stays None; anything
    non-numeric (including inf, which int() rejects with OverflowError)
    becomes None so the writer never emits a non-serializable payload.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def default_clean_cache_path(pool_path):
    """Cache path beside a pool path (same directory, fixed filename)."""
    try:
        parent = pathlib.Path(str(pool_path)).parent
    except (TypeError, ValueError):
        parent = pathlib.Path(".")
    return str(parent / CLEAN_CACHE_FILENAME)


def load_clean_cache(path):
    """Read cached clean servers (tolerates missing/corrupt -> []).

    Accepts {"entries": [...]} (the save shape) or a bare [...].
    Malformed rows (not a dict, no server_id) are dropped; surviving
    rows keep server_id/provider/last_ok_ts/latency_ms only. Pure
    read: no network, no clock.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    rows = payload.get("entries") if isinstance(payload, dict) else None
    if rows is None:
        rows = payload if isinstance(payload, list) else []
    clean = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("server_id"):
            continue
        entry = {"server_id": row["server_id"]}
        entry["provider"] = norm_provider(row.get("provider"))
        try:
            entry["last_ok_ts"] = float(row.get("last_ok_ts", 0) or 0)
        except (TypeError, ValueError):
            entry["last_ok_ts"] = 0.0
        if not math.isfinite(entry["last_ok_ts"]):
            entry["last_ok_ts"] = 0.0
        try:
            entry["latency_ms"] = (None if row.get("latency_ms") is None
                                   else int(row["latency_ms"]))
        except (TypeError, ValueError, OverflowError):
            entry["latency_ms"] = None
        clean.append(entry)
    return clean


def save_clean_cache(path, entries):
    """The ONLY clean_cache.json writer. Refuses empty, strips secrets.

    Returns the saved entry count, or 0 when ``entries`` holds no
    server_id-bearing row — in which case the path is NOT touched (an
    empty probe clobbers neither pool nor cache). Atomic tmp+replace
    (a crash mid-write keeps the previous good file); failed writes
    remove the temp file best-effort and raise (OSError, ValueError,
    or TypeError — e.g. an unserializable id). Sync I/O.
    """
    live = [e for e in (entries or [])
            if isinstance(e, dict) and e.get("server_id")]
    if not live:
        return 0
    payload = {"saved_at": datetime.datetime.now(
        datetime.timezone.utc).isoformat(),
        "entries": [{"server_id": e["server_id"],
                     "provider": norm_provider(e.get("provider")),
                     "last_ok_ts": _clean_ts(e.get("last_ok_ts", 0)),
                     "latency_ms": _clean_latency(e.get("latency_ms"))}
                    for e in live]}
    tmp_path = str(path) + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except (OSError, ValueError, TypeError):
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return len(live)


def clean_cache_candidates(entries, provider, now, ttl=None):
    """Fresh provider-matched cache rows, earliest-latency first.

    Fresh = now - last_ok_ts <= ttl (default 24h); stale rows never
    return (a stale entry is a MISS, re-probed only by the caller's
    full scan). latency_ms None sorts last. Non-numeric/non-finite
    TTL falls back to the default (see _clean_ttl); rows whose age is
    non-numeric or non-finite (e.g. NaN last_ok_ts) are stale. Pure.
    """
    limit = _clean_ttl(ttl)
    want = norm_provider(provider)
    fresh = []
    for row in entries or []:
        if not isinstance(row, dict) or not row.get("server_id"):
            continue
        if norm_provider(row.get("provider")) != want:
            continue
        try:
            age = float(now) - float(row.get("last_ok_ts", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(age):
            continue
        if age < 0 or age > limit:
            continue
        fresh.append(row)
    fresh.sort(key=lambda r: (r.get("latency_ms") is None,
                              r.get("latency_ms") or 0))
    return fresh


def record_clean_success(entries, server_id, provider, latency_ms,
                         now):
    """Upsert one success into cache rows (pure write-back helper).

    Returns a NEW list (caller saves it): the (server_id, provider)
    row moves to the end with fresh last_ok_ts/latency_ms; falsy
    server_id is a no-op returning the input rows unchanged.
    """
    rows = [dict(e) for e in (entries or []) if isinstance(e, dict)]
    if not server_id:
        return rows
    want = norm_provider(provider)
    rows = [e for e in rows
            if not (e.get("server_id") == server_id
                    and norm_provider(e.get("provider")) == want)]
    at = _clean_ts(now)
    ms = _clean_latency(latency_ms)
    rows.append({"server_id": server_id, "provider": want,
                 "last_ok_ts": at, "latency_ms": ms})
    return rows


def direct_probe_event(ok, provider="avalai"):
    """R8 telemetry shape for the leaseless direct-first path.

    ok = the direct ping reached AvalAI with no lease; falsy = fall
    back to a lease (the caller mints it, this only labels the event).
    Secret-free, JSON-serializable. Pure.
    """
    hit = bool(ok)
    return {"event": "direct-probe",
            "provider": norm_provider(provider) or "avalai",
            "outcome": "direct-ok" if hit else "lease-fallback",
            "lease_taken": not hit}


def format_cache_line(hit, server_id="", provider=""):
    """CACHE HIT/MISS console text (single owner; ids only, no keys)."""
    if hit:
        return "CACHE HIT server=%s provider=%s (no full probe)" % (
            server_id or "?", norm_provider(provider) or "?")
    return "CACHE MISS provider=%s (full probe)" % (
        norm_provider(provider) or "?")


# --- T6 tunnel-selection seam block (phase 04): the precard line's busiest
# path crosses select / prove / remember here; TARGETS, key resolution,
# lease/cooldown shapes, batch/concurrency, and the registry are untouched.
# Concrete shapes mirror the T4 probe path (single-candidate source +
# ephemeral per-provider store); the durable clean-cache file stays behind
# the single readers/writers above (shared-infra compat, no second owner).


class _LegEgressSource(SubscriptionSource):
    """One-shot candidate source for one leg/lease attempt (no IO).

    ``refresh`` offers exactly the candidate ids in the caller's order;
    rows tag "paid" for tunnel targets (clean-tunnel infra) else "free"
    (paid-ness is decided by the supervisor lease, never here — no
    values leak).
    """

    def __init__(self, ids, paid=False):
        tag = "paid" if paid else "free"
        self._rows = [{"id": sid, "source": tag}
                      for sid in ids or () if sid]

    def refresh(self):
        return [dict(r) for r in self._rows]


class _EphemeralProviderStore:
    """Per-provider memory namespaces for one attempt (no files).

    Same read/write shape as the provider-aware cache: namespaces are
    keyed by provider (a groq select never sees google rows). Lives for
    one call — the durable supervisor file stays behind the single
    writers (remember path); stabilization here is best-effort only.
    """

    def __init__(self):
        self._namespaces = {}

    def read(self, provider):
        return [dict(r) for r in self._namespaces.get(provider, [])]

    def write(self, provider, rows):
        self._namespaces[provider] = [dict(r) for r in rows or []]


class _PingProbe(ProviderProbe):
    """Lease ping as a probe: truthy ping reads clean, falsy/raising and
    ``None`` read unknown (honest park, never invent a verdict — the same
    contract as the registered keyless/keyed shapes, but keyless and
    provider-agnostic: a TCP ping carries no key and proves reachability
    only, never identity)."""

    def __init__(self, check_fn=None):
        if check_fn is not None and not callable(check_fn):
            raise TypeError("check_fn must be callable or None")
        self._check_fn = check_fn

    def probe(self, exit_id):
        if self._check_fn is None:
            return "unknown"
        try:
            verdict = self._check_fn(exit_id)
        except Exception:
            return "unknown"
        if verdict == "clean":
            return "clean"
        if verdict == "blocked":
            return "blocked"
        return "unknown"


def _ping_check_fn(ping_fn, snapshots, detail):
    """Check closure turning one lease ping into a probe verdict.

    ``snapshots`` maps exit id -> pooled server dict (taken under the
    pool lock); ``detail["latencies"]`` collects per-exit ping ms for
    the ``remember`` stabilization (numeric finite ms only, else 0.0).
    """

    def _check(exit_id):
        snap = snapshots.get(exit_id)
        if snap is None:
            return "unknown"
        try:
            ok = ping_fn(snap)
        except Exception:  # noqa: BLE001 (ping fail = next row)
            return "unknown"
        if not ok:
            return "unknown"
        try:
            ms = float(ok)
        except (TypeError, ValueError):
            ms = 0.0
        if not math.isfinite(ms):
            ms = 0.0
        try:
            detail.setdefault("latencies", {})[exit_id] = ms
        except (AttributeError, TypeError):
            pass
        return "clean"

    return _check


def _ping_latency(detail, exit_id):
    """Stashed ping ms for a proven exit (0.0 when unmeasured)."""
    try:
        latencies = (detail or {}).get("latencies") or {}
        ms = float(latencies.get(exit_id, 0.0))
    except (TypeError, ValueError, AttributeError):
        return 0.0
    return ms if math.isfinite(ms) else 0.0


def _default_leg_selector(provider, adapter, candidates, *, clock,
                           batch=5, keep=5, paid=False,
                           subs_fn=None, store_fn=None):
    """Default select+prove wiring for one leg/lease attempt (no files).

    ``subs_fn``/``store_fn`` inject the source/store halves (tests pass
    fakes); ``batch``/``keep`` are the injected prove caps (defaults 5,
    never hardcoded — lease acquisition overrides keep=1: a single
    lease has a single winner, same single-exit precedent as the probe
    path).
    """
    subs = subs_fn() if subs_fn is not None else _LegEgressSource(
        candidates, paid=paid)
    store = store_fn() if store_fn is not None else \
        _EphemeralProviderStore()
    probes = {provider: adapter} if adapter is not None else {}
    return TunnelSelector(subs=subs, probes=probes, store=store,
                          clock=clock, batch=batch, keep=keep)


def order_cache_exits(entries, provider, available_ids, now, ttl=None):
    """Fresh provider-matched cached exit ids ∩ available, fastest first.

    Pure provider-scoped read over ``clean_cache_candidates``: only rows
    matching ``provider`` ever order (no shared fallback — another
    provider's fresh rows never appear, even when this provider has
    none). ``available_ids`` is the pooled + snapshot-non-cooling set;
    cached ids outside it never order. No network, no files, no keys.
    """
    rows = clean_cache_candidates(entries, provider, now, ttl)
    live = set(available_ids or ())
    return [r["server_id"] for r in rows
            if isinstance(r, dict) and r.get("server_id") in live]


def call_leg(cfg, leg, prompt, *, transport, model=None, keys=None,
             ring=None, key_var="", sleep_fn=None, state=None,
             label="", file_label="factory/.env", selector_fn=None,
             subs_fn=None, store_fn=None, batch=5, keep=5):
    """One single-model LLM attempt with KeyRing rotation. Returns
    (text, usage-or-None).

    leg selects the provider through TARGETS (e.g. "avalai"); keys default
    to the config's key values for that provider. An explicit ``ring``
    is used as-is (the leg batch loops keep their cross-batch ring, so
    routing them through here changes no rotation state); otherwise a
    fresh ring is built from ``keys`` (or the config). ``cfg`` may be
    None only when ``ring`` and ``sleep_fn`` are both given.

    Exactly one model with key rotation: 429/quota rotates to the
    next key and retries the same call; when every key is exhausted
    the wrapper raises RateLimited. Project-level quota
    (COOLDOWN_SWITCH, e.g. Google RESOURCE_EXHAUSTED) raises
    ProviderCooldown, and geo blocks (LOCATION_BLOCK) raise
    LocationBlocked (key kept) — both RateLimited subclasses, so
    existing flush+stop handlers stay safe — after exactly one
    attempt with no rotation.
    401/403 raises AuthError naming the key variable and file after
    exactly one attempt (no silent retry, no fallback).

    The R6 provider switch lives in the leg batch loops: they walk
    switch_plan and pass each attempt's own provider ring, so a
    switched attempt never presents another provider's key. Paid
    legs stop for a resume. Progress flushing and telemetry stay
    with the caller, exactly as for every other transport caller
    today.

    Tunnel-selection seam (T6): the attempt runs behind select /
    prove / remember. ``selector_fn(provider, adapter)`` injects the
    seam (tests pass fakes); the default wires a real
    ``TunnelSelector`` over an ephemeral per-provider seed (no files,
    no durable write). The registered keyed probe wraps the rotation
    call (key VAR NAME only, never the value): a non-empty reply
    proves clean, an empty reply or transport failure proves unknown,
    and control-flow (RateLimited incl. ProviderCooldown, AuthError)
    plus caller-visible errors ride ``detail`` and re-raise after
    ``prove`` — the legs' except-chains observe byte-identical
    behavior. A clean proof stabilizes via ``remember``
    (best-effort); ``NoTunnelExit`` propagates honestly (production
    seeds always carry the candidate, so the leg path never parks).
    ``subs_fn``/``store_fn`` inject the source/store halves;
    ``batch``/``keep`` are the injected prove caps (defaults 5).
    """
    spec = target_spec(leg)
    if spec is None:
        raise ValueError(
            "unknown leg %r (want one of: %s)"
            % (leg, ", ".join(sorted(TARGETS))))
    provider = spec["provider"]
    var = key_var or (PROVIDER_KEY_VARS.get(provider or "", ("",))[0])
    if state is None:
        state = {}
    sleep = sleep_fn or (cfg._sleep if cfg is not None else time.sleep)
    if provider is None:
        # Direct targets carry no keys: a single attempt, no rotation.
        return transport("", model, prompt)
    owned_ring = ring
    if owned_ring is None:
        ring_keys = ([k for k in (keys if keys is not None
                                  else (cfg.keys.get(provider or "", [])
                                        if cfg is not None else []))
                      if k])
        if not ring_keys:
            raise MissingKeyError(
                "no %s (set %s in the environment, or add it to "
                "%s) — aborting with no silent fallback"
                % (var or "keys", var or "keys", file_label))
        owned_ring = KeyRing(ring_keys)
    attempt_label = label or ("%s/%s" % (model, norm_target(leg)))
    detail: dict = {}

    def _attempt(exit_id):
        del exit_id  # single-attempt leg: egress rides the established path
        start = time.perf_counter()
        try:
            text, usage = _call_with_rotation(
                transport, owned_ring, model, prompt, sleep,
                state, attempt_label,
                provider=provider or "avalai", key_var=var,
                file_label=file_label)
        except Exception as exc:  # noqa: BLE001 (rides detail, re-raised)
            detail.update({"ran": True, "text": None, "usage": None,
                           "exc": exc, "verdict": "unknown",
                           "latency_ms": (time.perf_counter() - start)
                           * 1000.0})
            return "unknown"
        latency_ms = (time.perf_counter() - start) * 1000.0
        if isinstance(text, str) and text.strip():
            detail.update({"ran": True, "text": text, "usage": usage,
                           "exc": None, "verdict": "clean",
                           "latency_ms": latency_ms})
            return "clean"
        detail.update({"ran": True, "text": text, "usage": usage,
                       "exc": None, "verdict": "unknown",
                       "latency_ms": latency_ms})
        return "unknown"

    adapter = KeyedProviderProbe(key_name=var or provider,
                                 check_fn=_attempt)
    candidate = norm_target(leg)
    if selector_fn is not None:
        selector = selector_fn(provider, adapter)
    else:
        selector = _default_leg_selector(
            provider, adapter, [candidate], clock=time.time,
            batch=batch, keep=keep, paid=bool(spec["tunnel"]),
            subs_fn=subs_fn, store_fn=store_fn)
    selection = selector.select(provider)
    selector.prove(provider, [selection.exit_id])
    if not detail.get("ran"):
        raise RuntimeError(
            "leg selector did not execute the adapter "
            "(prove must route exits through the given probe)")
    exc = detail.get("exc")
    if exc is not None:
        raise exc
    if detail.get("verdict") == "clean":
        try:
            selector.remember(provider, selection.exit_id,
                              detail.get("latency_ms") or 0.0)
        except Exception:  # noqa: BLE001 (upkeep never fails a leg)
            pass
    return detail.get("text"), detail.get("usage")
