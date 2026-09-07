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


def _vmess_link():
    import base64 as _b64
    import json as _j
    payload = _b64.b64encode(_j.dumps({
        "add": "example.com", "port": 443, "id": "uuid-1",
        "aid": 0, "scy": "auto", "net": "ws", "tls": "tls",
        "sni": "example.com", "path": "/pth",
        "host": "example.com"}).encode()).decode()
    return "vmess://" + payload


def test_xrayconf_vmess_ws_tls():
    from xrayconf import parse_link, xray_config
    node = parse_link(_vmess_link())
    assert node["address"] == "example.com" and node["port"] == 443
    assert node["tls"] is True and node["network"] == "ws"
    cfg = xray_config(node, 18081)
    assert cfg["inbounds"][0]["port"] == 18081
    assert cfg["inbounds"][0]["listen"] == "127.0.0.1"
    assert cfg["outbounds"][0]["protocol"] == "vmess"
    stream = cfg["outbounds"][0]["streamSettings"]
    assert stream["security"] == "tls"
    assert stream["wsSettings"]["path"] == "/pth"


def test_xrayconf_vless_trojan_ss_shapes():
    from xrayconf import parse_link, xray_config
    import base64 as _b64
    vl = parse_link("vless://uuid-2@h.org:443"
                    "?security=tls&sni=h.org&type=tcp#n")
    assert (vl["address"], vl["port"], vl["tls"]) == ("h.org", 443, True)
    assert xray_config(vl, 18082)["outbounds"][0]["protocol"] == "vless"
    tr = parse_link("trojan://pw@h.net:443?sni=h.net#n")
    assert tr["tls"] is True
    assert xray_config(tr, 18083)["outbounds"][0]["protocol"] == "trojan"
    tr_plain = parse_link("trojan://pw@h.net:443#n")
    assert tr_plain["tls"] is False  # no sni, no flag: explicit plain
    ss_body = _b64.b64encode(b"aes-256-gcm:secret").decode()
    ss = parse_link("ss://%s@h.io:8388#n" % ss_body)
    assert ss["method"] == "aes-256-gcm"
    assert xray_config(ss, 18084)["outbounds"][0][
        "protocol"] == "shadowsocks"
    try:
        parse_link("http://example.com/x")
        assert False, "unsupported scheme must raise"
    except ValueError:
        pass


def test_xray_binary_validates_generated_config():
    """Real xray -test on a generated config (skipped without binary)."""
    import pathlib
    import subprocess
    from xrayconf import parse_link, xray_config
    exe = pathlib.Path(__file__).resolve().parent.parent / "tools" \
        / "egress" / "bin" / "xray.exe"
    if not exe.exists():
        import pytest as _pytest
        _pytest.skip("xray.exe not present")
    cfg = xray_config(parse_link(_vmess_link()), 18085)
    tmp = pathlib.Path(str(pathlib.Path(
        __file__).resolve().parent / "xray-test-tmp.json"))
    try:
        tmp.write_text(__import__("json").dumps(cfg), encoding="utf-8")
        proc = subprocess.run([str(exe), "-test", "-c", str(tmp)],
                              capture_output=True, timeout=60)
        assert proc.returncode == 0, proc.stderr.decode()[-500:]
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


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
    pool.load([{"scheme": "vless", "host": "h", "port": 1, "id": "a1",
                "link": "vless://u@h:1"}])
    lease = pool.lease("zen")
    assert lease["mode"] == "tunnel"
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


class _FakeTunnel:
    started, stopped = [], []

    def __init__(self, server, link):
        self.server = server
        self.link = link
        self.proc = None
        self._port = 19999

    @property
    def proxy_url(self):
        return "http://127.0.0.1:%d" % self._port

    def start(self, timeout=25):
        _FakeTunnel.started.append(self.server["id"])
        return self.proxy_url

    def egress_ip(self, timeout=15):
        return "9.9.9.9"

    def stop(self):
        _FakeTunnel.stopped.append(self.server["id"])


def test_tunnel_owner_acquire_and_rotate(monkeypatch):
    from supervisor import TunnelOwner
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    _FakeTunnel.started.clear()
    _FakeTunnel.stopped.clear()
    pool = Pool()
    pool.load([
        {"scheme": "vless", "host": "a", "port": 1, "id": "s1",
         "link": "vless://u@a:1"},
        {"scheme": "vless", "host": "b", "port": 1, "id": "s2",
         "link": "vless://u@b:1"},
    ])
    owner = TunnelOwner(pool)
    proxy, ip, sid = owner.acquire()
    assert proxy.startswith("http://127.0.0.1:") and ip == "9.9.9.9"
    assert sid == "s1"
    owner.rotate("http429")
    assert _FakeTunnel.stopped == ["s1"]
    proxy2, _, sid2 = owner.acquire()
    assert sid2 == "s2"  # s1 cooling down
    assert proxy2.startswith("http://127.0.0.1:")
    owner.stop()
    assert _FakeTunnel.stopped == ["s1", "s2"]


def test_http_tunnel_lease_path(monkeypatch):
    import supervisor as sup
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    _FakeTunnel.started.clear()
    _FakeTunnel.stopped.clear()
    sup.TOKEN = "test-token"
    sup.POOL.servers.clear()
    sup.POOL.load([{"scheme": "vless", "host": "a", "port": 1,
                    "id": "s1", "link": "vless://u@a:1"}])
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request as _url

        def post(path, payload):
            req = _url.Request(
                "http://127.0.0.1:%d%s" % (port, path),
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer test-token"})
            with _url.urlopen(req, timeout=10) as resp:
                return json.load(resp)

        lease = post("/v1/lease", {"target": "zen"})
        assert lease["mode"] == "tunnel"
        assert lease["proxy_url"].startswith("http://127.0.0.1:")
        assert lease["egress_ip"] == "9.9.9.9"
        res = post("/v1/report",
                   {"lease_id": lease["lease_id"],
                    "outcome": "http429"})
        assert res == {"action": "switch"}
    finally:
        server.shutdown()
        thread.join(timeout=10)
        sup.TUNNELS.stop()
        sup.TOKEN = ""


def test_run_with_lease_sets_child_env(monkeypatch, tmp_path):
    import run_with_lease as rwl
    calls = {}

    def fake_lease(target):
        calls["target"] = target
        return {"lease_id": "L12345678", "mode": "tunnel",
                "proxy_url": "http://127.0.0.1:18888",
                "egress_ip": "9.9.9.9"}

    def fake_report(lid, outcome):
        calls["report"] = (lid, outcome)
        return {"action": "keep"}

    monkeypatch.setattr(rwl.client, "lease", fake_lease)
    monkeypatch.setattr(rwl.client, "report", fake_report)

    seen = {}

    class FakeProc:
        def wait(self):
            return 0

    def fake_popen(cmd, env=None):
        seen["proxy"] = env.get("HTTPS_PROXY")
        seen["no_proxy"] = env.get("NO_PROXY", "")
        assert os.environ.get("HTTPS_PROXY") is None  # parent untouched
        return FakeProc()

    monkeypatch.setattr(rwl.subprocess, "Popen", fake_popen)
    assert rwl.main(["zen", "--", "echo", "hi"]) == 0
    assert seen["proxy"] == "http://127.0.0.1:18888"
    assert "api.avalai.ir" in seen["no_proxy"]
    assert calls == {"target": "zen", "report": ("L12345678", "ok")}
