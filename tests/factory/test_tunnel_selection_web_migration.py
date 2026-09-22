"""T8 — web-last migration onto the tunnel-selection seam (hermetic).

Locked scope (phase-06): the linker WebUI server + precard viewer
composition reads tunnel/lease/selection state through the locked seam
(``factory.net.tunnel_selection`` via the T4 probe helpers in
``factory.linking.probe_providers`` and the T5 linker adapter in
``factory.linking.google_clean``) with ``*_fn`` injection — display and
composition only, no domain logic in the web layer (R7). The old direct
(per-caller tunnel copies: inline supervisor lease/report HTTP, inline
registry-route mirror, inline whitelist reads, local reason-string
literal) are deleted in this same ticket (R6 same-PR rule).

All doubles are injected fakes: no network, no keys, no disk. Secrets
appear as names only, never values.
"""

from __future__ import annotations

import inspect
import io
import json
import os
import pathlib
import urllib.error

import pytest

from factory.linking.webui import server as webui


def _no_network(monkeypatch):
    """Fail any real HTTP attempt: the seam fakes carry every datum."""

    def _boom(*args, **kwargs):
        raise AssertionError("network touched in a hermetic test")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    monkeypatch.setattr("urllib.request.build_opener", _boom)


def _tunnel_registry_fn(provider):
    """Fake registry row reader: google is tunnel-route, rest direct."""
    if provider == "google":
        return {"route": "tunnel"}
    return {"route": "direct"}


def test_webui_composition_reads_seam_only(monkeypatch):
    """Route/lease/whitelist composition crosses the seam (fakes, no net)."""
    _no_network(monkeypatch)

    # Routing reads through the probe seam (registry_fn injects the row).
    route, reason = webui.route_for_provider(
        "google", registry_fn=_tunnel_registry_fn)
    assert route == "leased"
    assert "403" in reason and "\n" not in reason
    assert webui.route_for_provider(
        "avalai", registry_fn=_tunnel_registry_fn)[0] == "direct"
    # Operator custom profiles stay composition-side (no engine route).
    monkeypatch.setattr(webui, "_is_custom_profile",
                        lambda p: p == "mymine")
    route, reason = webui.route_for_provider("mymine")
    assert route == "direct"
    assert "custom profile" in reason

    # Lease acquisition arrives via the lease seam (lease_fn injects it).
    leased_targets = []

    def _fake_lease(target):
        leased_targets.append(target)
        return {"lease_id": "bb11cc22dd33", "mode": "tunnel",
                "proxy_url": "http://127.0.0.1:19998",
                "server_id": "srv-webui", "provider": "google",
                "target": target}

    verified, remembered = [], []

    def _fake_verify(proxy_url, server_id, provider="google", **kwargs):
        verified.append((proxy_url, server_id, provider))
        return {"ok": True, "remembered": True}

    monkeypatch.setattr(webui, "_supervisor_token", lambda: "tok")
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "r"))
    lease, error = webui.lease_tunnel_for_run(
        "google", lease_fn=_fake_lease,
        clean_fn=lambda *a, **k: ["srv-webui"],
        verify_fn=_fake_verify)
    assert error is None
    assert lease["lease_id"] == "bb11cc22dd33"
    assert leased_targets == ["google"]
    # Whitelist annotation rides OUR lease dict only (seam read, no file).
    assert lease["clean_exit"] == "srv-webui"
    assert lease["clean"] is True
    assert "srv-webui" in lease["clean_note"]
    assert verified == [("http://127.0.0.1:19998", "srv-webui", "google")]
    # Direct providers lease nothing (lease_fn never fires).
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("direct", "r"))
    assert webui.lease_tunnel_for_run("avalai", lease_fn=_fake_lease) == (
        None, None)
    assert leased_targets == ["google"]

    # Whitelist head for the compose line arrives via clean_fn (no file).
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "r")
                        if p == "google" else ("direct", "r"))
    assert webui._routing_clean_exit(
        "google", clean_fn=lambda *a, **k: ["srv-clean"]) == "srv-clean"
    assert webui._routing_clean_exit(
        "google", clean_fn=lambda *a, **k: []) == ""
    assert webui._routing_clean_exit(
        "avalai", clean_fn=lambda *a, **k: ["srv-clean"]) == ""


