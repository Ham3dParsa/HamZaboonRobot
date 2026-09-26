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
import pytest


@pytest.fixture(autouse=True)
def _egress_probe_isolated(monkeypatch):
    """R7: Pool.lease tunnel path pings via tcp_ping — pin the probe at
    dead so this hermetic suite never touches real DNS. (Clean-cache
    file pin lives in the shared tests/conftest.py fixture.)
    TunnelOwner.acquire() probes via _server_tcp_ping (not tcp_ping),
    so per-test liveness overrides that seam; the default here is live
    so spawn-focused tests never pay the probe path."""
    monkeypatch.setattr(supervisor, "tcp_ping",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(supervisor, "_server_tcp_ping",
                        lambda *args, **kwargs: 4)


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


def test_xray_binary_validates_generated_config(tmp_path):
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
    tmp = pathlib.Path(str(tmp_path / "xray-test.json"))
    tmp.write_text(__import__("json").dumps(cfg), encoding="utf-8")
    proc = subprocess.run([str(exe), "-test", "-c", str(tmp)],
                          capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode()[-500:]


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


def test_rank_restored_after_refresh_sequence(tmp_path):
    """T1: rank survives save -> fresh pool -> load (the real boot order:
    refresh_subscription then load_pool)."""
    import supervisor as sup
    pool = Pool()
    pool.load([
        {"scheme": "vless", "host": "b", "port": 1, "id": "s1"},
        {"scheme": "vless", "host": "a", "port": 1, "id": "s2"},
    ])
    pool.load_ranked([{"id": "s2", "alive": True},
                      {"id": "s1", "alive": True}])
    path = str(tmp_path / "pool.json")
    pool.save_pool(path)
    pool2 = Pool()
    # boot order: fresh subscription load (unordered) then pool restore
    pool2.load([
        {"scheme": "vless", "host": "a", "port": 1, "id": "s2"},
        {"scheme": "vless", "host": "b", "port": 1, "id": "s1"},
    ])
    assert pool2.load_pool(path) == 2
    assert [s["id"] for s in pool2.servers] == ["s2", "s1"]
    assert sup.Pool is Pool  # sanity: we tested the real class


def test_sub_sources_merge_order_and_dedup():
    from supervisor import sub_sources
    env = {"EGRESS_SUB_URLS": "https://a/sub\nhttps://b/sub\nhttps://a/sub",
           "EGRESS_SUB_URL": "https://b/sub"}
    assert sub_sources(env) == ["https://a/sub", "https://b/sub"]
    assert sub_sources({}) == []
    assert sub_sources({"EGRESS_SUB_URL": "x"}) == ["x"]
    # commas AND newlines both split (literal comma in a link is
    # unsupported by contract: it is a split point).
    assert sub_sources(
        {"EGRESS_SUB_URLS": "https://a/sub,https://b/sub"}) == \
        ["https://a/sub", "https://b/sub"]
    assert sub_sources(
        {"EGRESS_SUB_URLS": "https://a/sub,\n\n https://b/sub\n,"}) == \
        ["https://a/sub", "https://b/sub"]
    assert sub_sources({"EGRESS_SUB_URLS": "https://only/sub"}) == \
        ["https://only/sub"]


def test_load_env_continuation_line(tmp_path, monkeypatch):
    """A bare URL line after EGRESS_SUB_URLS= joins that value."""
    import supervisor as sup
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EGRESS_SUB_URLS=https://a/sub\nhttps://b/sub\n"
        "EGRESS_SUP_TOKEN=t\n", encoding="utf-8")
    monkeypatch.setattr(sup, "ENV_PATH", env_file)
    data = sup.load_env()
    assert sup.sub_sources(data) == ["https://a/sub", "https://b/sub"]


def test_load_env_continuation_with_query_equals(tmp_path, monkeypatch):
    """A continuation URL carrying ?token=... must not become a key."""
    import supervisor as sup
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EGRESS_SUB_URLS=https://a/sub\nhttps://b/sub?token=abc&x=1\n"
        "EGRESS_SUP_TOKEN=t\n", encoding="utf-8")
    monkeypatch.setattr(sup, "ENV_PATH", env_file)
    data = sup.load_env()
    assert data["EGRESS_SUP_TOKEN"] == "t"
    assert sup.sub_sources(data) == [
        "https://a/sub", "https://b/sub?token=abc&x=1"]


def test_source_label_strips_userinfo():
    """Review finding: credential-bearing sub URLs must not leak into logs."""
    import supervisor as sup
    label = sup._source_label("https://user:pass@h.example/sub")
    assert label == "h.example"
    assert "user" not in label and "pass" not in label
    assert sup._source_label("https://h.example:8443/sub") == "h.example"
    assert sup._source_label("inline-body") == "inline"


def test_load_env_stray_lines_after_token_ignored(tmp_path, monkeypatch):
    """Review finding: bare/URL lines after the token must not corrupt it."""
    import supervisor as sup
    env_file = tmp_path / ".env"
    env_file.write_text(
        "EGRESS_SUP_TOKEN=t\nstray-bare-line\n"
        "https://evil.example/x?token=abc\n"
        "EGRESS_SUB_URLS=https://a/sub\n", encoding="utf-8")
    monkeypatch.setattr(sup, "ENV_PATH", env_file)
    data = sup.load_env()
    assert data["EGRESS_SUP_TOKEN"] == "t"
    assert sup.sub_sources(data) == ["https://a/sub"]


