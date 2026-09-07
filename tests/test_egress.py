"""Hermetic tests for tools/egress (supervisor pool + client wiring).

No network, no real subscription, no tokens on disk: Pool is exercised
directly; HTTP layer is tested against a live loopback server with a
test-only token.
"""
import base64
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools",
                                "egress"))
import supervisor
from supervisor import HTTPServer, Handler, Pool, parse_subscription


def _sub_body():
    vmess = base64.b64encode(json.dumps(
        {"add": "example.com", "port": 443}).encode()).decode()
    return base64.b64encode(
        ("vmess://%s\nvless://u@other.org:443?x=1\njunkline\n" % vmess
         ).encode()).decode()


def test_parse_subscription_shapes():
    servers = parse_subscription(_sub_body())
    assert [s["scheme"] for s in servers] == ["vmess", "vless"]
    assert servers[0]["host"] == "example.com"
    assert servers[0]["port"] == 443
    assert servers[1]["host"] == "other.org"
    assert parse_subscription("") == []
    assert parse_subscription(":::not-a-link:::") == []


def test_pool_direct_lease_and_report():
    pool = Pool()
    pool.load([{"scheme": "vless", "host": "h", "port": 1, "id": "a1"}])
    lease = pool.lease("direct")
    assert lease["mode"] == "direct" and lease["proxy_url"] == ""
    assert pool.report(lease["lease_id"], "ok") == {"action": "keep"}
    assert pool.report("nope", "ok") == {"action": "unknown-lease"}


def test_pool_ranked_whitelist_roundtrip(tmp_path):
    pool = Pool()
    pool.load([
        {"scheme": "vless", "host": "slow", "port": 1, "id": "s1"},
        {"scheme": "vless", "host": "fast", "port": 1, "id": "s2"},
    ])
    pool.load_ranked([
        {"id": "s1", "alive": True}, {"id": "s2", "alive": True},
        {"id": "ghost", "alive": True},
    ])
    assert [s["id"] for s in pool.servers] == ["s1", "s2"]
    path = str(tmp_path / "pool.json")
    pool.save_pool(path)
    pool2 = Pool()
    assert pool2.load_pool(path) == 2
    assert [s["id"] for s in pool2.servers] == ["s1", "s2"]
    assert pool2.load_pool(str(tmp_path / "nope.json")) == 0


def test_sub_sources_merge_order_and_dedup():
    from supervisor import sub_sources
    env = {"EGRESS_SUB_URLS": "https://a/sub, https://b/sub\nhttps://a/sub",
           "EGRESS_SUB_URL": "https://b/sub"}
    assert sub_sources(env) == ["https://a/sub", "https://b/sub"]
    assert sub_sources({}) == []
    assert sub_sources({"EGRESS_SUB_URL": "x"}) == ["x"]


def test_probe_pool_ranks_and_marks_top(monkeypatch):
    import supervisor
    pool = Pool()
    pool.load([
        {"scheme": "vless", "host": "slow", "port": 1, "id": "s1"},
        {"scheme": "vless", "host": "fast", "port": 1, "id": "s2"},
        {"scheme": "vless", "host": "dead", "port": 1, "id": "s3"},
    ])
    lat = {"slow": 900, "fast": 120, "dead": None}
    monkeypatch.setattr(supervisor, "tcp_ping",
                        lambda h, p, timeout=5.0: lat[h])
    monkeypatch.setattr(supervisor, "POOL", pool)
    rows = supervisor.probe_pool(top_n=1)
    assert [r["host"] for r in rows] == ["fast", "slow", "dead"]
    assert rows[0]["zen_candidate"] is True
    assert rows[0]["latency_ms"] == 120
    assert rows[2]["alive"] is False
    assert rows[2]["zen_candidate"] is False


def test_pool_zen_parks_without_tunnel_backend():
    pool = Pool()
    out = pool.lease("zen")
    assert out["error"] == "park"


def test_pool_cooldown_on_429():
    pool = Pool()
    pool.load([{"scheme": "vless", "host": "h", "port": 1, "id": "a1"}])
    lease = pool.lease("zen")
    assert lease["mode"] == "tunnel-pending"
    assert pool.report(lease["lease_id"], "http429") == {"action": "switch"}
    # cooling down: pool now parks
    assert pool.lease("zen")["error"] == "park"


def test_http_auth_and_endpoints():
    supervisor.TOKEN = "test-token"
    supervisor.POOL.servers.clear()
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        def call(path, payload, token="test-token", method="POST"):
            data = None if method == "GET" else \
                json.dumps(payload or {}).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:%d%s" % (port, path),
                data=data,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + token},
                method=method)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, json.load(resp)
            except Exception as exc:  # noqa: BLE001 (assert on code)
                return getattr(exc, "code", "?"), {}

        code, _ = call("/v1/health", None, token="wrong", method="GET")
        assert code == 401
        code, body = call("/v1/health", None, method="GET")
        assert code == 200 and body["ok"] is True
        code, body = call("/v1/lease", {"target": "direct"})
        assert code == 200 and body["mode"] == "direct"
        code, body = call("/v1/report",
                           {"lease_id": body["lease_id"], "outcome": "ok"})
        assert body == {"action": "keep"}
    finally:
        server.shutdown()
        thread.join(timeout=10)
        supervisor.TOKEN = ""


def test_client_lease_report_roundtrip():
    """N1: client.lease/report/health against the loopback fixture."""
    import client as egress_client
    supervisor.TOKEN = "test-token"
    supervisor.POOL.servers.clear()
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    old_url, old_tok = egress_client.SUP_URL, egress_client.SUP_TOKEN
    egress_client.SUP_URL = "http://127.0.0.1:%d" % port
    egress_client.SUP_TOKEN = "test-token"
    try:
        lease = egress_client.lease("direct")
        assert lease["mode"] == "direct" and lease["lease_id"]
        assert egress_client.report(
            lease["lease_id"], "ok") == {"action": "keep"}
        assert egress_client.health()["ok"] is True
    finally:
        egress_client.SUP_URL, egress_client.SUP_TOKEN = old_url, old_tok
        server.shutdown()
        thread.join(timeout=10)
        supervisor.TOKEN = ""