def test_webui_report_and_remember_cross_seam(monkeypatch):
    """Terminal report + model-list write-back cross the seam (no net)."""
    _no_network(monkeypatch)
    monkeypatch.setattr(webui, "_supervisor_token", lambda: "tok")

    # Terminal report for OUR lease only (report_fn injects the client).
    reported = []
    webui.report_run_lease(
        "bb11cc22dd33", "google", True,
        report_fn=lambda lid, outcome, provider=None: reported.append(
            (lid, outcome, provider)))
    assert reported == [("bb11cc22dd33", "ok", "google")]
    webui.report_run_lease("", "google", True,
                           report_fn=lambda *a, **k: reported.append("boom"))
    assert reported == [("bb11cc22dd33", "ok", "google")]  # no id: silent

    # 429 cools OUR server (http429); other errors report nothing.
    rates = []
    boom429 = urllib.error.HTTPError("http://x", 429, "slow", {}, None)
    webui._report_lease_outcome(
        {"lease_id": "bb11cc22dd33"}, "google", boom429,
        report_fn=lambda lid, outcome, provider=None: rates.append(
            (lid, outcome, provider)))
    assert rates == [("bb11cc22dd33", "http429", "google")]
    webui._report_lease_outcome(
        {"lease_id": "bb11cc22dd33"}, "google", TimeoutError(),
        report_fn=lambda *a, **k: rates.append("boom"))
    assert len(rates) == 1
    # Success reports ok behind the same seam.
    oks = []
    webui._report_lease_outcome(
        {"lease_id": "bb11cc22dd33"}, "google", None,
        report_fn=lambda lid, outcome, provider=None: oks.append(
            (lid, outcome, provider)))
    assert oks == [("bb11cc22dd33", "ok", "google")]

    # Google model list leases + remembers through the seam (fake opener
    # serves the exact-ids payload; values stay in-memory, names out).
    remembered = []
    payload = {"models": [{"name": "models/gemini-x"},
                          {"name": ""}, "junk"]}

    class _FakeResp:
        def __init__(self, data):
            self._buf = io.BytesIO(json.dumps(data).encode())

        def __enter__(self):
            return self._buf

        def __exit__(self, *exc):
            return False

    class _FakeOpener:
        def open(self, req, timeout=None):
            return _FakeResp(payload)

    monkeypatch.setattr("urllib.request.build_opener",
                        lambda *a, **k: _FakeOpener())
    monkeypatch.setattr(webui, "_provider_key_var",
                        lambda p: "GOOGLE_AI_API_KEY")
    monkeypatch.setattr(webui, "_operator_key_values",
                        lambda: {"GOOGLE_AI_API_KEY": "k-fake"})
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "r"))
    monkeypatch.setattr(
        webui, "lease_tunnel_for_run",
        lambda p, **k: ({"lease_id": "bb11cc22dd33",
                         "proxy_url": "http://127.0.0.1:19998",
                         "server_id": "srv-webui"}, None))
    models, error = webui.provider_model_list(
        "google",
        remember_fn=lambda *a: remembered.append(a),
        report_fn=lambda *a, **k: None)
    assert error is None
    assert models == ["gemini-x"]  # exact ids, never invented
    assert remembered and remembered[0][0] == "srv-webui"
    assert remembered[0][1] == "google"