def test_refresh_subscription_partial_load(monkeypatch):
    """One poisoned source must not abort the rest."""
    import supervisor as sup
    sup.POOL.servers.clear()
    calls = []

    def fake_fetch(url, attempts=2):
        calls.append(url)
        if "bad" in url:
            raise OSError("down")
        return _sub_body()

    monkeypatch.setattr(sup, "fetch_sub", fake_fetch)
    sup.refresh_subscription({"EGRESS_SUB_URLS": "https://bad/sub\n"
                                                 + _sub_body()})
    assert calls == ["https://bad/sub"]
    assert len(sup.POOL.servers) == 2
    sup.POOL.servers.clear()


def test_refresh_subscription_failure_isolation(monkeypatch, capsys):
    """One bad URL + one good URL: both attempted, bad never kills good,
    status lines carry host only (never the full URL)."""
    import supervisor as sup
    sup.POOL.servers.clear()
    calls = []
    good_body = ("vless://u@good.example:443?security=tls&sni=good.example"
                 "#g\n")

    def fake_fetch(url, attempts=2):
        calls.append(url)
        if "bad" in url:
            raise OSError("down")
        return good_body

    monkeypatch.setattr(sup, "fetch_sub", fake_fetch)
    sup.refresh_subscription(
        {"EGRESS_SUB_URLS": "https://bad.example/sub,"
                            "https://good.example/sub"})
    assert calls == ["https://bad.example/sub",
                     "https://good.example/sub"]
    assert [s["host"] for s in sup.POOL.servers] == ["good.example"]
    out = capsys.readouterr().out
    assert "bad.example" in out and "good.example" in out
    assert "https://bad.example/sub" not in out
    assert "https://good.example/sub" not in out
    sup.POOL.servers.clear()


def test_refresh_subscription_raw_xirix_shape(monkeypatch):
    """Xirix-shape body: plain non-base64 link lines (no fetch)."""
    import supervisor as sup
    sup.POOL.servers.clear()
    raw = "vless://u@plain.example:443?security=tls&sni=plain.example#x"
    monkeypatch.setattr(sup, "fetch_sub",
                        lambda url, attempts=2: (_ for _ in ()).throw(
                            AssertionError("no fetch for inline body")))
    sup.refresh_subscription({"EGRESS_SUB_URLS": raw})
    assert [s["host"] for s in sup.POOL.servers] == ["plain.example"]
    sup.POOL.servers.clear()


def test_parse_subscription_raw_single_line():
    """Single-line plain-text body must not die to a spurious decode."""
    import supervisor as sup
    rows = sup.parse_subscription(
        "vless://u@plain.example:443?security=tls&sni=plain.example#x")
    assert [(r["host"], r["port"]) for r in rows] == [("plain.example",
                                                      443)]


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

    class _Proc:
        def poll(self):
            return None

    def __init__(self, server, link):
        self.server = server
        self.link = link
        self.proc = _FakeTunnel._Proc()
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
    # T3: second acquire reuses the live tunnel (no new start).
    proxy_b, _, sid_b = owner.acquire()
    assert (proxy_b, sid_b) == (proxy, "s1")
    assert _FakeTunnel.started == ["s1"]
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


def test_run_with_lease_unknown_on_app_failure(monkeypatch):
    """Nonzero child exit reports unknown (keeps lease, cools nothing)."""
    import run_with_lease as rwl

    def fake_lease(target):
        return {"lease_id": "L1", "mode": "tunnel",
                "proxy_url": "http://127.0.0.1:1", "egress_ip": "9.9.9.9"}

    seen = {}

    def fake_report(lid, outcome):
        seen["report"] = (lid, outcome)
        return {"action": "keep"}

    monkeypatch.setattr(rwl.client, "lease", fake_lease)
    monkeypatch.setattr(rwl.client, "report", fake_report)

    class FakeProc:
        def wait(self):
            return 1

    monkeypatch.setattr(rwl.subprocess, "Popen",
                        lambda cmd, env=None: FakeProc())
    assert rwl.main(["zen", "--", "false"]) == 1
    assert seen["report"] == ("L1", "unknown")


