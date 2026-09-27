"""Generic provider cycle driver (factory network home).

Test-first suite for ``factory.net.provider_cycle``: the ordered
cache-check -> refresh -> ping -> prove-in-fives -> remember -> done
state machine over the locked tunnel-selection seam with injected
adapters. No network, no keys, no files outside tmp paths — every
adapter is a fake. Secret VALUES never appear in outputs (names only).
"""

import time

import pytest

from factory.net import provider_cycle as cycle
from factory.net.tunnel_selection import ProviderCacheStore


def _fake_store(initial=None):
    namespaces = dict(initial or {})

    class _Store:
        def read(self, provider):
            return [dict(r) for r in namespaces.get(provider, [])]

        def write(self, provider, rows):
            namespaces[provider] = [dict(r) for r in rows or []]

    return _Store(), namespaces


def _run(check=None, pool=None, ping=None, store=None, provider="synthx",
         key_name="SYNTHX_API_KEY_G1", cool_log=None, remember_log=None,
         writes=None, batch=None, keep=None):
    store = store or _fake_store()[0]
    pool_rows = pool if pool is not None else [
        {"id": "s1", "source": "paid"},
        {"id": "s1", "source": "paid"},
        {"id": "s2", "source": "free"},
    ]
    ping_fn = ping if ping is not None else (lambda exit_id: 3.0)
    checks = check if check is not None else {
        "s1": ("unknown", {"http": None}),
        "s2": ("clean", {"http": None, "latency_ms": 12.0,
                          "payload": ["m1", "m2"]}),
    }

    def _check(exit_id):
        verdict, info = checks.get(exit_id, ("unknown", {"http": None}))
        return verdict, dict(info)

    def _cool(exit_id, prov, code):
        (cool_log if cool_log is not None else []).append(
            (exit_id, prov, code))

    def _remember(exit_id, prov, latency_ms):
        (remember_log if remember_log is not None else []).append(
            (exit_id, prov, latency_ms))

    _store = store
    orig_write = _store.write

    def _write(provider, rows):
        (writes if writes is not None else []).append((provider, list(rows)))
        return orig_write(provider, rows)

    _store.write = _write
    extra = {}
    if batch is not None:
        extra["batch"] = batch
    if keep is not None:
        extra["keep"] = keep
    return cycle.run_cycle(
        provider, store=_store,
        pool_fn=lambda: [dict(r) for r in pool_rows],
        ping_fn=ping_fn, check_fn=_check,
        cool_fn=_cool, remember_fn=_remember,
        key_name=key_name, **extra)


def test_states_ordered_and_data_only():
    res = _run()
    assert [s["state"] for s in res["states"]] == list(cycle.STATES)
    assert res["provider"] == "synthx"
    assert res["winner"] == "s2"
    assert res["count"] == 2
    assert res["error"] is None


def test_refresh_dedupes_and_paid_first():
    res = _run()
    refresh = next(s for s in res["states"] if s["state"] == "refresh")
    assert refresh["raw"] == 3
    assert refresh["unique"] == 2
    assert refresh["candidates"] == ["s1", "s2"]


def test_prove_batched_in_fives_with_keep_one():
    seen = []

    def _check(exit_id):
        seen.append(exit_id)
        return "clean", {"http": None, "latency_ms": 1.0,
                         "payload": ["m-%s" % exit_id]}

    pool = [{"id": "e%d" % i, "source": "paid"} for i in range(12)]
    res = _run(check={r["id"]: ("clean", {"http": None, "latency_ms": 1.0,
                                          "payload": ["m"]})
                      for r in pool}, pool=pool)
    prove = next(s for s in res["states"] if s["state"] == "prove")
    assert prove["batch"] == 5
    assert prove["clean"] == ["e0"]
    assert res["winner"] == "e0"


def test_quota_cool_per_exit():
    cool_log = []
    res = _run(check={
        "s1": ("unknown", {"http": 429}),
        "s2": ("clean", {"http": None, "latency_ms": 4.0,
                          "payload": ["m1"]}),
    }, cool_log=cool_log)
    assert cool_log == [("s1", "synthx", 429)]
    assert res["winner"] == "s2"


