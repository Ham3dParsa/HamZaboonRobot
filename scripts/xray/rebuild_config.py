#!/usr/bin/env python3
import json
import pathlib

# Use persistent clean list if available, fallback to outs
src = "/app/hamzaban/.xray/clean.json"
if not pathlib.Path(src).exists():
    src = "/app/hamzaban/.xray/outs.json"
if not pathlib.Path(src).exists():
    src = "/tmp/clean.json"
if not pathlib.Path(src).exists():
    src = "/tmp/outs.json"
outs = json.load(open(src))
cfg = {
    "inbounds": [
        {"port": 1080, "protocol": "socks", "settings": {"auth": "noauth", "udp": True}},
        {"port": 12345, "protocol": "dokodemo-door", "settings": {"network": "tcp", "followRedirect": True}},
    ],
    "outbounds": outs + [{"protocol": "freedom", "tag": "direct"}],
    "routing": {
        "rules": [
            {"type": "field", "domain": ["generativelanguage.googleapis.com", "generativelanguage.google.com"], "balancerTag": "auto"},
            {"type": "field", "network": "tcp,udp", "outboundTag": "direct"},
        ],
        "balancers": [{"tag": "auto", "selector": [o["tag"] for o in outs], "strategy": {"type": "roundRobin"}}],
    },
    "log": {"loglevel": "warning", "access": "/var/log/xray/access.log", "error": "/var/log/xray/error.log"},
}
# Use persistent path if available, fallback to legacy
out_path = "/app/hamzaban/.xray/config.json" if pathlib.Path("/app/hamzaban/.xray").exists() else "/usr/local/etc/xray/config.json"
pathlib.Path(out_path).write_text(json.dumps(cfg, indent=2))
# Also keep legacy path for compatibility
if out_path != "/usr/local/etc/xray/config.json":
    pathlib.Path("/usr/local/etc/xray/config.json").write_text(json.dumps(cfg, indent=2))
print(f"built {len(outs)} from {src} -> {out_path}")