def test_bad_link_lease_parks_over_http(monkeypatch):
    """T2: unparseable link through POST /v1/lease -> park (no drop)."""
    import supervisor as sup
    sup.TOKEN = "test-token"
    sup.POOL.servers.clear()
    sup.POOL.cooldown_until.clear()
    sup.POOL.load([{"scheme": "vless", "host": "bad", "port": 1,
                    "id": "s9", "link": "vless://%zz"}])
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request as _url
        req = _url.Request(
            "http://127.0.0.1:%d/v1/lease" % port,
            data=json.dumps({"target": "zen"}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer test-token"})
        with _url.urlopen(req, timeout=10) as resp:
            body = json.load(resp)
        assert body.get("error") == "park"
    finally:
        server.shutdown()
        thread.join(timeout=10)
        sup.TOKEN = ""


class _FakeHTTPError(Exception):
    def __init__(self, code, body):
        super().__init__("HTTP %s" % code)
        self.code = code
        self._body = body

    def read(self, size=-1):
        return self._body


class _FakeOpener:
    def __init__(self, result):
        self.result = result
        self.urls = []

    def open(self, req, timeout=None):
        import urllib.request as _u
        self.urls.append(req.full_url if isinstance(req, _u.Request)
                         else req)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_google_probe_live():
    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    code, ms, note = supervisor.google_probe(
        "http://127.0.0.1:1", "k",
        opener=_FakeOpener(Resp()))
    assert code == 200 and note == "live"


def test_google_probe_location_blocked():
    body = (b'{"error": {"code": 400, "message": "User location is not '
            b'supported for the API use.", "status": "FAILED_PRECONDITION"}}')
    code, ms, note = supervisor.google_probe(
        "http://127.0.0.1:1", "k",
        opener=_FakeOpener(_FakeHTTPError(400, body)))
    assert code == 400 and note == "location-blocked"


def test_google_probe_bad_key():
    body = b'{"error": {"code": 400, "message": "API key not valid."}}'
    code, ms, note = supervisor.google_probe(
        "http://127.0.0.1:1", "k",
        opener=_FakeOpener(_FakeHTTPError(400, body)))
    assert code == 400 and note == "bad-key"


def test_google_probe_forbidden():
    code, ms, note = supervisor.google_probe(
        "http://127.0.0.1:1", "k",
        opener=_FakeOpener(_FakeHTTPError(403, b"denied")))
    assert code == 403 and note == "forbidden"


def test_google_probe_quota():
    code, ms, note = supervisor.google_probe(
        "http://127.0.0.1:1", "k",
        opener=_FakeOpener(_FakeHTTPError(429, b"slow down")))
    assert code == 429 and note == "quota"


def test_google_probe_net_unknown():
    import urllib.error as _err

    code, ms, note = supervisor.google_probe(
        "http://127.0.0.1:1", "k",
        opener=_FakeOpener(_err.URLError("refused")))
    assert code == "?" and note == "net/unknown"


def test_google_probe_str_code_normalized():
    class _StrCode(Exception):
        code = "oops"

        def read(self, size=-1):
            return b""

    code, ms, note = supervisor.google_probe(
        "http://127.0.0.1:1", "k",
        opener=_FakeOpener(_StrCode()))
    assert code == "?" and note == "net/unknown"


def test_google_probe_key_stripped():
    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    opener = _FakeOpener(Resp())
    code, ms, note = supervisor.google_probe(
        "http://127.0.0.1:1", "  k  ", opener=opener)
    assert code == 200 and note == "live"
    assert opener.urls[0].endswith("key=k")


def test_geo_country_success():
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"country": "Germany"}'

    assert supervisor.geo_country(
        "http://127.0.0.1:1", "1.2.3.4",
        opener=_FakeOpener(Resp())) == "Germany"


def test_geo_country_failure_and_blank_ip():
    import urllib.error as _err

    assert supervisor.geo_country(
        "http://127.0.0.1:1", "1.2.3.4",
        opener=_FakeOpener(_err.URLError("down"))) == "?"
    assert supervisor.geo_country(
        "http://127.0.0.1:1", "",
        opener=_FakeOpener(_err.URLError("unused"))) == "?"


def test_geo_country_quotes_ip():
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"country": "?"}'

    opener = _FakeOpener(Resp())
    supervisor.geo_country(
        "http://127.0.0.1:1", "1.2.3.4?x=1", opener=opener)
    assert "%3F" in opener.urls[0] and "?x=1&" not in opener.urls[0]


# --- C4b: TARGETS table + per-(server,provider) cooldowns ---

def _link_pool():
    pool = Pool()
    pool.load([{"scheme": "vless", "host": "h", "port": 1, "id": "s1",
                "link": "vless://u@h:1"}])
    return pool


def test_targets_table_shape():
    from supervisor import TARGETS, google_probe, zen_probe
    assert set(TARGETS) == {"direct", "zen", "google", "openrouter",
                            "groq", "avalai"}
    assert TARGETS["direct"] == {"provider": None, "tunnel": False,
                                 "probe": None}
    assert TARGETS["zen"]["tunnel"] is True  # historic name unchanged
    assert TARGETS["zen"]["provider"] == "zen"
    # Name-compared, not `is`: the suite imports the egress supervisor
    # through two supported paths (plain `supervisor` here vs
    # `tools.egress.supervisor` elsewhere), so two module instances can
    # share this one TARGETS dict and last-writer-wins the probe slot.
    # The pin is that each slot references its own probe, not None or
    # another target's probe.
    assert TARGETS["zen"]["probe"].__name__ == zen_probe.__name__ == \
        "zen_probe"
    assert TARGETS["google"]["probe"].__name__ == \
        google_probe.__name__ == "google_probe"
    assert TARGETS["openrouter"] == {"provider": "openrouter",
                                     "tunnel": True, "probe": None}
    assert TARGETS["groq"] == {"provider": "groq",
                               "tunnel": False, "probe": None}
    assert TARGETS["avalai"] == {"provider": "avalai", "tunnel": False,
                                 "probe": None}