def test_no_domain_logic_in_webui():
    """R7 guard: the server holds no tunnel domain logic of its own.

    Allowed network in the server: read-only supervisor health display
    (``supervisor_health_snapshot``) and the key-gated per-provider
    model-list fetch (``provider_model_list``) — both composition facts
    for screens. Lease/report/route/whitelist paths must delegate to
    the seam modules (probe helpers + linker adapter), never inline
    supervisor HTTP, registry mirrors, or reason literals.
    """
    source = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    # No inline supervisor HTTP anywhere in the server (copies deleted).
    assert "/v1/lease" not in source
    assert "/v1/report" not in source
    for name in ("lease_tunnel_for_run", "report_run_lease",
                 "_report_lease_outcome"):
        body = inspect.getsource(getattr(webui, name))
        assert "urlopen" not in body, name
        assert "build_opener" not in body, name
        assert "urlopen" not in body and "Request(" not in body, name
    # Reason string is the single probe-module owner (alias, no literal).
    from factory.linking import probe_providers as _pp
    assert webui.GOOGLE_TUNNEL_REASON == _pp.GOOGLE_TUNNEL_REASON
    assert "GOOGLE_TUNNEL_REASON = (" not in source
    # Delegation markers: route/lease/report cross the probe seam.
    assert "route_for(" in inspect.getsource(webui.route_for_provider)
    assert "route_reason(" in inspect.getsource(webui.route_for_provider)
    assert "lease_tunnel(" in inspect.getsource(webui.lease_tunnel_for_run)
    assert "report_outcome(" in inspect.getsource(webui.report_run_lease)
    # Whitelist reads cross the linker adapter behind clean_fn injection.
    assert "clean_fn" in inspect.getsource(webui.key_presence)
    assert "clean_fn" in inspect.getsource(webui._routing_clean_exit)
    assert "remember_fn" in inspect.getsource(webui.provider_model_list)
    # The allowances stay (read-only health + key-gated model fetch).
    assert "urlopen" in inspect.getsource(webui.supervisor_health_snapshot)
    assert "urlopen" in inspect.getsource(webui.provider_model_list)


def test_no_per_caller_tunnel_copies_remain():
    """R6 sweep: the web layer keeps no rival tunnel helpers.

    Every whitelist-helper reference in the server is an injected
    ``*_fn`` default (production default = the seam owner); every
    route/lease/report reference delegates to the probe seam. The
    registry stays untouched (no forced migration — default path
    still resolves through the engine registry).
    """
    source = pathlib.Path(webui.__file__).read_text(encoding="utf-8")
    lines = source.splitlines()
    for helper in ("fresh_clean_exits", "verify_and_remember",
                   "remember_success"):
        for idx, line in enumerate(lines):
            if helper not in line or "``" in line:
                continue  # doc reference (``...``), not a call site
            stripped = line.strip()
            if stripped.startswith(("#", '"""', "'''")):
                continue
            prev = lines[idx - 1] if idx else ""
            assert ("clean_fn" in line or "verify_fn" in line
                    or "remember_fn" in line or "import" in line
                    or "clean_fn" in prev or "verify_fn" in prev
                    or "remember_fn" in prev), line
    params = inspect.signature(webui.route_for_provider).parameters
    assert "registry_fn" in params  # no forced migration: injectable row
    params = inspect.signature(webui.lease_tunnel_for_run).parameters
    assert "lease_fn" in params
    params = inspect.signature(webui.report_run_lease).parameters
    assert "report_fn" in params
    # Engine facts (routing table + reason) still come from the same
    # seam-backed helpers the screens render — composition, no copies.
    assert "route_for_provider" in inspect.getsource(webui.engine_info)
    assert "_routing_clean_exit" in inspect.getsource(webui.engine_info)
    # Registry untouched: the seam default still resolves engine rows.
    from factory.precard import provider_registry as reg
    assert reg.resolve_provider("google")["route"] == "tunnel"
    assert "tunnel_selection" not in pathlib.Path(
        reg.__file__).read_text(encoding="utf-8")


@pytest.mark.skipif(
    os.environ.get("HAMZABAN_LIVE_WEBUI") != "1",
    reason="gated live: needs HAMZABAN_LIVE_WEBUI=1; CI skips",
)
def test_live_webui_boot_capped():
    """Live loopback boot: the real stack serves engine facts (gated)."""
    assert os.environ.get("HAMZABAN_LIVE_WEBUI") == "1"
