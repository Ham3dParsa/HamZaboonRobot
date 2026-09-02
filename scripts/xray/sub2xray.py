#!/usr/bin/env python3
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

if len(sys.argv) < 2:
    print("usage: sub2xray.py <sub_url>", file=sys.stderr)
    sys.exit(1)
sub = sys.argv[1]
req = urllib.request.Request(sub, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
except (urllib.error.URLError, urllib.error.HTTPError) as e:
    print(f"fetch fail: {e}", file=sys.stderr)
    sys.exit(1)
try:
    txt = raw.decode().strip()
    txt += "=" * (-len(txt) % 4)
    raw = base64.b64decode(txt).decode(errors="ignore")
except Exception:
    raw = raw.decode(errors="ignore")
outs = []
for line in raw.strip().splitlines():
    line = line.strip()
    if not line.startswith("vless://"):
        continue
    u = urllib.parse.urlparse(line)
    qs = urllib.parse.parse_qs(u.query)
    get = lambda k, d="": qs.get(k, [d])[0]
    net = get("type", "tcp")
    sec = get("security", "none")
    sni = get("sni", "")
    fp = get("fp", "chrome")
    pbk = get("pbk", "")
    sid = get("sid", "")
    spx = get("spx", "/")
    flow = get("flow", "")
    path = get("path", "/")
    host = get("host", "")
    stream = {"network": net, "security": sec}
    if sec == "reality":
        stream["realitySettings"] = {
            "serverName": sni,
            "fingerprint": fp,
            "publicKey": pbk,
            "shortId": sid,
            "spiderX": spx or "/",
        }
    elif sec == "tls":
        stream["tlsSettings"] = {"serverName": sni or u.hostname, "fingerprint": fp}
    if net == "ws":
        stream["wsSettings"] = {"path": path, "headers": {"Host": host} if host else {}}
    outs.append(
        {
            "protocol": "vless",
            "tag": f"p{len(outs)}",
            "settings": {"vnext": [{"address": u.hostname, "port": u.port or 443, "users": [{"id": u.username, "encryption": "none", "flow": flow}]}]},
            "streamSettings": stream,
        }
    )
print(json.dumps(outs, ensure_ascii=False))