def test_lease_all_targets_no_network():
    pool = _link_pool()
    for target, mode, provider in (
            ("direct", "direct", None), ("avalai", "direct", "avalai"),
            ("zen", "tunnel", "zen"), ("google", "tunnel", "google"),
            ("openrouter", "tunnel", "openrouter")):
        lease = pool.lease(target)
        assert lease["mode"] == mode, target
        assert lease["provider"] == provider, target
        assert lease["target"] == target, target
        assert pool.report(lease["lease_id"], "ok") == {"action": "keep"}


def test_unknown_target_parks():
    pool = _link_pool()
    out = pool.lease("bogus")
    assert out["error"] == "park"
    assert "direct" in out["message"] and "bogus" in out["message"]


def test_target_case_and_space_normalized():
    pool = _link_pool()
    assert pool.lease("  ZEN ")["mode"] == "tunnel"
    assert pool.lease("Direct")["mode"] == "direct"


def test_per_provider_cooldown_isolation():
    """A zen 429 parks zen but leaves google/openrouter on the server."""
    pool = _link_pool()
    lease = pool.lease("zen")
    assert pool.report(lease["lease_id"], "http429") == {"action": "switch"}
    assert pool.lease("zen")["error"] == "park"
    assert pool.lease("google")["mode"] == "tunnel"
    assert pool.lease("openrouter")["mode"] == "tunnel"


def test_report_provider_override():
    """Explicit provider cools that pair, not the lease's provider."""
    pool = _link_pool()
    lease = pool.lease("zen")
    assert pool.report(lease["lease_id"], "http429",
                       "google") == {"action": "switch"}
    assert pool.lease("zen")["mode"] == "tunnel"  # zen pair untouched
    assert pool.lease("google")["error"] == "park"


def test_cool_is_cool_helpers():
    pool = Pool()
    assert pool.is_cool("ghost") is False
    assert pool.is_cool("") is False
    pool.cool("s1", "zen", seconds=60)
    assert pool.is_cool("s1", "zen") is True
    assert pool.is_cool("s1", "google") is False  # pair isolation
    assert pool.is_cool("s1", "zen", now=10 ** 12) is False  # expired
    assert pool.provider_of("nope") is None
    lease = pool.lease("direct")
    assert pool.provider_of(lease["lease_id"]) is None


def test_cool_default_resolves_per_provider_table():
    """Omitted seconds resolve via cooldown_for (kilo 18, google 4)."""
    import time as _time
    from factory.core.llm_json import cooldown_for
    pool = Pool()
    before = _time.time()
    pool.cool("s-k", "kilo")
    pool.cool("s-g", "google")
    assert cooldown_for("kilo") == 18.0
    assert cooldown_for("google") == 4.0
    assert pool.is_cool("s-k", "kilo", now=before + 17) is True
    assert pool.is_cool("s-k", "kilo", now=before + 19) is False
    assert pool.is_cool("s-g", "google", now=before + 3) is True
    assert pool.is_cool("s-g", "google", now=before + 5) is False


def test_tunnel_owner_acquire_honors_provider(monkeypatch):
    """acquire(provider) skips only that provider's cooled servers."""
    from supervisor import TunnelOwner
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    pool = _link_pool()
    owner = TunnelOwner(pool)
    pool.cool("s1", "zen")
    try:
        with __import__("pytest").raises(RuntimeError):
            owner.acquire(provider="zen")
    finally:
        owner.stop()
    proxy, _, sid = owner.acquire(provider="google")
    assert (proxy, sid) == ("http://127.0.0.1:19999", "s1")
    owner.stop()


def test_http_report_provider_override(monkeypatch):
    """Over loopback: google-override cools google only; zen still leases."""
    import supervisor as sup
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    sup.TOKEN = "test-token"
    sup.POOL.servers.clear()
    sup.POOL.cooldown_until.clear()
    sup.POOL.leases.clear()
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
        assert lease["provider"] == "zen"
        res = post("/v1/report", {"lease_id": lease["lease_id"],
                                  "outcome": "http429",
                                  "provider": "google"})
        assert res == {"action": "switch"}
        again = post("/v1/lease", {"target": "zen"})
        assert again["mode"] == "tunnel"  # zen pair untouched
    finally:
        server.shutdown()
        thread.join(timeout=10)
        sup.TUNNELS.stop()
        sup.TOKEN = ""


def test_client_report_provider_wire(monkeypatch):
    """client.report forwards provider; omits it when None."""
    import client as egress_client
    seen = {}

    def fake_call(path, payload):
        seen[path] = payload
        return {"action": "keep"}

    monkeypatch.setattr(egress_client, "_call", fake_call)
    egress_client.report("L1", "ok")
    assert seen["/v1/report"] == {"lease_id": "L1", "outcome": "ok"}
    egress_client.report("L1", "http429", provider="zen")
    assert seen["/v1/report"] == {"lease_id": "L1", "outcome": "http429",
                                  "provider": "zen"}