def test_remember_once_with_winner_and_namespaces():
    remember_log = []
    writes = []
    store, namespaces = _fake_store()
    res = _run(store=store, remember_log=remember_log, writes=writes)
    assert remember_log == [("s2", "synthx", 12.0)]
    assert writes and writes[0][0] == "synthx"
    assert store.read("other") == []
    assert namespaces.get("other") is None
    assert res["cache_hit"] is False


def test_empty_pool_parks_without_store_touch():
    remember_log = []
    writes = []
    store, _ = _fake_store()
    res = _run(store=store, pool=[], remember_log=remember_log,
               writes=writes)
    assert res["winner"] is None
    assert res["error"] is not None
    assert writes == []
    assert remember_log == []
    assert [s["state"] for s in res["states"]] == list(cycle.STATES)


def test_synthetic_provider_needs_no_code_change():
    """A brand-new member rides data + flag only (rule R8).

    No registry edit, no driver edit: the provider name, its pool rows,
    and its key NAME arrive as data; the tunnel flag arrives as an
    injected ``tunneled`` set. The cycle proves and remembers it.
    """
    remember_log = []
    res = cycle.run_cycle(
        "brandnew", store=_fake_store()[0],
        pool_fn=lambda: [{"id": "b1", "source": "paid"}],
        ping_fn=lambda exit_id: 2.5,
        check_fn=lambda exit_id: ("clean", {"http": None,
                                            "latency_ms": 2.5,
                                            "payload": ["bm1"]}),
        cool_fn=lambda *a: None,
        remember_fn=lambda e, p, m: remember_log.append((e, p, m)),
        key_name="BRANDNEW_API_KEY_G1",
        tunneled=frozenset({"brandnew"}))
    assert res["winner"] == "b1"
    assert res["count"] == 1
    assert remember_log == [("b1", "brandnew", 2.5)]
    assert "brandnew" in res["lines_fa"][0]


def test_persian_lines_names_and_numbers_only():
    res = _run()
    assert len(res["lines_fa"]) == len(cycle.STATES)
    blob = "\n".join(res["lines_fa"])
    assert "synthx" in blob
    assert "SYNTH" not in blob  # key NAME never leaks into lines
    assert "m1" not in blob  # payload values stay in data, not lines
    for line in res["lines_fa"]:
        assert isinstance(line, str) and line.strip()


def test_provider_store_namespaces_never_leak(tmp_path):
    path = str(tmp_path / "cycle_cache.json")
    clock = lambda: 1000.0
    store = ProviderCacheStore(path, clock=clock)
    store.write("alpha", [{"id": "a1", "latency_ms": 1.0}])
    assert store.read("alpha") == [{"id": "a1", "latency_ms": 1.0}]
    assert store.read("beta") == []
    # Driver remember for one provider leaves the other namespace alone.
    res = cycle.run_cycle(
        "beta", store=store,
        pool_fn=lambda: [{"id": "b9", "source": "paid"}],
        ping_fn=lambda exit_id: 1.0,
        check_fn=lambda exit_id: ("clean", {"http": None,
                                            "latency_ms": 1.0,
                                            "payload": []}),
        cool_fn=lambda *a: None,
        remember_fn=lambda *a: None,
        key_name="BETA_API_KEY_G1", clock=clock)
    assert res["winner"] == "b9"
    assert store.read("alpha") == [{"id": "a1", "latency_ms": 1.0}]
    assert [r["id"] for r in store.read("beta")] == ["b9"]


def test_unknown_verdict_never_cools_and_never_remembers():
    cool_log = []
    remember_log = []
    res = _run(check={"s1": ("unknown", {"http": None}),
                      "s2": ("unknown", {"http": None})},
               cool_log=cool_log, remember_log=remember_log)
    assert cool_log == []
    assert remember_log == []
    assert res["winner"] is None
    assert res["error"] is not None


def test_refresh_candidates_pure_helper():
    rows = [{"id": "x"}, {"id": "x", "source": "paid"},
            {"id": "y", "source": "free"}, {"source": "paid"}]
    assert cycle.refresh_candidates(rows) == ["x", "y"]


