#!/usr/bin/env python3
import json
import os
import pathlib
import sys

# Use persistent clean list if available, fallback to outs
src = "/app/.xray/clean.json"
if not pathlib.Path(src).exists():
    src = "/app/.xray/outs.json"
if not pathlib.Path(src).exists():
    src = "/tmp/clean.json"
if not pathlib.Path(src).exists():
    src = "/tmp/outs.json"
with open(src) as f:
    outs = json.load(f)
if not isinstance(outs, list) or len(outs) == 0:
    print(f"rebuild_config: no nodes in {src} - abort, keep previous config", file=sys.stderr)
    sys.exit(1)
tags = []
for _i, _o in enumerate(outs):
    _t = _o.get("tag") if isinstance(_o, dict) else None
    if not isinstance(_t, str) or not _t:
        print(f"rebuild_config: entry {_i} in {src} has no non-empty string tag - abort, keep previous config", file=sys.stderr)
        sys.exit(1)
    tags.append(_t)
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
        "balancers": [{"tag": "auto", "selector": tags, "strategy": {"type": "leastPing"}}],
    },
    "observatory": {
        "subjectSelector": tags,
        "probeUrl": "https://www.google.com/generate_204",
        "probeInterval": "10m",
    },
    "log": {"loglevel": "warning", "access": "/var/log/xray/access.log", "error": "/var/log/xray/error.log"},
}
# Use persistent path if available, fallback to legacy
out_path = "/app/.xray/config.json" if pathlib.Path("/app/.xray").exists() else "/usr/local/etc/xray/config.json"
tmp_path = out_path + ".tmp"
pathlib.Path(tmp_path).write_text(json.dumps(cfg, indent=2))
os.replace(tmp_path, out_path)
# Also keep legacy path for compatibility
if out_path != "/usr/local/etc/xray/config.json":
    legacy = "/usr/local/etc/xray/config.json"
    pathlib.Path(legacy).parent.mkdir(parents=True, exist_ok=True)
    tmp2 = legacy + ".tmp"
    pathlib.Path(tmp2).write_text(json.dumps(cfg, indent=2))
    os.replace(tmp2, legacy)
print(f"built {len(outs)} from {src} -> {out_path}")
