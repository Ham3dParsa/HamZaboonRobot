"""Probe Zen keys + egress: one tiny call per key, reports OK/429/401.
Usage: python factory/probe_keys.py
Reads factory/.env (never prints values). Burns ~2 micro-calls total.
"""
import json
import os
import pathlib
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from env_loader import KEYS  # noqa: E402  (allowlist only, values via env)

ZEN_URL = "https://opencode.ai/zen/v1/responses"


def load_env():
    env_path = pathlib.Path(__file__).resolve().parent / ".env"
    data = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def probe(name, key):
    body = json.dumps({
        "model": "muse-spark-1.3-contributor-free",
        "input": "Reply with the single word: ok",
        "reasoning": {"effort": "minimal"},
        "max_output_tokens": 16,
    }).encode()
    req = urllib.request.Request(
        ZEN_URL, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key,
                 "User-Agent": "HamZaban-factory/1.0"})
    import time as _t
    _t0 = _t.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            code = getattr(resp, "status", 200)
            ms = int((_t.time() - _t0) * 1000)
            return "%s: HTTP %s OK (key live, %dms)" % (name, code, ms)
    except Exception as exc:  # noqa: BLE001 (probe must report, not raise)
        ms = int((_t.time() - _t0) * 1000)
        code = getattr(exc, "code", "?")
        body = ""
        try:
            raw = exc.read()
            body = (" | body: " + raw.decode("utf-8", "replace")[:200]) \
                if raw else ""
        except Exception:  # noqa: BLE001 (body is best-effort)
            pass
        hint = {429: "quota out — switch server",
                401: "bad key", 403: "forbidden"}.get(code, "see error")
        return "%s: HTTP %s (%s, %dms%s)" % (name, code, hint, ms, body)


def main():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=15) \
                as resp:
            print("egress IP: %s" % resp.read().decode().strip(), flush=True)
    except Exception as exc:  # noqa: BLE001 (IP is diagnostic only)
        print("egress IP: unknown (%s)" % exc, flush=True)
    data = load_env()
    tried = 0
    for key_name in KEYS:
        if "ZEN" not in key_name:
            continue
        key = os.environ.get(key_name, "") or data.get(key_name, "")
        if not key:
            print("%s: (empty, skipped)" % key_name)
            continue
        tried += 1
        print(probe(key_name, key), flush=True)
    if not tried:
        print("no Zen keys configured")


if __name__ == "__main__":
    main()
