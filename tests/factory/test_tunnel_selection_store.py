"""Wave 1 / T2 — provider-aware store + paid-first subscription adapter.

Hermetic: fake subs/probes, tmp file store, injected clock.
No network, no keys, no real disk beyond tmp_path.
Secrets appear as names only, never values.
"""

from __future__ import annotations


def _make_selector(store, subs_rows=None, clock_value=0.0, **store_kwargs):
    from factory.net.tunnel_selection import ProviderProbe, SubscriptionSource, TunnelSelector

    now = [float(clock_value)]

    class FakeSubs(SubscriptionSource):
        def __init__(self, rows):
            self._rows = list(rows or [])
            self.refresh_calls = 0

        def refresh(self):
            self.refresh_calls += 1
            return [dict(r) for r in self._rows]

    class FakeProbe(ProviderProbe):
        def probe(self, exit_id):
            return "clean"

    subs = FakeSubs(subs_rows)
    sel = TunnelSelector(
        subs=subs,
        probes={"google": FakeProbe(), "groq": FakeProbe()},
        store=store,
        clock=lambda: now[0],
    )
    return sel, subs, now


def _real_store(tmp_path, clock, **kwargs):
    from factory.net.tunnel_selection import ProviderCacheStore

    return ProviderCacheStore(str(tmp_path / "clean_cache.json"), clock=clock, **kwargs)


def test_select_serves_fresh_provider_cache_without_refresh(tmp_path):
    now = [1000.0]
    store = _real_store(tmp_path, clock=lambda: now[0], ttl_seconds=3600.0)
    store.write("google", [{"id": "g1", "latency_ms": 10.0}])
    sel, subs, _ = _make_selector(store, subs_rows=[], clock_value=1000.0)
    # Rebind selector clock to the same frozen time.
    sel._clock = lambda: now[0]
    got = sel.select("google")
    assert got.exit_id == "g1"
    assert got.whitelisted is True
    assert got.served_from == "cache"
    assert subs.refresh_calls == 0


def test_stale_cache_is_miss(tmp_path):
    now = [0.0]
    store = _real_store(tmp_path, clock=lambda: now[0], ttl_seconds=100.0)
    store.write("google", [{"id": "stale1", "latency_ms": 5.0}])
    now[0] = 1000.0  # well past ttl
    sel, subs, _ = _make_selector(
        store, subs_rows=[{"id": "fresh1", "source": "free"}], clock_value=1000.0
    )
    sel._clock = lambda: now[0]
    got = sel.select("google")
    assert got.exit_id == "fresh1"
    assert got.served_from == "subscription"
    assert subs.refresh_calls == 1


def test_provider_cache_isolation_google_vs_groq(tmp_path):
    from factory.net.tunnel_selection import NoTunnelExit

    now = [500.0]
    store = _real_store(tmp_path, clock=lambda: now[0], ttl_seconds=3600.0)
    store.write("google", [{"id": "g-only", "latency_ms": 7.0}])
    sel, subs, _ = _make_selector(store, subs_rows=[], clock_value=500.0)
    sel._clock = lambda: now[0]
    # Google serves its own rows without refresh.
    assert sel.select("google").exit_id == "g-only"
    assert subs.refresh_calls == 0
    # Groq must never see Google rows: empty subs -> honest NoTunnelExit.
    try:
        sel.select("groq")
    except NoTunnelExit:
        pass
    else:  # pragma: no cover - global cache would land here
        raise AssertionError("groq served google rows: cache is not provider-aware")
    # After writing groq rows each provider serves its own.
    store.write("groq", [{"id": "q-only", "latency_ms": 9.0}])
    assert sel.select("groq").exit_id == "q-only"
    assert sel.select("google").exit_id == "g-only"


def test_paid_first_ordering_in_refresh(tmp_path):
    now = [200.0]
    store = _real_store(tmp_path, clock=lambda: now[0], ttl_seconds=3600.0)
    rows = [
        {"id": "free-a", "source": "free"},
        {"id": "paid-b", "source": "paid"},
        {"id": "free-c", "source": "free"},
    ]
    sel, subs, _ = _make_selector(store, subs_rows=rows, clock_value=200.0)
    sel._clock = lambda: now[0]
    got = sel.select("google")
    assert got.exit_id == "paid-b"
    assert got.whitelisted is False
    assert got.served_from == "subscription"
    # Source tags only: no subscription values leak into the selection.
    assert "http" not in got.exit_id and "token" not in got.exit_id.lower()


def test_dedup_singletons(tmp_path):
    from factory.net.tunnel_selection import dedup_rows, order_paid_first

    rows = [
        {"id": "dup", "source": "free"},
        {"id": "dup", "source": "free"},
        {"id": "paid-1", "source": "paid"},
        {"id": "paid-1", "source": "paid"},
        {"id": "", "source": "free"},
    ]
    ordered = order_paid_first(dedup_rows(rows))
    ids = [r["id"] for r in ordered]
    assert ids == ["paid-1", "dup"]

    # End-to-end through select: duplicates collapse to one candidate.
    now = [300.0]
    store = _real_store(tmp_path, clock=lambda: now[0])
    sel, _, _ = _make_selector(store, subs_rows=rows, clock_value=300.0)
    sel._clock = lambda: now[0]
    assert sel.select("google").exit_id == "paid-1"


def test_remember_empty_never_touches_file(tmp_path):
    from factory.net.tunnel_selection import ProviderCacheStore

    target = tmp_path / "clean_cache.json"
    now = [400.0]
    store = ProviderCacheStore(str(target), clock=lambda: now[0])
    sel, _, _ = _make_selector(store, subs_rows=[], clock_value=400.0)
    sel._clock = lambda: now[0]
    sel.remember("google", "", 0)
    assert not target.exists()
    # Store-level guard: writing an empty list never creates or clears the file.
    store.write("google", [])
    assert not target.exists()
    store.write("google", [{"id": "keep", "latency_ms": 3.0}])
    assert target.exists()
    store.write("google", [])
    assert store.read("google")[0]["id"] == "keep"


def test_injected_clock_drives_ttl_boundary(tmp_path):
    now = [0.0]
    store = _real_store(tmp_path, clock=lambda: now[0], ttl_seconds=100.0)
    store.write("google", [{"id": "edge", "latency_ms": 1.0}])
    now[0] = 99.0
    assert [r["id"] for r in store.read("google")] == ["edge"]
    now[0] = 101.0
    assert store.read("google") == []


def test_store_write_then_read_per_provider(tmp_path):
    now = [700.0]
    store = _real_store(tmp_path, clock=lambda: now[0], ttl_seconds=3600.0)
    store.write("google", [{"id": "g1", "latency_ms": 4.0}])
    store.write("groq", [{"id": "q1", "latency_ms": 6.0}])
    assert [r["id"] for r in store.read("google")] == ["g1"]
    assert [r["id"] for r in store.read("groq")] == ["q1"]
    # Rows carry id + timing only: no links, keys, or subscription values.
    row = store.read("google")[0]
    assert set(row) <= {"id", "latency_ms", "source"}
    assert "http" not in str(row.values())


def test_injected_caps_override(tmp_path):
    now = [0.0]
    store = _real_store(
        tmp_path, clock=lambda: now[0], ttl_seconds=10.0, max_rows=2
    )
    store.write(
        "google",
        [
            {"id": "a", "latency_ms": 1.0},
            {"id": "b", "latency_ms": 2.0},
            {"id": "c", "latency_ms": 3.0},
        ],
    )
    assert [r["id"] for r in store.read("google")] == ["a", "b"]
    now[0] = 11.0
    assert store.read("google") == []
