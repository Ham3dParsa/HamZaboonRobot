"""Generic provider cycle driver (factory network home).

One module, one fix point: every provider model-list / run-launch cycle
walks the same ordered state machine — cache check, refresh, ping,
prove (in fives), remember, done — over the locked tunnel-selection
seam (``select`` / ``prove`` / ``remember`` + ``SubscriptionSource`` /
``ProviderProbe`` adapters). All I/O and key material arrive as
injected adapters; this module never touches the network, the pool
file, or secret values itself.

- ``refresh_candidates``: pure dedupe + paid-first over a supervisor
  pool snapshot, thin over the existing ``dedup_rows`` /
  ``order_paid_first`` helpers (no new egress path — the snapshot is
  data passed in, never fetched here).
- ``run_cycle``: the ordered machine, returned as DATA (``states``)
  plus Persian interface lines (``lines_fa`` — provider names and
  numbers only, never key names, values, URLs, or payloads).
- Prove is batched (``batch`` = 5 default, ``keep`` = 1 single-winner
  default — never hardcoded at the call site) behind a keyed probe
  (key NAME only, never the value — the value lives in the caller's
  ``check_fn`` closure, in-memory only). HTTP 429 (quota) cools that
  exit via the injected ``cool_fn`` (per-exit, provider-scoped);
  anything else cools nothing.
- Remember is best-effort and provider-namespaced: the winner is
  upserted at the front of its own provider namespace in the injected
  store (the existing ``ProviderCacheStore`` — another provider's rows
  never leak), then the injected ``remember_fn`` runs (clean-cache
  write-back owned by the caller). Empty (no winner) never touches
  the store.

Adding a provider is data + flag only: the provider name, its pool
rows, and its key NAME arrive as arguments; the tunnel flag arrives
as an injected ``tunneled`` set. Zero code change (see
``tests/test_provider_cycle.py::test_synthetic_provider_needs_no_code_change``).

Forbidden zone untouched: screening, evidence, ranking, and registry
rows are read-only from here (registry rows as data only — this module
never imports the registry).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from factory.net.tunnel_selection import (
    KeyedProviderProbe,
    TunnelSelector,
    dedup_rows,
    order_paid_first,
)

#: Ordered cycle states (the machine order — returned as data).
STATES = ("cache_check", "refresh", "ping", "prove", "remember", "done")

#: Prove width: five exits per batch (injected default with override).
DEFAULT_BATCH = 5

#: Single winner: a cycle serves one exit (same single-exit precedent
#: as the probe and lease-acquisition paths).
DEFAULT_KEEP = 1

#: HTTP code meaning quota-exhausted on that exit (per-exit cool).
QUOTA_HTTP_CODE = 429


def _provider_name(provider):
    """Canonical provider key: lowercase, stripped ("" when absent)."""
    return str(provider or "").strip().lower()


def refresh_candidates(pool_rows):
    """Ordered exit ids from a pool snapshot (pure, no I/O).

    Thin over the existing helpers: ``dedup_rows`` collapses to first
    occurrence per non-empty id (order preserved), ``order_paid_first``
    partitions on the source tag (paid clean-tunnel infra first).
    Rows without an id never order. No network, no files, no keys.
    """
    ordered = order_paid_first(dedup_rows(list(pool_rows or [])))
    ids = []
    for row in ordered:
        exit_id = row.get("id", "") if isinstance(row, dict) else (
            row if isinstance(row, str) else "")
        if isinstance(exit_id, str) and exit_id and exit_id not in ids:
            ids.append(exit_id)
    return ids


def _latency_number(value):
    try:
        ms = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    try:
        finite = ms == ms and abs(ms) != float("inf")
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return ms if finite else 0.0


def _safe_batch(batch):
    """Prove width with safe fallback (never raises).

    Non-numeric input (e.g. a stray string) falls back to
    ``DEFAULT_BATCH`` instead of raising out of the cycle.
    """
    try:
        return int(batch or DEFAULT_BATCH)
    except (TypeError, ValueError):
        return DEFAULT_BATCH


def build_fa_lines(provider, states):
    """Persian interface lines, one per state (names + numbers only).

    The provider NAME and counts/latencies appear; key names, secret
    values, URLs, and payload contents never do. Pure.
    """
    name = _provider_name(provider) or str(provider or "")
    by_state = {s.get("state"): s for s in states or []
                if isinstance(s, dict)}
    cache = by_state.get("cache_check", {})
    refresh = by_state.get("refresh", {})
    ping = by_state.get("ping", {})
    prove = by_state.get("prove", {})
    remember = by_state.get("remember", {})
    done = by_state.get("done", {})
    lines = []
    if cache.get("hit"):
        lines.append("چرخه %s: حافظه: برخورد (%s مورد)" % (
            name, cache.get("cached", 0)))
    else:
        lines.append("چرخه %s: حافظه: عدم برخورد (%s مورد)" % (
            name, cache.get("cached", 0)))
    lines.append("چرخه %s: تازه‌سازی: %s خروجی از %s ردیف" % (
        name, refresh.get("unique", 0), refresh.get("raw", 0)))
    lines.append("چرخه %s: پینگ: %s از %s در دسترس" % (
        name, ping.get("reachable", 0), ping.get("pinged", 0)))
    lines.append("چرخه %s: اثبات: %s تمیز از %s (بسته‌های %sتایی)" % (
        name, len(prove.get("clean") or []),
        len(prove.get("order") or []), prove.get("batch", DEFAULT_BATCH)))
    if remember.get("exit"):
        lines.append("چرخه %s: یادآوری: %s (%s میلی‌ثانیه)" % (
            name, remember.get("exit"),
            int(_latency_number(remember.get("latency_ms", 0)))))
    else:
        lines.append("چرخه %s: یادآوری: بدون برنده (ثبت نشد)" % name)
    if done.get("winner"):
        lines.append("چرخه %s: نتیجه: %s مدل روی %s" % (
            name, done.get("count", 0), done.get("winner")))
    else:
        lines.append("چرخه %s: نتیجه: توقف (%s)" % (
            name, done.get("error") or "بدون خروجی"))
    return lines


class _CycleSource:
    """One-shot candidate source for one cycle (no I/O).

    ``refresh`` offers exactly the candidate ids in the caller's
    order; rows tag "paid" (clean-tunnel infra) — paid-ness is decided
    by the snapshot, never here. Mirrors the leg/probe sources.
    """

    def __init__(self, ids):
        self._rows = [{"id": sid, "source": "paid"}
                      for sid in ids or () if sid]

    def refresh(self):
        return [dict(r) for r in self._rows]


class _CycleStore:
    """Ephemeral per-provider store for one cycle (no files).

    Same read/write shape as the provider-aware cache: namespaces are
    keyed by provider. Lives for one call — durable write-back stays
    behind the caller's store + ``remember_fn``.
    """

    def __init__(self):
        self._namespaces = {}

    def read(self, provider):
        return [dict(r) for r in self._namespaces.get(provider, [])]

    def write(self, provider, rows):
        self._namespaces[provider] = [dict(r) for r in rows or []]


def run_cycle(provider, *, store, pool_fn, ping_fn, check_fn, cool_fn,
              remember_fn, key_name="", batch=DEFAULT_BATCH,
              keep=DEFAULT_KEEP, clock=None, tunneled=None):
    """Walk the ordered cycle for one provider; return the result dict.

    ``store`` has ``read(provider)`` / ``write(provider, rows)``
    (the existing ``ProviderCacheStore`` or a fake — provider
    namespaces never leak across providers). ``pool_fn()`` returns
    the supervisor pool snapshot rows (data only — no egress here).
    ``ping_fn(exit_id)`` returns ms or None (never raises out).
    ``check_fn(exit_id)`` returns ``(verdict, info)`` with verdict in
    ``clean`` / ``blocked`` / ``unknown`` and ``info`` carrying
    ``http`` (code or None), ``latency_ms``, and ``payload`` (e.g.
    the model list — data only, never rendered into lines).
    ``cool_fn(exit_id, provider, http_code)`` cools one exit on quota.
    ``remember_fn(exit_id, provider, latency_ms)`` is the clean-cache
    write-back (best-effort). ``key_name`` is the key VAR NAME for
    receipts (never the value — the value lives in the caller's
    ``check_fn`` closure). ``batch`` / ``keep`` are the injected prove
    caps (defaults 5 / 1). ``tunneled`` is the injected flag set
    (data only — recorded on the refresh state, never fetched here).

    Returns ``{"provider", "winner", "payload", "count", "error",
    "cache_hit", "states", "lines_fa"}``. Never raises for empty
    pools or unknown verdicts (honest park, never an invented exit).
    """
    want = _provider_name(provider)
    tick = clock if callable(clock) else time.monotonic
    states = []
    try:
        flagged = set(tunneled or ())
    except TypeError:
        flagged = set()

    # 1. cache check (namespaces never leak: read our provider only).
    try:
        cached = store.read(want) if store is not None else []
    except Exception:
        cached = []
    cached = [r for r in (cached or []) if isinstance(r, dict)]
    hit_id = ""
    for row in cached:
        rid = row.get("id", "")
        if isinstance(rid, str) and rid:
            hit_id = rid
            break
    states.append({"state": "cache_check", "provider": want,
                   "hit": bool(hit_id), "cached": len(cached),
                   "key_name": str(key_name or "")})

    # 2. refresh from the snapshot (dedupe + paid-first, no egress).
    try:
        raw = pool_fn() if callable(pool_fn) else []
    except Exception:
        raw = []
    raw = list(raw or [])
    candidates = refresh_candidates(raw)
    if hit_id and hit_id in candidates:
        candidates = [hit_id] + [c for c in candidates if c != hit_id]
    states.append({"state": "refresh", "provider": want,
                   "raw": len(raw), "unique": len(candidates),
                   "candidates": list(candidates),
                   "tunneled": want in flagged})

    if not candidates:
        states.append({"state": "ping", "provider": want,
                       "pinged": 0, "reachable": 0, "latencies": {}})
        states.append({"state": "prove", "provider": want,
                        "batch": _safe_batch(batch),
                        "order": [], "clean": [], "blocked": [],
                       "unknown": []})
        states.append({"state": "remember", "provider": want,
                       "exit": "", "written": False})
        states.append({"state": "done", "provider": want,
                       "winner": None, "count": 0, "cache_hit": False,
                       "error": "no exit available (pool empty)"})
        return {"provider": want, "winner": None, "payload": None,
                "count": 0, "error": "no exit available (pool empty)",
                "cache_hit": False, "states": states,
                "lines_fa": build_fa_lines(want, states)}

    # 3. ping (reachability gate; failures fall back, never raise).
    latencies = {}
    for exit_id in candidates:
        try:
            ms = ping_fn(exit_id) if callable(ping_fn) else None
        except Exception:
            ms = None
        num = _latency_number(ms) if ms is not None else 0.0
        if ms is not None:
            latencies[exit_id] = num
    reachable = [e for e in candidates if e in latencies]
    reachable.sort(key=lambda e: latencies[e])
    order = reachable + [e for e in candidates if e not in latencies]
    states.append({"state": "ping", "provider": want,
                   "pinged": len(candidates),
                   "reachable": len(reachable),
                   "latencies": dict(latencies)})

    # 4. prove in fives over the locked seam (keyed probe, key NAME).
    infos = {}

    def _check(exit_id):
        try:
            verdict, info = check_fn(exit_id)
        except Exception:
            verdict, info = "unknown", {"http": None}
        if not isinstance(info, dict):
            info = {"http": None}
        infos[exit_id] = dict(info)
        if verdict == "clean":
            return "clean"
        if verdict == "blocked":
            return "blocked"
        return "unknown"

    width = _safe_batch(batch)
    if width <= 0:
        width = len(order)
    depth = int(keep if isinstance(keep, int) and not isinstance(
        keep, bool) else DEFAULT_KEEP)
    if depth <= 0:
        depth = DEFAULT_KEEP
    probe = KeyedProviderProbe(key_name=str(key_name or ""),
                               check_fn=_check)
    selector = TunnelSelector(subs=_CycleSource(order),
                              probes={want: probe},
                              store=_CycleStore(), clock=tick,
                              batch=width, keep=depth)
    try:
        selection = selector.select(want)
        ordered = [selection.exit_id] + [
            e for e in order if e != selection.exit_id]
    except Exception:
        ordered = list(order)
    proof = selector.prove(want, ordered)
    for exit_id in ordered:
        info = infos.get(exit_id) or {}
        try:
            code = info.get("http")
        except AttributeError:
            code = None
        if code == QUOTA_HTTP_CODE and exit_id not in (proof.clean or []):
            try:
                if callable(cool_fn):
                    cool_fn(exit_id, want, code)
            except Exception:
                pass
    states.append({"state": "prove", "provider": want,
                   "batch": width, "keep": depth,
                   "order": list(ordered),
                   "clean": list(proof.clean or []),
                   "blocked": list(proof.blocked or []),
                   "unknown": list(proof.unknown or [])})

    # 5. remember (single winner; empty never touches the store).
    winner = (proof.clean or [None])[0]
    payload = None
    count = 0
    winner_latency = 0.0
    if winner:
        info = infos.get(winner) or {}
        payload = info.get("payload")
        try:
            count = len(payload) if payload is not None else 0
        except TypeError:
            count = 0
        winner_latency = _latency_number(info.get("latency_ms", 0.0))
        merged = ([{"id": winner, "latency_ms": winner_latency}]
                  + [r for r in cached
                     if isinstance(r, dict) and r.get("id") != winner])
        written = False
        try:
            if store is not None:
                store.write(want, merged)
                written = True
        except Exception:
            written = False
        try:
            if callable(remember_fn):
                remember_fn(winner, want, winner_latency)
            remembered = True
        except Exception:
            remembered = False
        states.append({"state": "remember", "provider": want,
                       "exit": winner, "latency_ms": winner_latency,
                       "written": bool(written),
                       "remembered": bool(remembered)})
    else:
        states.append({"state": "remember", "provider": want,
                       "exit": "", "written": False})

    # 6. done.
    if winner:
        states.append({"state": "done", "provider": want,
                       "winner": winner, "count": count,
                       "cache_hit": bool(hit_id and winner == hit_id),
                       "error": None})
        return {"provider": want, "winner": winner, "payload": payload,
                "count": count, "error": None,
                "cache_hit": bool(hit_id and winner == hit_id),
                "states": states,
                "lines_fa": build_fa_lines(want, states)}
    states.append({"state": "done", "provider": want, "winner": None,
                   "count": 0, "cache_hit": False,
                   "error": "no clean exit (all blocked or unknown)"})
    return {"provider": want, "winner": None, "payload": None,
            "count": 0, "error": "no clean exit (all blocked or unknown)",
            "cache_hit": False, "states": states,
            "lines_fa": build_fa_lines(want, states)}


__all__ = ["STATES", "DEFAULT_BATCH", "DEFAULT_KEEP", "QUOTA_HTTP_CODE",
           "refresh_candidates", "build_fa_lines", "run_cycle"]
