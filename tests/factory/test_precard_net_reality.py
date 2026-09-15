"""P0 net core: parse-only hermetic tests for reality.patch.

No network, no keys, no files: vless+reality links are parsed and
rendered to xray-core config dicts in memory. Pins the patched
behavior (reality params survive parse -> config) and the unpatched
TLS path (regression).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "tools", "egress"))
import xrayconf as XC  # noqa: E402


def _reality_link():
    return ("vless://11111111-2222-4333-8444-555555555555@ep.example.net"
            ":443?security=reality&encryption=none&pbk=PUBKEY84CHARS"
            "sdflsdkfjsdlfkjsdlfkjsdlkfjsdlkfjskldfjslkdfj&fp=chrome&"
            "sni=cdn.example.com&sid=abcd1234&spx=%2F&flow=xtls-rprx-"
            "vision&type=tcp#reality-node")


def test_reality_params_survive_parse():
    node = XC.parse_link(_reality_link())
    assert node["scheme"] == "vless"
    assert node["security"] == "reality"
    assert node["pbk"].startswith("PUBKEY")
    assert node["sid"] == "abcd1234"
    assert node["fp"] == "chrome"
    assert node["spx"] == "/"
    assert node["sni"] == "cdn.example.com"
    assert node["flow"] == "xtls-rprx-vision"


def test_reality_config_carries_reality_settings_and_flow():
    cfg = XC.xray_config(XC.parse_link(_reality_link()), 18081)
    stream = cfg["outbounds"][0]["streamSettings"]
    assert stream["security"] == "reality"
    assert "realitySettings" in stream and "tlsSettings" not in stream
    reality = stream["realitySettings"]
    assert reality["serverName"] == "cdn.example.com"
    assert reality["fingerprint"] == "chrome"
    assert reality["publicKey"].startswith("PUBKEY")
    assert reality["shortId"] == "abcd1234"
    assert reality["spiderX"] == "/"
    users = cfg["outbounds"][0]["settings"]["vnext"][0]["users"]
    assert users[0]["flow"] == "xtls-rprx-vision"
    assert cfg["inbounds"][0]["port"] == 18081


def test_reality_partial_params_omit_empty_settings():
    link = ("vless://11111111-2222-4333-8444-555555555555@h.example"
            ":443?security=reality&type=tcp#bare")
    cfg = XC.xray_config(XC.parse_link(link), 18082)
    stream = cfg["outbounds"][0]["streamSettings"]
    assert stream["security"] == "reality"
    assert stream["realitySettings"] == {"serverName": "h.example"}
    users = cfg["outbounds"][0]["settings"]["vnext"][0]["users"]
    assert users[0]["flow"] == ""


def test_tls_path_unchanged_regression():
    link = ("vless://11111111-2222-4333-8444-555555555555@h.example"
            ":443?security=tls&sni=s.example.com&type=tcp#tls-node")
    node = XC.parse_link(link)
    assert node["flow"] == "" and node["pbk"] == ""
    cfg = XC.xray_config(node, 18083)
    stream = cfg["outbounds"][0]["streamSettings"]
    assert stream["security"] == "tls"
    assert stream["tlsSettings"] == {"serverName": "s.example.com"}
    assert "realitySettings" not in stream
