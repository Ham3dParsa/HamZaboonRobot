"""Google-clean egress selection (linker path) — formal seam adapter.

Thin client-side companion to the known-good supervisor technique
(``tools/egress/supervisor.py --probe --top-n 30 --probe-google 15``:
tunnel the top-N alive servers one by one, take one free
``models:list`` ping each through ``TARGETS["google"]["probe"]``;
``note == "live"`` rows move first via
``provider_lease_policy.order_google_first`` and persist to the
``egress_pool.json`` whitelist).

The supervisor side already prefers clean exits with no restart: every
``/v1/lease`` loads ``tools/egress/clean_cache.json`` and takes a fresh
provider-matched row behind one real-ping gate (``lease_for`` R7
cache-first). What the linker path was missing is the client half,
exposed here as a formal adapter over the locked tunnel-selection seam
(``factory.net.tunnel_selection`` — select / prove / remember + the two
registered adapters, consumed read-only, never reimplemented):

- a keyless Google-reachability check (a bare ``models:list`` GET with
  NO key appended — never a billed call, never a secret on the wire),
  executed behind the registered :class:`KeylessGoogleProbe` shape via
  :func:`make_google_probe` (the prove contract), so any holder of a
  proxy URL (a leased tunnel, a run child env) can prove its exit
  without spending quota;
- write-back of proven exits into ``clean_cache.json`` through the
  single writers (``record_clean_success`` + ``save_clean_cache``) so
  the NEXT lease is a CACHE HIT on a whitelisted exit;
- pure selection (:func:`select_clean_exit`) served through
  :class:`TunnelSelector.select` over an ephemeral per-provider seed
  (the select contract) + annotation (:func:`clean_note`) both the
  probe module and the WebUI runs share instead of each taking
  whatever lease the supervisor hands out blind.

The verdict table lives behind :func:`classify_exit` (renamed from the
old ``classify`` entry so the ``factory.core.llm_json`` single-owner
guard stays green — one taxonomy owner, no rival ``def classify``).
The supervisor ``clean_cache.json`` file layout stays behind the
``provider_lease_policy`` single readers/writers (shared-infra compat).

Secret discipline: this module never reads, logs, or writes key
VALUES. The keyless check sends no key at all; cache rows carry
server ids + timing only (same secret-free rule as the pool writer).
Hermetic by design: ``open_fn``/``clock``/rows inject (no network in
tests); production entry points are the ``production_open_fn`` +
``verify_and_remember`` pair.
"""

from __future__ import annotations

import os
import time
import urllib.request

from factory.net.tunnel_selection import (
    KeylessGoogleProbe,
    NoTunnelExit,
    SubscriptionSource,
    TunnelSelector,
)
from factory.precard.provider_lease_policy import (
    CLEAN_CACHE_TTL_S,
    clean_cache_candidates,
    load_clean_cache,
    norm_provider,
    record_clean_success,
    save_clean_cache,
)

#: Keyless reachability target: models:list WITHOUT any key (no key
#: appended, none sent). A clean egress answers with a key complaint;
#: a sanctioned egress answers location-blocked. Either way the call
#: is unbilled (no generate/model call) and keyless.
GOOGLE_REACH_URL = ("https://generativelanguage.googleapis.com/"
                    "v1beta/models?pageSize=1")

#: Body marker the Google endpoint returns for sanctioned egress
#: countries (same marker ``supervisor.google_probe`` keys on).
LOCATION_MARK = "not supported for the API use"

#: Body markers that prove the egress reached Google and only the
#: (deliberately absent) key is the problem — i.e. a clean exit.
KEY_PROBLEM_MARKS = ("API_KEY_INVALID", "API key not valid",
                     "UNAUTHENTICATED")


def classify_exit(code, body):
    """(verdict, kind) for a keyless reachability answer (pure).

    verdict is "clean" (egress reaches Google fine), "blocked"
    (sanctioned/geo exit), or "unknown" (quota or inconclusive —
    never judge an exit on these). ``code`` is int for HTTP answers,
    "?" for non-HTTP failures; ``body`` is best-effort text (""
    when unreadable).
    """
    text = str(body or "")
    if code == 200:
        return "clean", "live"
    if code == 400 and LOCATION_MARK in text:
        return "blocked", "location-blocked"
    if code == 400 and any(m in text for m in KEY_PROBLEM_MARKS):
        return "clean", "key-required"
    if code == 401:
        return "clean", "key-required"
    if code == 403 and any(m in text for m in KEY_PROBLEM_MARKS):
        return "clean", "key-required"
    if code == 403:
        return "blocked", "forbidden"
    if code == 429:
        return "unknown", "quota"
    if code == "?":
        return "unknown", "net-error"
    return "unknown", ("http-%s" % code)