def test_non_numeric_batch_falls_back_without_raising():
    res = _run(batch="junk")
    prove = next(s for s in res["states"] if s["state"] == "prove")
    assert prove["batch"] == cycle.DEFAULT_BATCH
    assert res["winner"] == "s2"
    parked = _run(pool=[], batch="junk")
    prove_parked = next(
        s for s in parked["states"] if s["state"] == "prove")
    assert prove_parked["batch"] == cycle.DEFAULT_BATCH


def test_zero_ping_counts_reachable():
    res = _run(ping=lambda exit_id: 0.0)
    ping = next(s for s in res["states"] if s["state"] == "ping")
    assert ping["pinged"] == 2
    assert ping["reachable"] == 2
    assert ping["latencies"] == {"s1": 0.0, "s2": 0.0}


def test_huge_latency_never_raises():
    assert cycle._latency_number(10 ** 1000) == 0.0
    assert cycle._latency_number(float("inf")) == 0.0
    assert cycle._latency_number("12") == 12.0
    res = _run(batch=float("inf"))
    prove = next(s for s in res["states"] if s["state"] == "prove")
    assert prove["batch"] == cycle.DEFAULT_BATCH


def test_pool_file_helper_reads_tmp_pool(monkeypatch, tmp_path):
    import json as _json
    from tools.egress import supervisor as _sup
    from factory.webui import server as _srv
    pool = tmp_path / "pool.json"
    pool.write_text(_json.dumps({"servers": [
        {"id": "srv-t", "host": "127.0.0.1", "port": 9},
        {"id": "srv-w", "host": "127.0.0.1", "port": 9},
    ]}), encoding="utf-8")
    monkeypatch.setattr(_sup, "POOL_PATH", pool)
    monkeypatch.setattr(_sup, "tcp_ping",
                        lambda host, port, timeout=1.0: (
                            3 if host and port else None))
    rows = _srv._pool_snapshot_rows(clean_fn=lambda: [])
    assert [r["id"] for r in rows] == ["srv-t", "srv-w"]
    ping = _srv._cycle_ping_fn()
    assert ping("srv-t") == 3
    assert ping("unknown-exit") is None


# ─── Console thin-call paths (fakes only: no network/files/keys) ───

def test_model_list_unknown_provider_parks():
    from factory.webui import server as _srv
    states = []
    models, error = _srv.provider_model_list("nope", state_log=states)
    assert models is None
    assert error.startswith("unknown provider")
    assert states == []


def test_model_list_no_key_parks_before_cycle(monkeypatch):
    from factory.precard import provider_lease_policy as _lease
    from factory.webui import server as _srv
    monkeypatch.setattr(_lease, "resolve_key", lambda var, **k: "")
    monkeypatch.setattr(_srv, "_operator_key_values", lambda: {})
    states = []
    models, error = _srv.provider_model_list("google", state_log=states)
    assert models is None
    assert error.startswith("no key resolves")
    assert "GOOGLE_AI_API_KEY" in error  # names only, never values
    assert states == []


def test_lease_run_launch_direct_route_states(monkeypatch):
    from factory.webui import server as _srv
    states = []
    lease, error = _srv.lease_tunnel_for_run(
        "avalai", tunneled=frozenset(), state_log=states)
    assert lease is None and error is None
    assert [s["state"] for s in states] == list(cycle.STATES)
    assert states[-1].get("route") == "direct"


def test_lease_run_launch_wake_refused_parks(monkeypatch):
    from factory.webui import server as _srv
    monkeypatch.setattr(_srv, "_supervisor_token", lambda: "")
    states = []
    lease, error = _srv.lease_tunnel_for_run(
        "google", tunneled=frozenset({"google"}),
        wake_fn=lambda: False, state_log=states)
    assert lease is None and error is not None
    assert "EGRESS_SUP_TOKEN" in error  # name only
    assert [s["state"] for s in states] == list(cycle.STATES)
    assert states[-1].get("winner") is None


