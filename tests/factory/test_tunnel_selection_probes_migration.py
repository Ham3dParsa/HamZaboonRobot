"""T4 — probes migration onto the tunnel-selection seam (hermetic).

Locked scope (phase-02): probe_one sits behind select+prove; route_for /
lease_tunnel stay thin callers; registry untouched (registry_fn injection,
default stays on TARGETS); batch/keep injected (default 5); provider-aware
cache; paid-first via tags; forbidden zone + batch/concurrency untouched.

All doubles are injected fakes: no network, no keys, no disk. Secrets appear
as names only, never values.
"""

import inspect
import os

import pytest

from factory.linking import probe_providers as probe_mod


def _direct_registry_fn(provider):
    """Fake registry row reader: google is tunnel-route, rest direct."""
    if provider == "google":
        return {"route": "tunnel"}
    return {"route": "direct"}


def test_probe_one_routes_through_prove_seam():
    """probe_one crosses select+prove (injected fake selector, no network)."""
    from factory.net.tunnel_selection import Proof

    transport_calls = []
    seam_calls = {}

    def _ok(api_key, model, text):
        transport_calls.append((model, text))
        return ("PICK run#0", None)

    def _selector_fn(provider, adapter):
        seam_calls["provider"] = provider
        seam_calls["adapter"] = adapter

        class _FakeSelector:
            def select(self, p):
                seam_calls["select"] = p
                from types import SimpleNamespace

                return SimpleNamespace(exit_id="direct", whitelisted=False,
                                       served_from="subscription")

            def prove(self, p, exits):
                seam_calls["prove"] = (p, list(exits))
                for exit_id in exits:
                    adapter.probe(exit_id)
                return Proof(clean=list(exits), blocked=[], unknown=[])

        return _FakeSelector()

    rec = probe_mod.probe_one(
        "groq", "PROMPT", model="op-model", key_value="k" * 16,
        transport_fn=_ok, clock=lambda: 1.0, route="direct",
        registry_fn=_direct_registry_fn,
        selector_fn=_selector_fn)
    assert seam_calls["select"] == "groq"
    assert seam_calls["prove"][0] == "groq"
    assert seam_calls["prove"][1] == ["direct"]
    assert len(transport_calls) == 1  # one transport behind prove, no retry
    assert rec["status"] == "ok"
    assert rec["route"] == "direct"
    assert rec["egress"] == "direct"
    assert rec["latency_s"] == 0.0


def test_old_probe_path_deleted_same_pr():
    """Route-delete rule: probe_one holds no direct transport block anymore.

    The old inline path (direct transport_fn call + proxy-env patch inside
    probe_one) is gone in this same ticket; the transport executes behind
    the prove seam (adapter), never inline in probe_one.
    """
    source = inspect.getsource(probe_mod.probe_one)
    assert "prove(" in source  # new path: verdict arrives via prove
    assert "select(" in source  # new path: egress arrives via select
    # Old path markers: inline single-shot transport + inline proxy patch.
    # The transport now executes inside the probe adapter (a different
    # function behind the prove seam), never inline in probe_one.
    assert "transport_fn(key_value, model, prompt_text)" not in source
    assert "_proxy_env(" not in source


def test_probe_reports_latency_and_error_kind_unchanged():
    """Migrated probe reports identical latency/error_kind/http_status."""
    import urllib.error

    reports = []

    def _fail(api_key, model, text):
        raise urllib.error.HTTPError("url", 429, "too many", {}, None)

    rec = probe_mod.probe_one(
        "google", "PROMPT", model="gemini-x", key_value="g" * 16,
        transport_fn=_fail, clock=lambda: 1.0, route="auto",
        lease_fn=lambda target: {"lease_id": "ab12cd34ef56",
                                 "mode": "tunnel",
                                 "proxy_url": "http://127.0.0.1:19099",
                                 "server_id": "srv-fake",
                                 "provider": "google", "target": target},
        report_fn=lambda *a: reports.append(a) or {},
        target_fn=lambda p: "google",
        registry_fn=_direct_registry_fn,
        clean_fn=lambda: [],
        remember_fn=lambda *a: None)
    assert rec["status"] == "http-error"
    assert rec["http_status"] == 429
    assert rec["error_kind"] == "http-429"
    assert rec["latency_s"] == 0.0
    assert rec["route"] == "leased"
    assert rec["lease"] == "ab12cd34"
    assert rec["egress"] == "srv-fake"
    assert reports and reports[0][1] == "http429"

    # Empty reply keeps its distinct status (not folded into ok/unknown).
    rec = probe_mod.probe_one(
        "groq", "PROMPT", model="m", key_value="k" * 16,
        transport_fn=lambda k, m, t: ("   ", None),
        clock=lambda: 1.0, route="direct",
        registry_fn=_direct_registry_fn)
    assert rec["status"] == "empty-reply"
    assert rec["error_kind"] == "empty-reply"
    assert rec["latency_s"] == 0.0


def test_registered_probes_early_stop_hermetic():
    """Registered adapters behind real prove: keep=1 stops after 1 probe."""
    from factory.net.tunnel_selection import (
        KeyedProviderProbe,
        KeylessGoogleProbe,
        SubscriptionSource,
        TunnelSelector,
    )

    calls = []

    def _check(exit_id):
        calls.append(exit_id)
        return "clean"

    class _Subs(SubscriptionSource):
        def refresh(self):
            return []

    class _Store:
        def read(self, provider):
            return []

        def write(self, provider, rows):
            pass

    for probe in (KeylessGoogleProbe(check_fn=_check),
                  KeyedProviderProbe(key_name="PROBE_KEY", check_fn=_check)):
        calls.clear()
        sel = TunnelSelector(subs=_Subs(),
                             probes={"google": probe},
                             store=_Store(), clock=lambda: 0.0,
                             batch=5, keep=1)
        proof = sel.prove("google", ["e1", "e2", "e3"])
        assert proof.clean == ["e1"]
        assert calls == ["e1"]  # early stop: no 2nd/3rd probe, no network


@pytest.mark.skipif(
    os.environ.get("HAMZABAN_LIVE_PROBE") != "1",
    reason="gated live: needs HAMZABAN_LIVE_PROBE=1 + network; CI skips",
)
def test_live_probe_single_provider_capped():
    """Live single-provider probe, batch-capped, free probe only (gated)."""
    provider = os.environ.get("HAMZABAN_LIVE_PROBE_PROVIDER", "google")
    results = probe_mod.probe_all(
        providers=[provider], operator_models={},
        batch=1, keep=1)
    assert len(results) == 1
    assert results[0]["provider"] == provider