def production_open_fn(proxy_url):
    """``open_fn(url, timeout) -> (code, body)`` over one exit (keyless).

    ``proxy_url`` selects the exit (tunnel proxy) or "" for the true
    direct exit (empty ``ProxyHandler`` bypasses ambient env proxies so
    the datum is the machine's own egress, not the operator's client
    proxy). Sends NO key — the URL carries none and no auth header is
    set. Returns (200, body) on HTTP success; (int-code, up-to-2KB
    body) on HTTP errors; ("?", "") on non-HTTP failures.
    """
    if proxy_url:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {"http": proxy_url, "https": proxy_url}))
    else:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}))

    def _open(url, timeout=20):
        req = urllib.request.Request(
            url, headers={"User-Agent": "HamZaban-factory/1.0"})
        try:
            with opener.open(req, timeout=timeout) as resp:
                return (getattr(resp, "status", 200), "")
        except Exception as exc:  # noqa: BLE001 (every failure is a datum)
            raw = getattr(exc, "code", "?")
            code = (raw if isinstance(raw, int)
                    and not isinstance(raw, bool) else "?")
            body = ""
            try:
                body = (exc.read(2048) or b"").decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 (body is best-effort)
                pass
            return code, body

    return _open


def make_google_probe(open_fn=None, proxy_url="", timeout=20,
                       clock=None, detail=None):
    """Formal adapter: keyless Google reachability as a registered probe.

    Returns a :class:`KeylessGoogleProbe` whose single check executes
    the keyless ``models:list`` verdict behind the prove contract
    ("clean" on a proven exit, "blocked" on a sanctioned egress,
    "unknown" otherwise — transport errors are unknown, never
    blocked). ``open_fn``/``proxy_url``/``timeout``/``clock`` inject
    exactly like :func:`check_exit` (tests pass fakes — no network
    here). ``detail`` optionally receives ``{"kind", "latency_ms"}``
    for the caller that needs the annotation datum (same pattern as
    the probe module's error datum — OUR measurement only).
    """
    if open_fn is None:
        open_fn = production_open_fn(proxy_url)
    now = clock or time.monotonic

    def _check(exit_id):
        del exit_id  # single-exit check: egress rides the opener/proxy
        start = now()
        try:
            code, body = open_fn(GOOGLE_REACH_URL, timeout)
        except Exception as exc:  # noqa: BLE001 (classify, never raise)
            kind = ("timeout" if isinstance(exc, TimeoutError)
                    or "timed out" in str(
                        getattr(exc, "reason", "") or "").lower()
                    else "net-error")
            if detail is not None:
                detail.update({"kind": kind,
                               "latency_ms": int((now() - start) * 1000)})
            return "unknown"
        verdict, kind = classify_exit(code, body)
        if detail is not None:
            detail.update({"kind": kind,
                           "latency_ms": int((now() - start) * 1000)})
        return verdict

    return KeylessGoogleProbe(check_fn=_check)


def check_exit(open_fn=None, proxy_url="", timeout=20, clock=None):
    """Keyless reachability verdict for one exit (no key, unbilled).

    ``open_fn(url, timeout)`` defaults to
    :func:`production_open_fn` over ``proxy_url``; tests inject fakes
    (no network). The verdict arrives via the probe seam
    (:func:`make_google_probe` + ``probe("direct")`` — the old direct
    ``classify`` call is deleted). Returns ``{"ok", "verdict", "kind",
    "latency_ms"}``: ok True only for a clean exit. Never raises —
    opener failures classify as unknown/net-error with measured
    latency.
    """
    detail = {}
    probe = make_google_probe(open_fn=open_fn, proxy_url=proxy_url,
                              timeout=timeout, clock=clock, detail=detail)
    verdict = probe.probe("direct")
    kind = detail.get("kind")
    if kind is None:  # foreign probe double that skipped the check datum
        kind = {"clean": "live", "blocked": "forbidden"}.get(
            verdict, "net-error")
    return {"ok": verdict == "clean", "verdict": verdict, "kind": kind,
            "latency_ms": int(detail.get("latency_ms", 0))}