def test_model_list_leased_full_cycle_with_fakes(monkeypatch):
    import io
    import json as _json
    import urllib.request as _url_mod
    from factory.precard import provider_lease_policy as _lease
    from factory.webui import server as _srv

    monkeypatch.setattr(_lease, "resolve_key",
                        lambda var, **k: "FAKE-KEY-VALUE")
    monkeypatch.setattr(_srv, "_operator_key_values", lambda: {})
    monkeypatch.setattr(_srv, "_supervisor_token", lambda: "FAKE-SUP")
    monkeypatch.setattr(_srv, "_refresh_egress_client_auth",
                        lambda: None)
    remembered, reported = [], []

    class _FakeStore:
        def __init__(self):
            self.rows = {}

        def read(self, provider):
            return [dict(r) for r in self.rows.get(provider, [])]

        def write(self, provider, rows):
            self.rows[provider] = [dict(r) for r in rows or []]

    monkeypatch.setattr(_srv, "_cycle_store", lambda: _FakeStore())

    payload = {"models": [{"name": "models/fake-one"},
                          {"name": "models/fake-two"}]}

    class _FakeResp:
        def __init__(self, data):
            self._buf = io.StringIO(_json.dumps(data))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *args):
            return self._buf.read()

    class _FakeOpener:
        def open(self, req, timeout=None):
            return _FakeResp(payload)

    monkeypatch.setattr(_url_mod, "build_opener",
                        lambda *a, **k: _FakeOpener())

    states = []
    models, error = _srv.provider_model_list(
        "google", state_log=states,
        # Pinned leased: the blanket resolve_key fake above would
        # otherwise answer the tunnel-flag var too (route is data,
        # never a code change — same seam as the wake-refused test).
        tunneled=frozenset({"google"}),
        lease_fn=lambda target: {"lease_id": "L1", "mode": "tunnel",
                                 "server_id": "srv9",
                                 "proxy_url": "http://127.0.0.1:9"},
        target_fn=lambda provider: "google",
        clean_fn=lambda: ["srv9"],
        verify_fn=lambda *a, **k: {"ok": True, "remembered": True,
                                   "latency_ms": 5.0},
        remember_fn=lambda sid, prov, ms: remembered.append(
            (sid, prov, ms)),
        report_fn=lambda *a, **k: reported.append((a, k)),
        pool_fn=lambda: [{"id": "srv9", "source": "paid"},
                         {"id": "srv9", "source": "paid"},
                         {"id": "srv8", "source": "free"}],
        ping_fn=lambda exit_id: 2.0)
    assert error is None
    assert models == ["fake-one", "fake-two"]
    # Six lease states + six cycle states, in machine order.
    assert [s["state"] for s in states] == list(cycle.STATES) * 2
    refresh = [s for s in states if s["state"] == "refresh"][1]
    assert refresh["raw"] == 3 and refresh["unique"] == 2
    assert refresh["candidates"] == ["srv9", "srv8"]
    assert remembered and remembered[0][0] == "srv9"
    assert remembered[0][1] == "google"
    blob = _json.dumps({"states": states}, ensure_ascii=False)
    assert "FAKE-KEY-VALUE" not in blob
    assert "FAKE-SUP" not in blob
    lines = cycle.build_fa_lines("google", states[6:])
    assert len(lines) == len(cycle.STATES)
    assert "FAKE-KEY-VALUE" not in "\n".join(lines)


def test_model_list_direct_attributes_provider_error(monkeypatch):
    """Direct fetch keeps the real failure (provider + http, never values)."""
    import io
    import json as _json2
    import urllib.error as _httperr
    import urllib.request as _url_mod
    from factory.precard import provider_lease_policy as _lease
    from factory.webui import server as _srv

    monkeypatch.setattr(_lease, "resolve_key",
                        lambda var, **k: "FAKE-KEY-VALUE")
    monkeypatch.setattr(_srv, "_operator_key_values", lambda: {})

    def _boom(req, timeout=None):
        raise _httperr.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(_url_mod, "urlopen", _boom)
    states = []
    models, error = _srv.provider_model_list(
        "groq", state_log=states, tunneled=frozenset())
    assert models is None
    assert "http-403" in error  # attributed, never the key value
    assert "FAKE-KEY-VALUE" not in error
    assert "FAKE-KEY-VALUE" not in _json2.dumps({"states": states})
