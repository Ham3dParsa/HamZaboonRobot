"""Subscription link -> xray-core config (phase 2 tunnels).

Supports vmess / vless / trojan / ss link shapes with common parameters.
Best-effort: unknown/exotic params are ignored; unparseable links raise
ValueError so the pool skips them with a reason instead of crashing.
Outbound goes straight to the server; inbound is a loopback HTTP proxy
(stdlib urllib honors it with zero extra dependencies).
"""
from __future__ import annotations

import base64
import json
import urllib.parse


def _b64decode(text):
    pad = "=" * (-len(text or "") % 4)
    return base64.b64decode((text or "") + pad).decode("utf-8", "replace")


def _parse_vmess(link):
    payload = json.loads(_b64decode(link.split("://", 1)[1]))
    return {
        "address": str(payload.get("add", "")),
        "port": int(payload.get("port", 0) or 0),
        "uuid": str(payload.get("id", "")),
        "alter_id": int(payload.get("aid", 0) or 0),
        "security": str(payload.get("scy", "auto") or "auto"),
        "network": str(payload.get("net", "tcp") or "tcp"),
        "tls": str(payload.get("tls", "") or "").lower() == "tls",
        "sni": str(payload.get("sni", "") or ""),
        "path": str(payload.get("path", "") or ""),
        "host": str(payload.get("host", "") or ""),
    }


def _parse_vless_trojan(link, scheme):
    body, _, _frag = link.split("://", 1)[1].partition("#")
    cred, _, at = body.partition("@")
    hostport, _, query = at.partition("?")
    host, _, port_s = hostport.rpartition(":")
    try:
        port = int(port_s)
    except (TypeError, ValueError):
        raise ValueError("bad port in %s link" % scheme)
    params = urllib.parse.parse_qs(query)
    get = lambda k, d="": params.get(k, [d])[0]
    sec = get("security", "")
    sni = get("sni") or get("serverName", "")
    # trojan is TLS-by-convention: an sni with no explicit security flag
    # still means TLS (plain trojan on 443 is a dead link otherwise).
    tls = sec in ("tls", "reality") or \
        (scheme == "trojan" and bool(sni) and sec != "none")
    return {
        "address": host.strip("[]"),
        "port": port,
        "uuid": urllib.parse.unquote(cred),
        "security": sec or "none",
        "network": get("type", "tcp"),
        "tls": tls,
        "sni": sni,
        "path": get("path", ""),
        "host": get("host", ""),
    }


def _parse_ss(link):
    body = link.split("://", 1)[1]
    if "@" not in body:
        body = _b64decode(body)
    cred, _, at = body.partition("@")
    if ":" not in cred:
        cred = _b64decode(cred)
    method, _, password = cred.partition(":")
    hostport = at.split("?")[0].split("#")[0].split("/")[0]
    host, _, port_s = hostport.rpartition(":")
    return {"method": method, "password": password,
            "address": host.strip("[]"), "port": int(port_s)}


def parse_link(link):
    """Parse one subscription link -> normalized dict. Raises ValueError."""
    scheme = (link or "").split("://", 1)[0].lower()
    if scheme == "vmess":
        node = _parse_vmess(link)
        node["scheme"] = "vmess"
    elif scheme in ("vless", "trojan"):
        node = _parse_vless_trojan(link, scheme)
        node["scheme"] = scheme
    elif scheme == "ss":
        node = _parse_ss(link)
        node["scheme"] = "ss"
    else:
        raise ValueError("unsupported scheme: %s" % scheme)
    if not node.get("address") or not node.get("port"):
        raise ValueError("missing address/port")
    return node


def xray_config(node, http_port):
    """Build an xray-core config dict: loopback HTTP inbound + one node."""
    stream = {"network": node.get("network") or "tcp"}
    if node.get("tls"):
        tls = {"serverName": node.get("sni") or node.get("address")}
        stream["security"] = "tls"
        stream["tlsSettings"] = tls
    if (node.get("network") or "tcp") == "ws":
        ws = {"path": node.get("path") or "/"}
        if node.get("host"):
            ws["headers"] = {"Host": node["host"]}
        stream["wsSettings"] = ws
    scheme = node.get("scheme")
    if scheme == "vmess":
        users = [{"id": node["uuid"], "alterId": node.get("alter_id", 0),
                  "security": node.get("security") or "auto"}]
        outbound = {"protocol": "vmess",
                    "settings": {"vnext": [{"address": node["address"],
                                            "port": node["port"],
                                            "users": users}]},
                    "streamSettings": stream}
    elif scheme == "vless":
        outbound = {"protocol": "vless",
                    "settings": {"vnext": [{"address": node["address"],
                                            "port": node["port"],
                                            "users": [{"id": node["uuid"],
                                                       "encryption": "none",
                                                       "flow": ""}]}]},
                    "streamSettings": stream}
    elif scheme == "trojan":
        outbound = {"protocol": "trojan",
                    "settings": {"servers": [{
                        "address": node["address"], "port": node["port"],
                        "password": node["uuid"]}]},
                    "streamSettings": stream}
    elif scheme == "ss":
        outbound = {"protocol": "shadowsocks",
                    "settings": {"servers": [{
                        "address": node["address"], "port": node["port"],
                        "method": node.get("method", "aes-256-gcm"),
                        "password": node.get("password", "")}]},
                    "streamSettings": {"network": "tcp"}}
    else:  # pragma: no cover (parse_link guards)
        raise ValueError("unsupported scheme: %s" % scheme)
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "port": int(http_port), "listen": "127.0.0.1",
            "protocol": "http",
            "settings": {"timeout": 300},
        }],
        "outbounds": [outbound],
    }
