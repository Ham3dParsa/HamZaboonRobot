"""Thin client for the egress supervisor (loopback HTTP + Bearer).

Phase 1: direct leases work with no VPN and no tunnel (AvalAI/domestic).
Zen/tunnel leases park until phase 2 (xray children).
"""
from __future__ import annotations

import json
import os
import urllib.request

SUP_URL = os.environ.get("EGRESS_SUP_URL", "http://127.0.0.1:18789")
SUP_TOKEN = os.environ.get("EGRESS_SUP_TOKEN", "")


def _call(path, payload):
    body = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        SUP_URL + path, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + SUP_TOKEN})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def lease(target="direct"):
    """Lease an egress. Returns dict with lease_id/mode/proxy_url.

    target is one of supervisor.TARGETS (direct/zen/google/openrouter/
    avalai); "zen" keeps its historic tunnel meaning.
    """
    return _call("/v1/lease", {"target": target})


def report(lease_id, outcome, provider=None):
    """Report outcome (ok|http429|net_err|auth_err|unknown).

    provider overrides the lease's provider for per-(server,provider)
    cooldowns; None (default) cools the lease's own provider, which
    keeps every old caller working unmodified.
    """
    payload = {"lease_id": lease_id, "outcome": outcome}
    if provider is not None:
        payload["provider"] = provider
    return _call("/v1/report", payload)


def health():
    """Supervisor health snapshot."""
    req = urllib.request.Request(
        SUP_URL + "/v1/health",
        headers={"Authorization": "Bearer " + SUP_TOKEN})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)