def test_run_with_lease_accepts_new_targets(monkeypatch):
    """run_with_lease gates on TARGETS keys, not a hardcoded pair."""
    import run_with_lease as rwl
    assert set(rwl.TARGETS) >= {"direct", "zen", "google", "openrouter",
                                "avalai"}
    assert rwl.main([]) == 2
    assert rwl.main(["bogus", "--", "echo"]) == 2
    calls = {}

    def fake_lease(target):
        calls["target"] = target
        return {"lease_id": "L1", "mode": "direct", "proxy_url": "",
                "egress_ip": "direct"}

    def fake_report(lid, outcome, provider=None):
        calls["report"] = (lid, outcome, provider)
        return {"action": "keep"}

    monkeypatch.setattr(rwl.client, "lease", fake_lease)
    monkeypatch.setattr(rwl.client, "report", fake_report)

    class FakeProc:
        def wait(self):
            return 0

    monkeypatch.setattr(rwl.subprocess, "Popen",
                        lambda cmd, env=None: FakeProc())
    assert rwl.main(["google", "--", "echo", "hi"]) == 0
    assert calls["target"] == "google"
    assert rwl.main(["avalai", "--", "echo", "hi"]) == 0
    assert calls["target"] == "avalai"


def test_report_rejects_unknown_provider():
    """Review finding: arbitrary provider strings must not mint keys."""
    from supervisor import known_provider
    assert known_provider(None) is True
    assert known_provider("zen") is True
    assert known_provider(" ZEN ") is True
    assert known_provider("victim-provider") is False
    assert known_provider("") is False
    pool = _link_pool()
    lease = pool.lease("zen")
    assert pool.report(lease["lease_id"], "http429",
                       "victim-provider") == {"action": "keep"}
    assert pool.lease("zen")["mode"] == "tunnel"  # nothing cooled
    assert pool.lease("google")["mode"] == "tunnel"


def test_discard_lease_drops_under_lock():
    """Review finding: lease cleanup owns its locking."""
    pool = _link_pool()
    lease = pool.lease("zen")
    pool.discard_lease(lease["lease_id"])
    assert pool.report(lease["lease_id"], "ok") == {
        "action": "unknown-lease"}
    pool.discard_lease("never-existed")  # no-op, no raise


def test_run_with_lease_normalizes_target(monkeypatch):
    """Review finding: CLI gate matches supervisor normalization."""
    import run_with_lease as rwl
    calls = {}

    def fake_lease(target):
        calls["target"] = target
        return {"lease_id": "L1", "mode": "direct", "proxy_url": "",
                "egress_ip": "direct"}

    monkeypatch.setattr(rwl.client, "lease", fake_lease)
    monkeypatch.setattr(rwl.client, "report",
                        lambda lid, outcome: {"action": "keep"})

    class FakeProc:
        def wait(self):
            return 0

    monkeypatch.setattr(rwl.subprocess, "Popen",
                        lambda cmd, env=None: FakeProc())
    assert rwl.main(["  ZEN ", "--", "echo", "hi"]) == 0
    assert calls["target"] == "zen"


def test_parse_subscription_dedupes_exact_links():
    body = ("vless://u@one.org:443?x=1\n"
            "vless://u@one.org:443?x=1\n"
            "vless://u@two.org:443?x=1\n")
    rows = supervisor.parse_subscription(body)
    assert [(r["host"], r["port"]) for r in rows] == [("one.org", 443),
                                                     ("two.org", 443)]


def test_pool_lease_cache_hit_reuses_hint_and_writes_back(
        monkeypatch, tmp_path, capsys):
    """R7 production hit path: a fresh cached row + reachable ping
    mints the hint (not the classic first-avail), prints CACHE HIT,
    and writes the measured latency back. Hermetic: tmp cache file +
    fake tcp_ping (the module autouse fixture pins dead; this test
    overrides it)."""
    import time as _time
    pool = Pool()
    pool.load([
        {"scheme": "vless", "host": "first", "port": 1, "id": "s-first",
         "link": "vless://u@first:1"},
        {"scheme": "vless", "host": "cached", "port": 2, "id": "s-cached",
         "link": "vless://u@cached:2"},
    ])
    cache = tmp_path / "clean_cache.json"
    cache.write_text(json.dumps({"saved_at": "t", "entries": [
        {"server_id": "s-cached", "provider": "zen",
         "last_ok_ts": _time.time() - 5, "latency_ms": 9}]}),
        encoding="utf-8")
    monkeypatch.setenv("EGRESS_CLEAN_CACHE_PATH", str(cache))
    monkeypatch.delenv("EGRESS_CLEAN_TTL", raising=False)
    monkeypatch.setattr(
        supervisor, "_server_tcp_ping",
        lambda server, timeout=2.0: 4
        if server.get("host") == "cached" else None)
    lease = pool.lease("zen")
    assert lease["server_id"] == "s-cached"
    assert "CACHE HIT" in capsys.readouterr().out
    entries = json.loads(cache.read_text(encoding="utf-8"))["entries"]
    back = [e for e in entries if e["server_id"] == "s-cached"]
    assert len(back) == 1 and back[0]["latency_ms"] == 4


