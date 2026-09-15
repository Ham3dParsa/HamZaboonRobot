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

Stdlib + factory.precard.transport only (precard self-containment:
no factory.archive / factory.pipeline / factory.lexicon imports).
Leases carry server ids and provider names, never key strings.
"""

from __future__ import annotations

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


def call_leg(cfg, leg, prompt, *, transport, model, keys=None,
             key_var="", sleep_fn=None, state=None, label=""):
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
            "factory/.env) — aborting with no silent fallback"
            % (var or "keys", var or "keys"))
    ring = KeyRing(ring_keys)
    if state is None:
        state = {}
    return _call_with_rotation(
        transport, ring, model, prompt, sleep_fn or cfg._sleep,
        state, label or ("%s/%s" % (model, norm_target(leg))),
        provider=provider or "zen", key_var=var)
