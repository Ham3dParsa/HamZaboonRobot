"""Cloud probes (Step 3): live health checks over the standard prompt.

Infrastructure only (no screening/ranking logic here): builds ONE
minimal arbitration prompt with the engine's own
:func:`factory.precard.judge.arbiter_prompt` (the standard wording —
never retyped here) over a single synthetic item with two fake
candidates, then sends it through each named provider's registry
transport and records latency + HTTP error kind per provider.

Key discipline: name-only checks first
(:func:`provider_registry.key_ref_for` names +
:func:`provider_lease_policy.resolve_key` booleans). Secret VALUES are
never printed, logged, or written — only names + booleans leave this
module. The module loads the factory environment file itself via
:func:`load_factory_env` (default ``factory/.env`` beside this repo —
never the ambient shell export); ``--env-file`` lets the operator point
at another dotenv path (a path only, never values). A provider with no
resolvable key is recorded as ``skipped-with-reason`` and the rest
continue; nothing is guessed.

Model discipline: Google keeps its engine default (flash-lite) for the
``sense_judge`` leg. Groq and OpenRouter have no engine default model
for that leg, so this module documents explicit probe free defaults
(:data:`PROBE_FREE_MODELS`) the operator can override per provider with
``--model name=id`` (operator-provided, never an engine default — the
receipt says so via ``model_source``).

Probe lines go to stdout AND the Temp run log
(``%TEMP%/linker_probe_<UTC-stamp>.log``).

Usage:
    python -m factory.linking.probe_providers
    python -m factory.linking.probe_providers --env-file <path-to-.env>
    python -m factory.linking.probe_providers --model groq=llama-3.3-70b-versatile
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tempfile
import time
import urllib.error

PROBE_PROVIDERS = ("groq", "openrouter", "google")

#: Explicit probe free defaults per provider (operator-overridable via
#: ``--model name=id``). Google keeps its engine flash-lite default;
#: Groq and OpenRouter have no engine default for the ``sense_judge``
#: leg, so these documented free-tier ids stand in — never presented
#: as engine defaults (see :func:`model_source`).
PROBE_FREE_MODELS = {
    "google": "gemini-3.5-flash-lite",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "qwen/qwen3.8-27b:free",
}

#: Factory environment file name probed beside the repo root.
FACTORY_ENV_NAME = ".env"

PROBE_ITEM = {"kind": "word", "text": "run",
              "pool_level": "B1", "pos": "verb"}

#: One-line reason Google defaults to the leased tunnel (stated wherever
#: the route is shown — probe lines, CLI plan, WebUI compose line).
GOOGLE_TUNNEL_REASON = (
    "direct Google calls die with geo-block 403 — "
    "Google rides the leased tunnel")

#: Domestic hosts bypass the tunnel proxy (same rule as
#: tools/egress/run_with_lease.py — child env only, never the parent).
NO_PROXY_DOMESTIC = "api.avalai.ir,localhost,127.0.0.1"


def route_for(provider, registry_fn=None):
    """Leased-vs-direct route for a provider: "leased" or "direct".

    Mirrors the precard line's TARGETS table via the engine registry
    row (``provider_registry.resolve_provider`` ``route`` field:
    "tunnel" -> leased, anything else -> direct). ``registry_fn``
    injects the row reader (tests pass fakes — no imports in tests).
    """
    if registry_fn is None:
        from factory.precard import provider_registry as _reg
        registry_fn = _reg.resolve_provider
    try:
        row = registry_fn(provider)
    except Exception:
        row = None
    if isinstance(row, dict) and str(row.get("route") or "") == "tunnel":
        return "leased"
    return "direct"


def route_reason(provider, route):
    """One-line reason for a (provider, route) pairing (no secrets)."""
    from factory.precard.provider_lease_policy import (
        norm_provider as _norm)
    name = _norm(provider) or str(provider or "")
    if route == "leased":
        if name == "google":
            return GOOGLE_TUNNEL_REASON
        return ("%s registry route is tunnel — leased clean egress "
                "via the supervisor" % name)
    return ("%s registry route is direct — no lease, no proxy"
            % name)


def lease_tunnel(provider, lease_fn=None, target_fn=None):
    """Lease a clean tunnel for a provider (supervisor lease flow).

    Mirrors the precard line (factory/run.py ensure_supervisor +
    tools/egress/run_with_lease.py): health-checked supervisor lease
    for the provider's TARGETS target — never a spawn here (a down
    supervisor is a loud lease-error, never an auto-start; shared
    infrastructure stays untouched, others' leases undisturbed).
    Returns the lease dict as-is (lease_id/mode/proxy_url/server_id).
    ``lease_fn(target)`` defaults to the live loopback client;
    ``target_fn(provider)`` defaults to the engine ``target_for``.
    """
    if target_fn is None:
        from factory.precard.provider_lease_policy import (
            target_for as target_fn)
    if lease_fn is None:
        from tools.egress import client as _client
        lease_fn = _client.lease
    return lease_fn(target_fn(provider))


def report_outcome(lease_id, outcome, provider=None, report_fn=None):
    """Best-effort terminal report for our OWN lease only (never others').

    Outcome mapping (supervisor cools OUR server for the provider on
    http429 via its per-(server,provider) cooldown; auth retires our
    lease; unknown keeps it and cools nothing). Returns the report
    dict or None when skipped/failed (reporting never fails a probe).
    """
    if not lease_id:
        return None
    if report_fn is None:
        try:
            from tools.egress import client as _client
            report_fn = _client.report
        except Exception:
            return None
    try:
        if provider is None:
            return report_fn(lease_id, outcome)
        return report_fn(lease_id, outcome, provider)
    except Exception:
        return None


class _proxy_env:
    """Patch HTTPS_PROXY/HTTP_PROXY (+ NO_PROXY domestic) around one call.

    Same-process mirror of run_with_lease.py's child-env export: the
    parent shell and system VPN are untouched (previous values
    restored in a finally). urllib honors these with zero extra deps.
    """

    def __init__(self, proxy_url):
        self.proxy_url = proxy_url or ""
        self._saved = {}

    def __enter__(self):
        if not self.proxy_url:
            return self
        for var in ("HTTPS_PROXY", "HTTP_PROXY"):
            self._saved[var] = os.environ.get(var)
            os.environ[var] = self.proxy_url
        prev_no = os.environ.get("NO_PROXY", "")
        self._saved["NO_PROXY"] = os.environ.get("NO_PROXY")
        domestic = [h for h in NO_PROXY_DOMESTIC.split(",") if h]
        if prev_no:
            domestic = prev_no.split(",") + domestic
        os.environ["NO_PROXY"] = ",".join(dict.fromkeys(
            h.strip() for h in domestic if h.strip()))
        return self

    def __exit__(self, *exc):
        for var, prev in self._saved.items():
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev
        self._saved = {}
        return False

PROBE_CANDIDATES = [
    {"sense_id": "run#0", "gloss": "move fast on foot",
     "tags": ["verb"]},
    {"sense_id": "run#1", "gloss": "manage or be in charge of",
     "tags": ["verb"]},
]


def default_factory_env_path():
    """Absolute default factory env path (``factory/.env``)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", FACTORY_ENV_NAME))


def load_factory_env(path=None, *, override=False):
    """Load the factory environment file into ``os.environ``.

    Thin wrapper over :func:`factory.core.env_loader.load_factory_env`
    (the single allowlisted loader — no parallel dictionaries here):
    only canonical + legacy key names load, values never leave the
    process. Returns ``{"path", "loaded", "vars"}``: the resolved path,
    whether the file existed, and the key VAR NAMES loaded (never
    values). Missing file => ``loaded`` False, ``vars`` [] — never an
    exception, never a guess.
    """
    import pathlib as _pl

    from factory.core.env_loader import KEYS as _ALLOWLIST
    from factory.core.env_loader import (
        load_factory_env as _core_load,
    )

    resolved = os.path.abspath(path) if path else default_factory_env_path()
    if not _pl.Path(resolved).exists():
        return {"path": resolved, "loaded": False, "vars": []}
    before = dict(os.environ)
    _core_load(path=resolved, override=override)
    names = [k for k in _ALLOWLIST
             if os.environ.get(k)
             and (override or not before.get(k))]
    # Report in file order (stable, names only) — reread names only.
    ordered = []
    try:
        for raw in open(resolved, encoding="utf-8"):
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name = line.split("=", 1)[0].strip()
            if name in names and name not in ordered:
                ordered.append(name)
    except OSError:
        ordered = list(names)
    return {"path": resolved, "loaded": True, "vars": ordered}


def build_probe_prompt(prompt_fn=None):
    """Standard arbitration prompt over the synthetic probe item."""
    if prompt_fn is None:
        from factory.precard.judge import arbiter_prompt as prompt_fn
    from factory.precard.accounting import source_item_key

    key = source_item_key(PROBE_ITEM)
    anchor_map = {key: {"candidates": list(PROBE_CANDIDATES)}}
    return prompt_fn([dict(PROBE_ITEM)], anchor_map)


def key_status(provider, resolve_fn=None):
    """(has_key, key_var_names): names + booleans only, values never read."""
    from factory.precard import provider_registry as _reg

    if resolve_fn is None:
        from factory.precard.provider_lease_policy import (
            resolve_key as resolve_fn)
    names = list(_reg.key_ref_for(provider))
    return bool(any(resolve_fn(v) for v in names)), names


def default_model(provider, chain_fn=None):
    """Probe model for a provider: engine default first, else the probe
    free default ("" when neither exists)."""
    if chain_fn is None:
        from factory.precard.provider_lease_policy import (
            leg_chain as chain_fn)
    try:
        chain = chain_fn(provider, "sense_judge")
    except Exception:
        chain = []
    if chain:
        first = chain[0] if isinstance(chain, (list, tuple)) else ""
        if isinstance(first, str) and first:
            return first
    from factory.precard.provider_lease_policy import (
        norm_provider as _norm)
    return PROBE_FREE_MODELS.get(_norm(provider), "")


def model_source(provider, operator_models=None, chain_fn=None):
    """Where the probe model comes from: operator-provided (``--model``),
    engine-default (``leg_chain``), or probe-free-default (documented
    in :data:`PROBE_FREE_MODELS`); "" when no model resolves."""
    from factory.precard.provider_lease_policy import (
        norm_provider as _norm)
    key = _norm(provider)
    if (operator_models or {}).get(provider):
        return "operator-provided"
    if chain_fn is None:
        from factory.precard.provider_lease_policy import (
            leg_chain as chain_fn)
    try:
        chain = chain_fn(provider, "sense_judge")
    except Exception:
        chain = []
    if chain and isinstance(chain, (list, tuple)) and chain \
            and isinstance(chain[0], str) and chain[0]:
        return "engine-default"
    if key in PROBE_FREE_MODELS:
        return "probe-free-default"
    return ""


def _error_kind(exc):
    """(kind, http_status) for a transport failure; values never included."""
    if isinstance(exc, urllib.error.HTTPError):
        return ("http-%d" % exc.code, exc.code)
    if isinstance(exc, urllib.error.URLError):
        reason = str(getattr(exc, "reason", "") or "")
        if "timed out" in reason.lower():
            return ("timeout", None)
        return ("url-error", None)
    if isinstance(exc, TimeoutError):
        return ("timeout", None)
    name = type(exc).__name__ or "error"
    return ("error-" + name.lower(), None)


class _SingleEgressSource:
    """One-candidate subscription source for the probe path (no network).

    The probe resolves exactly one egress (the leased server id, or
    "direct"); select picks it through the normal paid-first/dedup order.
    Leased exits tag "paid" (clean-tunnel infra), direct tags "free".
    """

    def __init__(self, exit_id, paid):
        self._rows = [{"id": exit_id,
                       "source": "paid" if paid else "free"}]

    def refresh(self):
        return [dict(r) for r in self._rows]


class _MemoryProviderStore:
    """Ephemeral per-provider store for the probe path (no files).

    Same read/write shape as the provider-aware cache: namespaces are
    keyed by provider (a Groq select never sees Google rows). Rows live
    only for the single probe call — the durable google-clean file stays
    behind the ``remember_fn`` seam (linker migration owns it).
    """

    def __init__(self):
        self._namespaces = {}

    def read(self, provider):
        return [dict(r) for r in self._namespaces.get(provider, [])]

    def write(self, provider, rows):
        self._namespaces[provider] = [dict(r) for r in rows or []]


def _make_probe_adapter(provider, transport_fn, key_value, model,
                        prompt_text, proxy_url, clock, detail):
    """Registered probe wrapping one transport call (runs behind prove).

    Returns the keyless-Google implementation for Google, the keyed
    implementation (key NAME only, never the value) for every other
    provider. The ``check_fn`` closure executes the single transport call
    under the leased proxy env, records ``detail`` (text/kind/code/exc/
    latency/empty/ran — OUR error datum only), and returns the Proof
    verdict: "clean" on a non-empty reply, "unknown" otherwise (transport
    errors are unknown, never blocked — the prove-seam contract).
    """
    from factory.net.tunnel_selection import (
        KeyedProviderProbe,
        KeylessGoogleProbe,
    )
    from factory.precard.provider_lease_policy import (
        norm_provider as _norm)

    def _check(exit_id):
        del exit_id  # single-egress probe: egress rides the proxy env
        start = clock()
        try:
            with _proxy_env(proxy_url):
                text, _usage = transport_fn(key_value, model, prompt_text)
        except Exception as exc:  # noqa: BLE001 — every failure is a datum
            kind, code = _error_kind(exc)
            detail.update({"ran": True, "text": "", "kind": kind,
                           "code": code, "exc": exc,
                           "latency": round(clock() - start, 3),
                           "empty": False})
            return "unknown"
        detail.update({"ran": True, "text": text,
                       "kind": None, "code": None, "exc": None,
                       "latency": round(clock() - start, 3),
                       "empty": not (isinstance(text, str)
                                     and text.strip())})
        return "clean" if not detail["empty"] else "unknown"

    if _norm(provider) == "google":
        return KeylessGoogleProbe(check_fn=_check)
    return KeyedProviderProbe(key_name=_norm(provider) or str(provider or ""),
                              check_fn=_check)


def _default_probe_selector(provider, adapter, candidate, leased,
                            subs_fn, store_fn, batch, keep, clock):
    """Default select+prove wiring for the probe path (no network/files)."""
    from factory.net.tunnel_selection import TunnelSelector

    subs = subs_fn() if subs_fn is not None else _SingleEgressSource(
        candidate, paid=bool(leased and candidate != "direct"))
    store = store_fn() if store_fn is not None else _MemoryProviderStore()
    return TunnelSelector(subs=subs, probes={provider: adapter},
                          store=store, clock=clock,
                          batch=batch, keep=keep)


def probe_one(provider, prompt_text, model="", key_value="",
              transport_fn=None, clock=None, route="auto",
              lease_fn=None, report_fn=None, target_fn=None,
              registry_fn=None, clean_fn=None, remember_fn=None,
              selector_fn=None, subs_fn=None, store_fn=None,
              batch=5, keep=5):
    """Probe one provider: (result dict). Secret value stays in-memory only.

    Thin caller of the tunnel-selection seam: egress arrives via
    ``select`` (single-candidate source, paid-first/dedup order) and the
    single transport verdict arrives via ``prove`` (registered keyless-
    Google / keyed-second probe behind one Proof shape). ``selector_fn``
    ``(provider, adapter) -> selector`` injects the seam (tests pass
    fakes — no network in tests); the default wires a real
    ``TunnelSelector`` over an ephemeral per-provider store
    (``subs_fn``/``store_fn`` inject its halves). ``batch``/``keep`` are
    injected caps (defaults 5, never hardcoded); the single-exit probe
    coerces non-positive ``keep`` to 1 so the one exit is always proven.

    ``transport_fn(api_key, model, user_text) -> (text, usage)`` defaults
    to the provider's own registry transport. ``clock`` defaults to
    ``time.monotonic`` (tests inject fakes — no network in tests).
    ``clean_fn() -> [server ids]`` defaults to the fresh verified-exit
    whitelist (tests inject fakes — never the real cache file);
    ``remember_fn(server_id, provider, latency_ms)`` defaults to the
    clean-cache write-back (tests inject recorders).

    Routing mirrors the precard leased-tunnel path: ``route="auto"``
    leases a clean supervisor tunnel for tunnel-route providers
    (Google: geo-block 403 direct) and runs direct otherwise; explicit
    "leased"/"direct" overrides auto. A leased run patches the proxy
    env around the single transport call only (guest == direct: no
    lease, no proxy), then best-effort reports OUR lease outcome
    (ok / http429-cool / auth-retire / unknown-keep) — others'
    leases are never touched. Result carries ``route`` + short
    ``lease`` id + ``egress`` server (or "direct").
    Google leased results additionally carry the whitelist verdict:
    ``clean`` True (leased exit is a fresh verified exit) / False
    (unlisted) / None (not a google leased exit), ``clean_note``
    ("whitelisted/unlisted exit <id>"), and ``location_blocked``
    (a 403 whose body proves a sanctioned egress — reported net_err
    so OUR server cools for google; any other 403 keeps auth_err).
    A successful leased Google call writes OUR exit back to the
    clean cache (future leases prefer it, no restart).
    """
    from factory.precard import provider_registry as _reg

    if clock is None:
        clock = time.monotonic
    want_route = str(route or "auto").strip().lower()
    if want_route not in ("auto", "leased", "direct"):
        want_route = "auto"
    eff_route = (route_for(provider, registry_fn=registry_fn)
                 if want_route == "auto" else want_route)
    if transport_fn is None:
        row = _reg.resolve_provider(provider)
        if row is None:
            return {"provider": provider, "status": "skipped",
                    "reason": "unknown provider (not in engine registry)",
                    "latency_s": None, "error_kind": None,
                    "http_status": None, "model": model or None,
                    "route": eff_route, "lease": None,
                    "egress": None,
                    "route_reason": route_reason(provider, eff_route)}
        transport = _reg.transport_for(row.get("protocol"))
        base_url = row.get("base_url")
        extras = row.get("request_extras") or {}

        def transport_fn(api_key, model, user_text,
                         _t=transport, _u=base_url, _e=extras):
            if _t is None:
                raise RuntimeError("no transport for protocol")
            try:
                return _t(api_key, model, user_text,
                          base_url=_u, extra=_e or None)
            except TypeError:
                # Transports with a narrower envelope (e.g. gemini_rest:
                # no base_url/extra legs) take (api_key, model, text).
                return _t(api_key, model, user_text)

    lease_id, egress, proxy_url = "", "", ""
    # Google-clean whitelist (client half of the known-good
    # supervisor technique): fresh verified exits from
    # tools/egress/clean_cache.json — the same file every /v1/lease
    # honors with no restart. Non-google providers skip it (never
    # their business); load failures read as [] (unlisted, honest).
    whitelist = []
    if eff_route == "leased":
        try:
            from factory.precard.provider_lease_policy import (
                norm_provider as _norm_w)
            if _norm_w(provider) == "google":
                if clean_fn is None:
                    from factory.linking import google_clean as _gc
                    clean_fn = _gc.fresh_clean_exits
                whitelist = list(clean_fn() or [])
        except Exception:  # noqa: BLE001 (no whitelist, no preference)
            whitelist = []

    def _clean_flag():
        if eff_route != "leased" or not egress:
            return None
        try:
            from factory.precard.provider_lease_policy import (
                norm_provider as _norm_c)
            if _norm_c(provider) != "google":
                return None
        except Exception:  # noqa: BLE001 (unjudged, never dirty)
            return None
        return egress in set(whitelist or [])

    def _clean_note():
        flag = _clean_flag()
        if flag is None:
            return ""
        try:
            from factory.linking import google_clean as _gc_n
            return _gc_n.clean_note(egress, whitelist)
        except Exception:  # noqa: BLE001 (annotation never fails a probe)
            return ""
    if eff_route == "leased":
        try:
            lease = lease_tunnel(provider, lease_fn=lease_fn,
                                 target_fn=target_fn)
        except Exception as exc:  # noqa: BLE001 — lease fail is a datum
            return {"provider": provider, "status": "lease-error",
                    "reason": ("supervisor lease failed (%s) — "
                               "start the shared supervisor; nothing "
                               "was spawned" % type(exc).__name__),
                    "latency_s": None, "error_kind": "lease-error",
                    "http_status": None, "model": model or None,
                    "route": eff_route, "lease": None, "egress": None,
                    "clean": None, "clean_note": "",
                    "location_blocked": False,
                    "route_reason": route_reason(provider, eff_route)}
        if not isinstance(lease, dict) or lease.get("error"):
            msg = ""
            try:
                msg = str((lease or {}).get("message") or "")
            except Exception:
                msg = ""
            return {"provider": provider, "status": "lease-error",
                    "reason": ("supervisor lease refused%s — shared "
                               "supervisor untouched, nothing spawned"
                               % (": %s" % msg if msg else "")),
                    "latency_s": None, "error_kind": "lease-error",
                    "http_status": None, "model": model or None,
                    "route": eff_route, "lease": None, "egress": None,
                    "clean": None, "clean_note": "",
                    "location_blocked": False,
                    "route_reason": route_reason(provider, eff_route)}
        lease_id = str(lease.get("lease_id") or "")
        egress = str(lease.get("server_id") or lease.get("egress_ip")
                     or "")
        proxy_url = str(lease.get("proxy_url") or "")
    else:
        egress = "direct"

    def _report(outcome):
        from factory.precard.provider_lease_policy import (
            norm_provider as _norm)
        return report_outcome(lease_id, outcome,
                              provider=_norm(provider),
                              report_fn=report_fn)

    # Seam crossing (T4): egress arrives via select, the single transport
    # verdict arrives via prove. The adapter runs the transport behind
    # prove and stashes OUR error datum in ``detail``; the annotation
    # below (reports, whitelist flag, write-back) is unchanged behavior.
    detail = {}
    adapter = _make_probe_adapter(
        provider, transport_fn, key_value, model, prompt_text,
        proxy_url if eff_route == "leased" else "", clock, detail)
    candidate = egress or "direct"
    effective_keep = keep if isinstance(keep, int) and not isinstance(
        keep, bool) and keep > 0 else 1
    if selector_fn is not None:
        selector = selector_fn(provider, adapter)
    else:
        selector = _default_probe_selector(
            provider, adapter, candidate, eff_route == "leased",
            subs_fn, store_fn, batch, effective_keep, clock)
    selection = selector.select(provider)
    selector.prove(provider, [selection.exit_id])
    if not detail.get("ran"):
        raise RuntimeError(
            "probe selector did not execute the adapter "
            "(prove must route exits through the given probe)")
    text = detail.get("text") or ""
    latency = detail.get("latency")
    exc = detail.get("exc")
    if exc is not None:
        kind, code = detail.get("kind"), detail.get("code")
        # Sanctioned-exit proof: a 403 whose body carries the
        # location marker is the EGRESS (not the key) — cool OUR
        # server for google (net_err rotates the tunnel) instead of
        # retiring the lease as auth. Any other 403 keeps the old
        # auth_err meaning. Reads OUR exception body only.
        location_blocked = False
        if eff_route == "leased" and code == 403:
            try:
                from factory.linking import google_clean as _gc_b
                raw_body = (exc.read(2048) or b"")
                location_blocked = _gc_b.LOCATION_MARK in raw_body.decode(
                    "utf-8", "replace")
            except Exception:  # noqa: BLE001 (body is best-effort)
                location_blocked = False
        if eff_route == "leased":
            if code == 429:
                _report("http429")
            elif location_blocked:
                _report("net_err")
            elif code in (401, 403):
                _report("auth_err")
            elif kind in ("timeout", "url-error"):
                _report("net_err")
            else:
                _report("unknown")
        return {"provider": provider, "status": "http-error",
                "reason": kind, "latency_s": latency,
                "error_kind": kind, "http_status": code,
                "model": model or None, "route": eff_route,
                "lease": (lease_id[:8] if lease_id else None),
                "egress": egress or None,
                "clean": _clean_flag(), "clean_note": _clean_note(),
                "location_blocked": location_blocked,
                "route_reason": route_reason(provider, eff_route)}
    if eff_route == "leased":
        _report("ok")
    if not (isinstance(text, str) and text.strip()):
        if eff_route == "leased":
            _report("unknown")
        return {"provider": provider, "status": "empty-reply",
                "reason": "empty-reply", "latency_s": latency,
                "error_kind": "empty-reply", "http_status": None,
                "model": model or None, "route": eff_route,
                "lease": (lease_id[:8] if lease_id else None),
                "egress": egress or None,
                "clean": _clean_flag(), "clean_note": _clean_note(),
                "location_blocked": False,
                "route_reason": route_reason(provider, eff_route)}
    if eff_route == "leased":
        # Proven exit: a successful Google call through OUR lease is
        # the strongest clean signal — write it back so the next
        # lease prefers it (supervisor cache-first, no restart).
        try:
            from factory.precard.provider_lease_policy import (
                norm_provider as _norm_r)
            if _norm_r(provider) == "google" and egress \
                    and egress != "direct":
                if remember_fn is None:
                    from factory.linking import google_clean as _gc_r
                    remember_fn = _gc_r.remember_success
                remember_fn(egress, "google", latency)
        except Exception:  # noqa: BLE001 (upkeep never fails a probe)
            pass
    return {"provider": provider, "status": "ok",
            "reason": "", "latency_s": latency,
            "error_kind": None, "http_status": None,
            "model": model or None,
            "reply_chars": len(text), "route": eff_route,
            "lease": (lease_id[:8] if lease_id else None),
            "egress": egress or None,
            "clean": _clean_flag(), "clean_note": _clean_note(),
            "location_blocked": False,
            "route_reason": route_reason(provider, eff_route)}


def probe_all(providers=PROBE_PROVIDERS, operator_models=None,
              prompt_text=None, resolve_fn=None, key_value_fn=None,
              transport_fn_for=None, chain_fn=None, clock=None,
              route="auto", routes=None, lease_fn_for=None,
              report_fn=None, target_fn=None, registry_fn=None,
              clean_fn_for=None, remember_fn=None,
              selector_fn_for=None, subs_fn_for=None, store_fn_for=None,
              batch=5, keep=5):
    """Probe every named provider; returns [result dicts] (order kept).

    ``key_value_fn(provider) -> plaintext`` defaults to resolving the
    first set key var (in-memory only — never logged). Tests inject
    fakes for every seam (no network, no real keys). Routing mirrors
    the precard leased-tunnel path: ``route="auto"`` leases for
    tunnel-route providers (Google defaults leased — geo-block 403
    direct); ``routes`` maps provider -> "leased"/"direct" override;
    ``lease_fn_for(provider)`` injects the lease seam per provider.
    ``clean_fn_for(provider)`` injects the whitelist seam per
    provider; ``remember_fn`` injects the clean-cache write-back
    (tests pass fakes — never the real cache file).
    ``batch``/``keep`` are the injected prove caps (defaults 5, never
    hardcoded); ``selector_fn_for``/``subs_fn_for``/``store_fn_for``
    inject the select+prove seam per provider (tests pass fakes).
    """
    from factory.precard.provider_lease_policy import (
        resolve_key as _resolve)

    if operator_models is None:
        operator_models = {}
    if prompt_text is None:
        prompt_text = build_probe_prompt()
    if resolve_fn is None:
        resolve_fn = _resolve
    results = []
    for provider in providers:
        has_key, names = key_status(provider, resolve_fn=resolve_fn)
        if not has_key:
            results.append({
                "provider": provider, "status": "skipped",
                "reason": "no key resolves (%s)" % "+".join(names),
                "key_vars": names, "latency_s": None,
                "error_kind": None, "http_status": None,
                "model": None, "model_source": None})
            continue
        model = (operator_models or {}).get(provider) or default_model(
            provider, chain_fn=chain_fn)
        if not model:
            results.append({
                "provider": provider, "status": "skipped",
                "reason": ("key resolves but neither the engine nor the "
                           "probe free defaults name a model for this "
                           "provider (pass --model %s=<id> to probe with "
                           "an operator-provided model)") % provider,
                "key_vars": names, "latency_s": None,
                "error_kind": None, "http_status": None,
                "model": None, "model_source": None})
            continue
        if key_value_fn is None:
            value = ""
            for var in names:
                try:
                    hit = resolve_fn(var)
                except Exception:
                    hit = ""
                if hit:
                    value = hit
                    break
        else:
            value = key_value_fn(provider)
        transport_fn = None
        if transport_fn_for is not None:
            transport_fn = transport_fn_for(provider)
        eff = (routes or {}).get(provider, route)
        lease_fn = None
        if lease_fn_for is not None:
            lease_fn = lease_fn_for(provider)
        clean_fn = None
        if clean_fn_for is not None:
            clean_fn = clean_fn_for(provider)
        selector_fn = None
        if selector_fn_for is not None:
            selector_fn = selector_fn_for(provider)
        subs_fn = None
        if subs_fn_for is not None:
            subs_fn = subs_fn_for(provider)
        store_fn = None
        if store_fn_for is not None:
            store_fn = store_fn_for(provider)
        rec = probe_one(provider, prompt_text, model=model,
                        key_value=value, transport_fn=transport_fn,
                        clock=clock, route=eff, lease_fn=lease_fn,
                        report_fn=report_fn, target_fn=target_fn,
                        registry_fn=registry_fn, clean_fn=clean_fn,
                        remember_fn=remember_fn,
                        selector_fn=selector_fn,
                        subs_fn=subs_fn, store_fn=store_fn,
                        batch=batch, keep=keep)
        rec["key_vars"] = names
        rec["model_source"] = model_source(
            provider, operator_models, chain_fn=chain_fn)
        results.append(rec)
    return results


def probe_line(rec):
    """One human-readable probe line (names + numbers only, never values)."""
    base = "probe provider=%s status=%s route=%s" % (
        rec.get("provider"), rec.get("status"),
        rec.get("route") or ("leased" if rec.get("lease") else "direct"))
    if rec.get("lease"):
        base += " lease=%s" % rec.get("lease")
    if rec.get("egress"):
        base += " egress=%s" % rec.get("egress")
    if rec.get("clean") is True:
        base += " clean=whitelisted"
    elif rec.get("clean") is False:
        base += " clean=unlisted"
    if rec.get("location_blocked"):
        base += " blocked=location"
    if rec.get("model"):
        base += " model=%s" % rec.get("model")
    if rec.get("model_source"):
        base += " src=%s" % rec.get("model_source")
    if rec.get("latency_s") is not None:
        base += " latency_s=%.3f" % rec.get("latency_s")
    if rec.get("http_status") is not None:
        base += " http=%s" % rec.get("http_status")
    if rec.get("error_kind"):
        base += " error=%s" % rec.get("error_kind")
    if rec.get("reason") and rec.get("status") == "skipped":
        base += " reason=%s" % rec.get("reason")
    return base


def write_run_log(lines):
    """Append probe lines to the Temp run log; returns the log path."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%S")
    path = os.path.join(tempfile.gettempdir(),
                        "linker_probe_%s.log" % stamp)
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Live provider health probes (standard prompt).")
    ap.add_argument("--model", action="append", default=[],
                    help="operator-provided model: name=id (repeatable)")
    ap.add_argument("--env-file", default="",
                    help="factory env file to load keys from "
                         "(default: factory/.env beside the repo)")
    ap.add_argument("--route", default="auto",
                    choices=("auto", "leased", "direct"),
                    help="egress routing: auto leases a clean tunnel "
                         "for tunnel-route providers (Google defaults "
                         "leased — direct Google calls die with "
                         "geo-block 403) and runs direct otherwise")
    ap.add_argument("--route-provider", action="append", default=[],
                    help="per-provider route override: name=leased|direct "
                         "(repeatable)")
    args = ap.parse_args(argv)
    routes = {}
    for chunk in args.route_provider or []:
        name, sep, mode = (chunk or "").partition("=")
        if not sep or not name.strip() \
                or mode.strip() not in ("leased", "direct"):
            print("bad --route-provider %r (want name=leased|direct)"
                  % chunk, file=sys.stderr)
            return 2
        routes[name.strip()] = mode.strip()
    operator_models = {}
    for chunk in args.model or []:
        name, sep, model = (chunk or "").partition("=")
        if not sep or not name.strip() or not model.strip():
            print("bad --model %r (want name=id)" % chunk,
                  file=sys.stderr)
            return 2
        operator_models[name.strip()] = model.strip()
    root = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(root, "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    env_info = load_factory_env(args.env_file or None)
    prompt_text = build_probe_prompt()
    results = probe_all(operator_models=operator_models,
                        prompt_text=prompt_text,
                        route=args.route, routes=routes or None)
    lines = [probe_line(r) for r in results]
    lines.append("google route default: leased — %s" % GOOGLE_TUNNEL_REASON)
    log_path = write_run_log(lines)
    print("env loaded=%s vars=%s" % (
        env_info["loaded"], "+".join(env_info["vars"]) or "-"))
    for line in lines:
        print(line)
    print("log=%s" % log_path)
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