def test_http_lease_tunnel_server_matches_on_cache_hit(
        monkeypatch, tmp_path):
    """OC W: end-to-end (HTTP) lease server == tunnel server on a
    cache hit — the hint is threaded into acquire, so a later
    http429 report cools the server carrying traffic."""
    import time as _time
    import supervisor as sup
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    _FakeTunnel.started.clear()
    _FakeTunnel.stopped.clear()
    sup.TOKEN = "test-token"
    sup.POOL.servers.clear()
    sup.POOL.leases.clear()
    sup.POOL.cooldown_until.clear()
    sup.POOL.load([
        {"scheme": "vless", "host": "first", "port": 1, "id": "s-first",
         "link": "vless://u@first:1"},
        {"scheme": "vless", "host": "cached", "port": 2, "id": "s-cached",
         "link": "vless://u@cached:2"},
    ])
    cache = tmp_path / "clean_cache.json"
    cache.write_text(json.dumps({"saved_at": "t", "entries": [
        {"server_id": "s-cached", "provider": "zen",
         "last_ok_ts": _time.time() - 5, "latency_ms": 9}]}),
        encoding="utf-8")
    monkeypatch.setenv("EGRESS_CLEAN_CACHE_PATH", str(cache))
    monkeypatch.delenv("EGRESS_CLEAN_TTL", raising=False)
    monkeypatch.setattr(
        sup, "_server_tcp_ping",
        lambda server, timeout=2.0: 4
        if server.get("host") == "cached" else None)
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
        assert lease["server_id"] == "s-cached"
        assert _FakeTunnel.started == ["s-cached"]
    finally:
        server.shutdown()
        thread.join(timeout=10)
        sup.TUNNELS.stop()
        sup.TOKEN = ""


def test_pool_retarget_lease_syncs_record_to_tunnel(
        tmp_path, monkeypatch):
    """Fallback sync: when acquire serves another server than the
    hint, the lease record follows it — a later http429 cools the
    server carrying traffic, not the stale hint. The switch is
    audit-logged (secret-free)."""
    import supervisor as sup
    monkeypatch.setattr(sup, "LEASES_PATH", tmp_path / "leases.jsonl")
    pool = Pool()
    pool.load([
        {"scheme": "vless", "host": "a", "port": 1, "id": "s1",
         "link": "vless://u@a:1"},
        {"scheme": "vless", "host": "b", "port": 1, "id": "s2",
         "link": "vless://u@b:1"},
    ])
    lease = pool.lease("zen")
    assert lease["server_id"] == "s1"
    pool.retarget_lease(lease["lease_id"], "s2")
    pool.retarget_lease("unknown-lease", "s2")  # no-op, no raise
    assert pool.report(lease["lease_id"], "http429",
                       "zen") == {"action": "switch"}
    assert pool.lease("zen")["server_id"] == "s1"  # s2 cooling
    events = [json.loads(line) for line in
              (tmp_path / "leases.jsonl").read_text(
                  encoding="utf-8").splitlines()]
    assert [e["event"] for e in events] == ["lease", "retarget",
                                            "report", "lease"]
    assert events[1]["server"] == "s2"
    assert len(events[1]["lease"]) <= 8
    blob = "\n".join(json.dumps(e) for e in events)
    assert "proxy_url" not in blob and "token" not in blob.lower()


def test_tunnel_owner_acquire_skips_malformed_servers(monkeypatch):
    """acquire mirrors the lease guards: entries without id (or not
    dicts) never raise KeyError — the first healthy server wins."""
    from supervisor import TunnelOwner
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    _FakeTunnel.started.clear()
    _FakeTunnel.stopped.clear()
    pool = Pool()
    pool.servers = [
        {"scheme": "vless", "host": "bad", "port": 1,
         "link": "vless://u@bad:1"},  # no id
        "not-a-dict",
        {"scheme": "vless", "host": "good", "port": 2, "id": "s-good",
         "link": "vless://u@good:2"},
    ]
    owner = TunnelOwner(pool)
    _, _, sid = owner.acquire()
    assert sid == "s-good"
    owner.stop()


# --- Probe-batch hermetic coverage (PR feat/egress-probe-batch) ---

def _live_ping(server, timeout=2.0):
    return 4


def _dead_ping(server, timeout=2.0):
    return None


def test_probe_all_dead_parks_fast_without_spawn(monkeypatch):
    """A fully dead pool parks here (no 25s spawn burn per attempt):
    no xray start attempted, every probed server cooled."""
    from supervisor import TunnelOwner
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    monkeypatch.setattr(supervisor, "_server_tcp_ping", _dead_ping)
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
    try:
        with pytest.raises(RuntimeError, match="no live server"):
            owner.acquire(provider="zen")
    finally:
        owner.stop()
    assert _FakeTunnel.started == []
    assert pool.is_cool("s1", "zen") and pool.is_cool("s2", "zen")


def test_probe_dead_cooled_live_kept_in_order(monkeypatch):
    """Dead probed servers cool (600s) while live ones keep pool order
    — the first live server still wins the spawn."""
    from supervisor import TunnelOwner
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    monkeypatch.setattr(
        supervisor, "_server_tcp_ping",
        lambda server, timeout=2.0: None
        if server["id"] == "s-dead" else 5)
    _FakeTunnel.started.clear()
    _FakeTunnel.stopped.clear()
    pool = Pool()
    pool.load([
        {"scheme": "vless", "host": "a", "port": 1, "id": "s1",
         "link": "vless://u@a:1"},
        {"scheme": "vless", "host": "d", "port": 1, "id": "s-dead",
         "link": "vless://u@d:1"},
        {"scheme": "vless", "host": "b", "port": 1, "id": "s2",
         "link": "vless://u@b:1"},
    ])
    owner = TunnelOwner(pool)
    try:
        _, _, sid = owner.acquire()
    finally:
        owner.stop()
    assert sid == "s1"
    assert _FakeTunnel.started == ["s1"]
    assert pool.is_cool("s-dead", None)
    assert not pool.is_cool("s1", None)
    assert not pool.is_cool("s2", None)


