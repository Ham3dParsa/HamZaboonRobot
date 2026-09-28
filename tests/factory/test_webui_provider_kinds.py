"""Two-kind provider rows (local/cloud) + probe endpoint tests.

Local = loopback-only + keyless + direct (SSRF-safe by construction).
Cloud = https + non-loopback (key enforced at the form; manifest stays
flexible for engine-level rows). Probe never stores anything.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from factory.precard import provider_manifest as _manifest
from factory.webui import server as webui


def _row(**kw):
    base = {"protocol": "openai_compat", "route": "direct",
            "key_vars": [], "request_extras": {}}
    base.update(kw)
    return base


#: Fake DNS: every name resolves globally (tests never touch the network).
_GLOBAL = lambda host: ["93.184.216.34"]  # noqa: E731
_PRIVATE = lambda host: ["10.0.0.9"]  # noqa: E731


def _dead_resolver(host):
    raise OSError("dns down")


def test_local_loopback_ok():
    for base in ("http://localhost:1234/v1",
                 "http://127.0.0.1:11434/v1",
                 "http://localhost:1234/v1/chat/completions"):
        ok, error = _manifest.validate_row(
            "mylocal", _row(base_url=base, kind="local"))
        assert ok, (base, error)


def test_local_rejects_non_loopback_not_keys():
    ok, _ = _manifest.validate_row(
        "x", _row(base_url="https://api.example.com/v1", kind="local"))
    assert not ok
    ok, _ = _manifest.validate_row(
        "x", _row(base_url="http://10.0.0.5/v1", kind="local"))
    assert not ok
    # Keys stay allowed on local rows (key-gated listing needs a
    # reference; loopback-only addressing already kills SSRF).
    ok, error = _manifest.validate_row(
        "x", _row(base_url="http://localhost:1234/v1", kind="local",
                  key_vars=["X_API_KEY_1"]))
    assert ok, error
    ok, _ = _manifest.validate_row(
        "x", _row(base_url="http://localhost:1234/v1", kind="local",
                  route="tunnel"))
    assert not ok


def test_cloud_rules():
    ok, _ = _manifest.validate_row(
        "x", _row(base_url="https://api.example.com/v1", kind="cloud"))
    assert ok
    for bad in ("http://api.example.com/v1",
                "http://127.0.0.1:11434/v1",
                "http://10.1.2.3/v1"):
        ok, _ = _manifest.validate_row(
            "x", _row(base_url=bad, kind="cloud"))
        assert not ok, bad


def test_host_resolution_gate():
    ok, _ = _manifest.host_addrs_allowed("svc.example",
                                         _resolver=_GLOBAL)
    assert ok
    ok, reason = _manifest.host_addrs_allowed("svc.example",
                                              _resolver=_PRIVATE)
    assert not ok and "non-public" in reason
    ok, reason = _manifest.host_addrs_allowed("svc.example",
                                              _resolver=_dead_resolver)
    assert not ok and "could not resolve" in reason
    ok, _ = _manifest.host_addrs_allowed("localhost")
    assert ok
    # Split contract: registration stores the inert row (literal-only,
    # offline-deterministic); the FETCH gate refuses private DNS.
    ok, _ = _manifest.validate_row(
        "x", _row(base_url="https://svc.example/v1", kind="cloud"))
    assert ok
    assert _manifest.base_host_allowed("https://svc.example/v1",
                                       _resolver=_PRIVATE) is False
    assert _manifest.base_host_allowed("https://svc.example/v1",
                                       _resolver=_GLOBAL) is True


def test_kind_inference_and_seeds_still_validate():
    assert _manifest.infer_kind(
        {"base_url": "http://localhost:1234/v1"}) == "local"
    assert _manifest.infer_kind(
        {"base_url": "https://api.example.com/v1"}) == "cloud"
    for name, row in _manifest.SEED_PROVIDERS.items():
        ok, error = _manifest.validate_row(name, dict(row))
        assert ok, (name, error)


class _Stub(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.path == "/v1/models"
        body = json.dumps({"data": [{"id": "stub-m"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def stub_base():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/v1" % server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_probe_local_stub_ok(stub_base):
    client = webui.app.test_client()
    resp = client.post("/api/provider_probe",
                       json={"base_url": stub_base, "kind": "local"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["count"] == 1
    assert body["models"] == ["stub-m"]


def test_probe_refuses_and_never_stores():
    client = webui.app.test_client()
    assert client.post("/api/provider_probe",
                       json={"base_url": "", "kind": "local"}).get_json()["ok"] is False
    assert client.post(
        "/api/provider_probe",
        json={"base_url": "http://10.0.0.9/v1",
              "kind": "local"}).get_json()["ok"] is False
    assert client.post(
        "/api/provider_probe",
        json={"base_url": "http://127.0.0.1:9/v1",
              "kind": "local"}).get_json()["ok"] is False
    from factory.precard import provider_registry
    assert "probe" not in provider_registry.provider_names()
