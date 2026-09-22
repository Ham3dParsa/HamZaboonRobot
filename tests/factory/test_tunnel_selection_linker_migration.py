"""T5 — linker migration onto the tunnel-selection seam (hermetic).

Locked scope (phase-03): the linker Google-clean helper becomes a formal
adapter over the locked seam (select / prove / remember + the two registered
adapters); probe copies converge on that adapter surface; the old direct
helper path is deleted in this same ticket. Linker core, screening
functions, evidence strings, ranking internals, and the cloud registry stay
untouched (forbidden zone).

All doubles are injected fakes: no network, no keys, no disk beyond
tmp_path. Secrets appear as names only, never values.
"""

import inspect
import os

import pytest

from factory.linking import google_clean as gc

NOW = 1_000_000.0
TTL = 3600.0

LOC_BODY = b'{"error": {"code": 400, "message": "User location is not supported for the API use.", "status": "FAILED_PRECONDITION"}}'
KEY_BODY = b'{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}'


def _rows():
    return [
        {"server_id": "s-fresh-slow", "provider": "google",
         "last_ok_ts": NOW - 100, "latency_ms": 900},
        {"server_id": "s-fresh-fast", "provider": "google",
         "last_ok_ts": NOW - 50, "latency_ms": 120},
        {"server_id": "s-stale", "provider": "google",
         "last_ok_ts": NOW - 99999, "latency_ms": 10},
        {"server_id": "s-zen", "provider": "zen",
         "last_ok_ts": NOW - 10, "latency_ms": 5},
    ]


def test_linker_clean_selection_through_seam():
    """Linker clean selection crosses the locked seam (no direct path).

    The keyless verdict executes behind the registered KeylessGoogleProbe
    shape (prove contract) and the preference step serves through
    TunnelSelector.select (select contract) — both observable with fakes.
    """
    from factory.net.tunnel_selection import KeylessGoogleProbe, NoTunnelExit

    # Adapter shape: the linker helper exposes the registered probe shape.
    probe = gc.make_google_probe(
        open_fn=lambda url, timeout: (401, ""))
    assert isinstance(probe, KeylessGoogleProbe)
    assert probe.probe("any-exit") == "clean"
    blocked = gc.make_google_probe(
        open_fn=lambda url, timeout: (400, LOC_BODY.decode()))
    assert blocked.probe("any-exit") == "blocked"
    unknown = gc.make_google_probe(
        open_fn=lambda url, timeout: (429, ""))
    assert unknown.probe("any-exit") == "unknown"

    # check_exit verdict arrives via the probe seam (fake probe, no network).
    seen = {}

    class _FakeProbe:
        def __init__(self, check_fn=None):
            seen["check_fn"] = check_fn

        def probe(self, exit_id):
            seen["exit"] = exit_id
            return seen["check_fn"](exit_id)

    import factory.linking.google_clean as _gc_mod
    real_probe = _gc_mod.KeylessGoogleProbe
    _gc_mod.KeylessGoogleProbe = _FakeProbe
    try:
        rec = gc.check_exit(open_fn=lambda u, t: (401, ""))
    finally:
        _gc_mod.KeylessGoogleProbe = real_probe
    assert seen["exit"] == "direct"
    assert rec == {"ok": True, "verdict": "clean",
                   "kind": "key-required", "latency_ms": 0}

    # select_clean_exit serves through TunnelSelector.select (fake, no IO).
    selected = {}

    class _FakeSelector:
        def __init__(self, **kwargs):
            selected["kwargs"] = kwargs

        def select(self, provider):
            selected["provider"] = provider
            from factory.net.tunnel_selection import Selection
            return Selection(exit_id="s-fresh-fast", lease=None,
                             whitelisted=True, served_from="cache")

    real_selector = _gc_mod.TunnelSelector
    _gc_mod.TunnelSelector = _FakeSelector
    try:
        assert gc.select_clean_exit(
            _rows(), ["s-fresh-fast", "s-other"],
            now=NOW, ttl=TTL) == "s-fresh-fast"
    finally:
        _gc_mod.TunnelSelector = real_selector
    assert selected["provider"] == "google"

    # An empty seam (NoTunnelExit) reads as None — never an invented exit.
    class _EmptySelector:
        def __init__(self, **kwargs):
            pass

        def select(self, provider):
            raise NoTunnelExit(provider)

    _gc_mod.TunnelSelector = _EmptySelector
    try:
        assert gc.select_clean_exit(
            _rows(), ["s-other"], now=NOW, ttl=TTL) is None
    finally:
        _gc_mod.TunnelSelector = real_selector