def test_probe_tail_survives_as_unprobed_fallback(monkeypatch):
    """Servers past the first 8 are never probed and never cooled: a
    dead head still leaves the healthy tail available."""
    from supervisor import TunnelOwner
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    monkeypatch.setattr(supervisor, "_server_tcp_ping", _dead_ping)
    _FakeTunnel.started.clear()
    _FakeTunnel.stopped.clear()
    pool = Pool()
    pool.load([
        {"scheme": "vless", "host": "h%d" % i, "port": 1,
         "id": "s%d" % i, "link": "vless://u@h%d:1" % i}
        for i in range(10)
    ])
    owner = TunnelOwner(pool)
    try:
        _, _, sid = owner.acquire()
    finally:
        owner.stop()
    assert sid == "s8"  # first unprobed tail server
    assert _FakeTunnel.started == ["s8"]
    assert all(pool.is_cool("s%d" % i, None) for i in range(8))
    assert not pool.is_cool("s8", None)
    assert not pool.is_cool("s9", None)


def test_reuse_skips_probe_batch(monkeypatch):
    """A live tunnel for the wanted server is reused with zero pings:
    steady reuse pays no probe wall and a ping flake can never cool
    the working tunnel."""
    from supervisor import TunnelOwner
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FakeTunnel)
    monkeypatch.setattr(supervisor, "_server_tcp_ping", _live_ping)
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
    try:
        proxy, _, sid = owner.acquire()
        assert (proxy, sid) == ("http://127.0.0.1:19999", "s1")
        probed = []

        def _flake(server, timeout=2.0):
            probed.append(server["id"])
            return None

        monkeypatch.setattr(supervisor, "_server_tcp_ping", _flake)
        proxy2, _, sid2 = owner.acquire()
        assert (proxy2, sid2) == (proxy, "s1")
        assert probed == []
        assert _FakeTunnel.started == ["s1"]
        assert not pool.is_cool("s1", None)
    finally:
        owner.stop()


class _FailS2Tunnel(_FakeTunnel):
    def start(self, timeout=25):
        if self.server["id"] == "s2":
            raise RuntimeError("xray port never opened (timeout)")
        return super().start(timeout)


def test_acquire_failure_surfaces_actual_server(monkeypatch):
    """Spawn failure names the failed server (not the stale hint): the
    hint asked for s1, the dead hint lost, s2 failed to spawn."""
    from supervisor import TunnelOwner
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FailS2Tunnel)
    monkeypatch.setattr(
        supervisor, "_server_tcp_ping",
        lambda server, timeout=2.0: None
        if server["id"] == "s1" else 7)
    pool = Pool()
    pool.load([
        {"scheme": "vless", "host": "a", "port": 1, "id": "s1",
         "link": "vless://u@a:1"},
        {"scheme": "vless", "host": "b", "port": 1, "id": "s2",
         "link": "vless://u@b:1"},
    ])
    owner = TunnelOwner(pool)
    try:
        with pytest.raises(RuntimeError) as exc_info:
            owner.acquire(prefer="s1")
    finally:
        owner.stop()
    assert exc_info.value.failed_server_id == "s2"
    assert pool.is_cool("s1", None)  # probed dead
    assert not pool.is_cool("s2", None)  # spawn failure cools nothing here