def default_cache_path():
    """Absolute ``tools/egress/clean_cache.json`` for this repo.

    The SAME file the supervisor reads on every ``/v1/lease`` — a
    write here takes effect on the next lease with no restart.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", ".."))
    return os.path.join(root, "tools", "egress", "clean_cache.json")


def fresh_clean_exits(entries=None, now=None, ttl=None, path=None):
    """Fresh whitelisted google exit ids, earliest-latency first.

    ``entries`` defaults to loading ``path`` (default cache file);
    missing/corrupt reads as [] (no whitelist — honest, never an
    exception). ``now``/``ttl`` inject for hermetic tests (ttl garbage
    falls back to the 24h default inside the net home).
    """
    if entries is None:
        entries = load_clean_cache(path or default_cache_path())
    at = time.time() if now is None else now
    rows = clean_cache_candidates(entries, "google", at, ttl)
    return [r["server_id"] for r in rows
            if isinstance(r, dict) and r.get("server_id")]


class _CandidateSource(SubscriptionSource):
    """One-shot candidate source for the linker preference step (no IO).

    ``refresh`` offers exactly the fresh-and-available ids in
    earliest-latency order; tags are "free" (clean-tunnel paid-ness is
    decided by the supervisor lease, never here — no values leak).
    """

    def __init__(self, ids):
        self._rows = [{"id": sid, "source": "free"}
                      for sid in ids or () if sid]

    def refresh(self):
        return [dict(r) for r in self._rows]


class _SeededProviderStore:
    """Ephemeral per-provider seed for the linker preference step.

    Same read/write shape as the provider-aware cache: the "google"
    namespace carries only the fresh whitelisted ids (a Groq select
    would never see them). Lives for one call — the durable
    supervisor file stays behind the single writers (remember path).
    """

    def __init__(self, provider, ids):
        self._provider = provider
        self._rows = [{"id": sid, "latency_ms": 0.0}
                      for sid in ids or () if sid]

    def read(self, provider):
        if provider != self._provider:
            return []
        return [dict(r) for r in self._rows]

    def write(self, provider, rows):
        if provider == self._provider and rows:
            self._rows = [dict(r) for r in rows]


def select_clean_exit(entries, available_ids, now=None, ttl=None):
    """First fresh whitelisted id present in ``available_ids`` (pure).

    The preference step, served through ``TunnelSelector.select``
    over an ephemeral per-provider seed (the select contract — the
    old direct ``clean_cache_candidates`` loop is deleted): a Google
    lease should take this exit when it is offered; None means no
    verified exit is available (fall back honestly — never invent
    one). No network, no files, no keys.
    """
    fresh = fresh_clean_exits(entries, now=now, ttl=ttl)
    live = set(available_ids or ())
    cands = [sid for sid in fresh if sid in live]
    if not cands:
        return None
    selector = TunnelSelector(subs=_CandidateSource(cands),
                              probes={},
                              store=_SeededProviderStore("google", cands),
                              clock=time.time)
    try:
        return selector.select("google").exit_id
    except NoTunnelExit:
        return None


def clean_note(server_id, whitelist_ids):
    """Short lease annotation: whitelisted vs unlisted exit (pure)."""
    if not server_id:
        return ""
    if server_id in set(whitelist_ids or ()):
        return "whitelisted exit %s" % server_id
    return "unlisted exit %s" % server_id


def remember_success(server_id, provider="google", latency_ms=None,
                     now=None, path=None):
    """Write-back one proven exit (best-effort, never raises).

    Thin over the net home's single writers (load ->
    record_clean_success -> save_clean_cache): empty results never
    touch the file, rows stay id + timing only. Call with a REAL
    proof only (a successful Google call, or a clean keyless check) —
    a lease alone is not success.
    """
    try:
        at = time.time() if now is None else now
        cache_path = path or default_cache_path()
        entries = load_clean_cache(cache_path)
        updated = record_clean_success(entries, server_id,
                                       norm_provider(provider)
                                       or "google",
                                       latency_ms, at)
        save_clean_cache(cache_path, updated)
    except (OSError, ValueError, TypeError):
        pass


def verify_and_remember(proxy_url, server_id, provider="google",
                        open_fn=None, timeout=20, clock=None,
                        path=None):
    """Keyless-verify OUR exit, remember it when clean (never raises).

    ``proxy_url``/``server_id`` describe OUR lease only (never
    others'): one unbilled keyless check through our proxy, write-back
    on clean so the next lease prefers it. Returns the check dict
    plus ``remembered`` (True only when a clean verdict was saved).
    Check failures classify, never raise and never block a launch.
    """
    if open_fn is None:
        open_fn = production_open_fn(proxy_url)
    rec = check_exit(open_fn=open_fn, proxy_url=proxy_url,
                     timeout=timeout, clock=clock)
    rec["remembered"] = False
    if rec.get("ok") and server_id:
        remember_success(server_id, provider,
                         rec.get("latency_ms"), path=path)
        rec["remembered"] = True
    return rec