def test_google_cache_namespace_separate_from_groq(tmp_path):
    """Provider-aware cache on the linker path: Google rows never leak.

    The linker write-back namespaces by provider; the Google read path
    serves Google rows only (a Groq select never sees them and vice
    versa). Tmp file only — never the real cache file.
    """
    from factory.precard.provider_lease_policy import (
        clean_cache_candidates,
        load_clean_cache,
    )
    path = str(tmp_path / "clean_cache.json")
    gc.remember_success("s-g", "google", 11, now=NOW, path=path)
    gc.remember_success("s-q", "groq", 22, now=NOW, path=path)
    entries = load_clean_cache(path)
    assert gc.fresh_clean_exits(entries, now=NOW, ttl=TTL) == ["s-g"]
    groq_rows = clean_cache_candidates(entries, "groq", NOW, TTL)
    assert [r["server_id"] for r in groq_rows] == ["s-q"]
    # End-to-end preference honors the namespace too.
    assert gc.select_clean_exit(
        entries, ["s-g", "s-q"], now=NOW, ttl=TTL) == "s-g"
    assert gc.select_clean_exit(
        entries, ["s-q"], now=NOW, ttl=TTL) is None


def test_linker_core_untouched():
    """Forbidden zone: linker core, sieves, gates, evidence, ranking,
    registry — none cross the seam, none import the linker helper."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent.parent
    forbidden = [
        root / "factory" / "linking" / "linker.py",
        root / "factory" / "linking" / "gates.py",
        root / "factory" / "precard" / "provider_registry.py",
    ]
    for path in forbidden:
        text = path.read_text(encoding="utf-8")
        assert "tunnel_selection" not in text, path.name
        assert "TunnelSelector" not in text, path.name
        assert "ProviderProbe" not in text, path.name
        assert "google_clean" not in text, path.name
    # Core symbols still intact (migration adds adapters, removes nothing).
    from factory.linking import linker as _linker
    for name in ("arbitrate_link", "evidence_families", "shortlist",
                 "quarantine_check"):
        assert callable(getattr(_linker, name)), name
    from factory.linking import gates as _gates
    assert _gates is not None


def test_old_linker_helper_path_deleted_same_pr():
    """Route-delete rule: the old direct helper path is gone this ticket.

    The rival ``def classify`` (single-owner guard offender) is deleted —
    the verdict table lives behind ``classify_exit`` and executes through
    the probe seam; selection serves through the select seam.
    """
    assert not hasattr(gc, "classify")  # old entry deleted, not aliased
    assert callable(getattr(gc, "classify_exit"))
    assert callable(getattr(gc, "make_google_probe"))
    source = inspect.getsource(gc)
    assert "def classify(" not in source
    check_source = inspect.getsource(gc.check_exit)
    assert "make_google_probe" in check_source  # verdict via prove shape
    assert ".probe(" in check_source
    adapter_source = inspect.getsource(gc.make_google_probe)
    assert "KeylessGoogleProbe" in adapter_source  # registered probe shape
    assert "classify_exit" in adapter_source  # one verdict table, no copy
    select_source = inspect.getsource(gc.select_clean_exit)
    assert "TunnelSelector" in select_source  # preference via select seam
    assert ".select(" in select_source


@pytest.mark.skipif(
    os.environ.get("HAMZABAN_LIVE_LINKER") != "1",
    reason="gated live: needs HAMZABAN_LIVE_LINKER=1 + network; CI skips",
)
def test_live_linker_single_verify_capped():
    """Live single-exit keyless verify, explicit flag only (gated)."""
    rec = gc.verify_and_remember("", "", timeout=10)
    assert rec["verdict"] in ("clean", "blocked", "unknown")