def test_http_lease_failure_cools_actual_server(monkeypatch):
    """End-to-end over HTTP: dead hint + failing spawn on the live
    server parks the lease and cools the server that failed (s2),
    not just the hint (s1)."""
    import supervisor as sup
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FailS2Tunnel)
    monkeypatch.setattr(
        sup, "_server_tcp_ping",
        lambda server, timeout=2.0: None
        if server["id"] == "s1" else 7)
    _FailS2Tunnel.started.clear()
    _FailS2Tunnel.stopped.clear()
    sup.TOKEN = "test-token"
    sup.POOL.servers.clear()
    sup.POOL.leases.clear()
    sup.POOL.cooldown_until.clear()
    sup.POOL.load([
        {"scheme": "vless", "host": "a", "port": 1, "id": "s1",
         "link": "vless://u@a:1"},
        {"scheme": "vless", "host": "b", "port": 1, "id": "s2",
         "link": "vless://u@b:1"},
    ])
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request as _url
        req = _url.Request(
            "http://127.0.0.1:%d/v1/lease" % port,
            data=json.dumps({"target": "zen"}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer test-token"})
        with _url.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
        assert body.get("error") == "park"
        assert sup.POOL.is_cool("s2", "zen")
    finally:
        server.shutdown()
        thread.join(timeout=10)
        sup.TUNNELS.stop()
        sup.TOKEN = ""


def test_report_location_blocked_cools_switches_keeps_lease():
    """location-blocked cools the pair + switches, lease kept (no reauth)."""
    pool = _link_pool()
    lease = pool.lease("google")
    assert pool.report(lease["lease_id"], "location-blocked") == {
        "action": "switch"}
    assert pool.lease("google")["error"] == "park"  # pair cooling
    assert pool.lease("zen")["mode"] == "tunnel"  # others unaffected
    assert pool.report(lease["lease_id"], "ok") == {"action": "keep"}


def test_report_location_blocked_exiles_persistent_scale():
    """Geo-block exile runs on the persistent (generic 300s) scale, not
    the 4s google post-429 scale: still cooling 5s later."""
    import time as _time
    pool = _link_pool()
    lease = pool.lease("google")
    assert pool.report(lease["lease_id"], "location-blocked") == {
        "action": "switch"}
    assert pool.is_cool("s1", "google", now=_time.time() + 5.0)


def test_report_http429_honors_cooldown_secs_env(monkeypatch):
    """FACTORY_COOLDOWN_SECS overrides the per-provider table on the
    main report path (Pool.cool resolves the env when seconds is None)."""
    import time as _time
    import supervisor as sup
    monkeypatch.setenv("FACTORY_COOLDOWN_SECS", "11")
    pool = _link_pool()
    lease = pool.lease("zen")
    assert pool.report(lease["lease_id"], "http429") == {"action": "switch"}
    assert pool.is_cool("s1", "zen")
    assert not pool.is_cool("s1", "zen", now=_time.time() + 12.0)


def test_tunnel_cooldown_override_from_env_unset_and_garbage(monkeypatch):
    """Unset/unparseable/non-positive FACTORY_COOLDOWN_SECS means the
    table default (None); a finite positive value wins."""
    import supervisor as sup
    monkeypatch.delenv("FACTORY_COOLDOWN_SECS", raising=False)
    assert sup._cooldown_override_from_env() is None
    monkeypatch.setenv("FACTORY_COOLDOWN_SECS", "bogus")
    assert sup._cooldown_override_from_env() is None
    monkeypatch.setenv("FACTORY_COOLDOWN_SECS", "-5")
    assert sup._cooldown_override_from_env() is None
    monkeypatch.setenv("FACTORY_COOLDOWN_SECS", "11")
    assert sup._cooldown_override_from_env() == 11.0


def test_http_lease_failure_cool_honors_cooldown_secs_env(monkeypatch):
    """End-to-end over HTTP: FACTORY_COOLDOWN_SECS overrides the fixed
    tunnel_fetch 300s when an acquire failure cools the dead server."""
    import time as _time
    import supervisor as sup
    import tunnel as tunnel_mod
    monkeypatch.setattr(tunnel_mod, "Tunnel", _FailS2Tunnel)
    monkeypatch.setattr(
        sup, "_server_tcp_ping",
        lambda server, timeout=2.0: None
        if server["id"] == "s1" else 7)
    monkeypatch.setenv("FACTORY_COOLDOWN_SECS", "11")
    _FailS2Tunnel.started.clear()
    _FailS2Tunnel.stopped.clear()
    sup.TOKEN = "test-token"
    sup.POOL.servers.clear()
    sup.POOL.leases.clear()
    sup.POOL.cooldown_until.clear()
    sup.POOL.load([
        {"scheme": "vless", "host": "a", "port": 1, "id": "s1",
         "link": "vless://u@a:1"},
        {"scheme": "vless", "host": "b", "port": 1, "id": "s2",
         "link": "vless://u@b:1"},
    ])
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request as _url
        req = _url.Request(
            "http://127.0.0.1:%d/v1/lease" % port,
            data=json.dumps({"target": "zen"}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer test-token"})
        with _url.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
        assert body.get("error") == "park"
        assert sup.POOL.is_cool("s2", "zen")
        # Override honored: expired after 11s, not the fixed 300s.
        assert not sup.POOL.is_cool("s2", "zen",
                                    now=_time.time() + 12.0)
    finally:
        server.shutdown()
        thread.join(timeout=10)
        sup.TUNNELS.stop()
        sup.TOKEN = ""


def test_report_http429_and_auth_err_unchanged():
    """http429 still cools + switches; auth_err still reaps the lease."""
    pool = _link_pool()
    lease = pool.lease("zen")
    assert pool.report(lease["lease_id"], "http429") == {"action": "switch"}
    assert pool.lease("zen")["error"] == "park"
    lease2 = pool.lease("google")
    assert pool.report(lease2["lease_id"], "auth_err") == {
        "action": "reauth"}
    assert pool.report(lease2["lease_id"], "ok") == {
        "action": "unknown-lease"}


def test_client_report_location_blocked_vocab(monkeypatch):
    """client.report forwards the location-blocked outcome + provider."""
    import client as egress_client
    seen = {}

    def fake_call(path, payload):
        seen[path] = payload
        return {"action": "switch"}

    monkeypatch.setattr(egress_client, "_call", fake_call)
    egress_client.report("L1", "location-blocked", provider="google")
    assert seen["/v1/report"] == {"lease_id": "L1",
                                  "outcome": "location-blocked",
                                  "provider": "google"}
