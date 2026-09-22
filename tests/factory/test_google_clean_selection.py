"""Hermetic tests for Google-clean egress selection (no network).

Covers factory/linking/google_clean.py (classifier, keyless check
with a fake opener, pure whitelist selection, cache write-back to a
tmp file) plus the probe seam in factory/linking/probe_providers.py
(whitelist annotation, location-blocked reporting, success
write-back) — every seam injected, nothing real touched.
"""

import io
import json
import os
import sys
import urllib.error

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.linking import google_clean as gc
from factory.linking import probe_providers as probe_mod

NOW = 1_000_000.0
TTL = 3600.0

LOC_BODY = b'{"error": {"code": 400, "message": "User location is not supported for the API use.", "status": "FAILED_PRECONDITION"}}'
KEY_BODY = b'{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}'


def _rows():
    return [
        {"server_id": "s-fresh-slow", "provider": "google",
         "last_ok_ts": NOW - 100, "latency_ms": 900},
        {"server_id": "s-fresh-fast", "provider": "google",
         "last_ok_ts": NOW - 50, "latency_ms": 120},
        {"server_id": "s-stale", "provider": "google",
         "last_ok_ts": NOW - 99999, "latency_ms": 10},
        {"server_id": "s-zen", "provider": "zen",
         "last_ok_ts": NOW - 10, "latency_ms": 5},
    ]


# ─── classifier ───

def test_classify_exit_live_is_clean():
    assert gc.classify_exit(200, "") == ("clean", "live")


def test_classify_exit_location_blocked():
    assert gc.classify_exit(400, LOC_BODY.decode()) == (
        "blocked", "location-blocked")


def test_classify_exit_key_complaint_is_clean():
    assert gc.classify_exit(400, KEY_BODY.decode()) == (
        "clean", "key-required")
    assert gc.classify_exit(401, "") == ("clean", "key-required")


def test_classify_exit_plain_403_is_blocked():
    assert gc.classify_exit(403, "forbidden") == ("blocked", "forbidden")


def test_classify_exit_quota_and_net_are_unknown():
    assert gc.classify_exit(429, "") == ("unknown", "quota")
    assert gc.classify_exit("?", "") == ("unknown", "net-error")


# ─── keyless check (fake opener, fake clock) ───

def test_check_exit_clean_through_fake_opener():
    ticks = [100.0]

    def _open(url, timeout):
        assert "key=" not in url  # keyless: no key material on the wire
        ticks[0] += 0.25
        return 401, ""

    rec = gc.check_exit(open_fn=_open, clock=lambda: ticks[0])
    assert rec == {"ok": True, "verdict": "clean",
                   "kind": "key-required", "latency_ms": 250}


def test_check_exit_blocked_and_unknown():
    assert gc.check_exit(
        open_fn=lambda u, t: (400, LOC_BODY.decode()))["verdict"] \
        == "blocked"

    def _boom(url, timeout):
        raise TimeoutError("timed out")

    rec = gc.check_exit(open_fn=_boom)
    assert rec["ok"] is False and rec["verdict"] == "unknown"


# ─── pure selection ───

def test_fresh_exits_google_only_and_latency_first():
    assert gc.fresh_clean_exits(_rows(), now=NOW, ttl=TTL) == [
        "s-fresh-fast", "s-fresh-slow"]


def test_fresh_exits_missing_or_corrupt_is_empty(tmp_path):
    assert gc.fresh_clean_exits(
        None, now=NOW, ttl=TTL,
        path=str(tmp_path / "absent.json")) == []


def test_select_prefers_whitelisted_available():
    assert gc.select_clean_exit(
        _rows(), ["s-fresh-slow", "s-other"],
        now=NOW, ttl=TTL) == "s-fresh-slow"
    assert gc.select_clean_exit(
        _rows(), ["s-other"], now=NOW, ttl=TTL) is None
    assert gc.select_clean_exit([], ["s-other"], now=NOW,
                                ttl=TTL) is None


def test_clean_note():
    assert gc.clean_note("s-a", ["s-a"]) == "whitelisted exit s-a"
    assert gc.clean_note("s-b", ["s-a"]) == "unlisted exit s-b"
    assert gc.clean_note("", ["s-a"]) == ""


def test_default_cache_path_is_supervisor_file():
    assert gc.default_cache_path().replace("\\", "/").endswith(
        "tools/egress/clean_cache.json")


# ─── write-back (tmp file only) ───

def test_remember_success_persists_row(tmp_path):
    from factory.precard.provider_lease_policy import load_clean_cache
    path = str(tmp_path / "clean_cache.json")
    gc.remember_success("s-1", "google", 123, now=NOW, path=path)
    rows = load_clean_cache(path)
    assert [(r["server_id"], r["provider"], r["latency_ms"])
            for r in rows] == [("s-1", "google", 123)]
    # empty server id is a no-op (file untouched)
    gc.remember_success("", "google", 1, now=NOW, path=path)
    assert len(load_clean_cache(path)) == 1


def test_verify_and_remember_clean_writes_blocked_skips(tmp_path):
    ok_path = str(tmp_path / "ok.json")
    rec = gc.verify_and_remember(
        "http://127.0.0.1:9", "s-ok",
        open_fn=lambda u, t: (401, ""), path=ok_path)
    assert rec["ok"] is True and rec["remembered"] is True
    from factory.precard.provider_lease_policy import load_clean_cache
    assert [r["server_id"] for r in load_clean_cache(ok_path)] == ["s-ok"]
    bad_path = str(tmp_path / "bad.json")
    rec = gc.verify_and_remember(
        "http://127.0.0.1:9", "s-bad",
        open_fn=lambda u, t: (400, LOC_BODY.decode()),
        path=bad_path)
    assert rec["ok"] is False and rec["remembered"] is False
    assert not os.path.exists(bad_path)


# ─── probe seam ───

def _google_probe(transport_fn, lease, reports, whitelist,
                  remember_calls=None):
    return probe_mod.probe_one(
        "google", "PROMPT", model="gemini-x", key_value="k",
        transport_fn=transport_fn, clock=lambda: 7.0, route="auto",
        lease_fn=lambda target: dict(lease),
        report_fn=lambda lid, out, prov=None: reports.append(out),
        target_fn=lambda p: "google",
        registry_fn=lambda p: {"route": "tunnel"},
        clean_fn=lambda: list(whitelist),
        remember_fn=(lambda sid, prov, ms: remember_calls.append(
            (sid, prov, ms)) if remember_calls is not None else None))


def test_probe_annotates_whitelisted_exit():
    reports = []
    rec = _google_probe(lambda k, m, t: ("ok-text", {}),
                        {"lease_id": "aa11bb22cc33", "mode": "tunnel",
                         "server_id": "srv-fake", "proxy_url": "",
                         "provider": "google", "target": "google"},
                        reports, ["srv-fake"])
    assert rec["status"] == "ok" and rec["clean"] is True
    assert rec["clean_note"] == "whitelisted exit srv-fake"
    line = probe_mod.probe_line(rec)
    assert "clean=whitelisted" in line


def test_probe_annotates_unlisted_exit():
    reports = []
    rec = _google_probe(lambda k, m, t: ("ok-text", {}),
                        {"lease_id": "aa11bb22cc33", "mode": "tunnel",
                         "server_id": "srv-other", "proxy_url": "",
                         "provider": "google", "target": "google"},
                        reports, ["srv-fake"])
    assert rec["clean"] is False
    assert "clean=unlisted" in probe_mod.probe_line(rec)


def test_probe_success_writes_back_clean_exit():
    reports, remembered = [], []
    _google_probe(lambda k, m, t: ("ok-text", {}),
                  {"lease_id": "aa11bb22cc33", "mode": "tunnel",
                   "server_id": "srv-new", "proxy_url": "",
                   "provider": "google", "target": "google"},
                  reports, [], remembered)
    assert remembered and remembered[0][0] == "srv-new"
    assert remembered[0][1] == "google"


def _http_403(body):
    return urllib.error.HTTPError(
        "https://example.invalid/", 403, "Forbidden", {}, io.BytesIO(body))


def test_probe_location_blocked_cools_own_server():
    reports = []

    def _blocked(k, m, t):
        raise _http_403(LOC_BODY)

    rec = _google_probe(
        _blocked,
        {"lease_id": "bb11cc22dd33", "mode": "tunnel",
         "server_id": "srv-dirty", "proxy_url": "",
         "provider": "google", "target": "google"},
        reports, [])
    assert rec["location_blocked"] is True
    assert rec["clean"] is False
    assert reports == ["net_err"]  # cools OUR server, rotates tunnel
    assert "blocked=location" in probe_mod.probe_line(rec)


def test_probe_plain_403_keeps_auth_meaning():
    reports = []

    def _forbidden(k, m, t):
        raise _http_403(b"forbidden")

    rec = _google_probe(
        _forbidden,
        {"lease_id": "cc11dd22ee33", "mode": "tunnel",
         "server_id": "srv-x", "proxy_url": "",
         "provider": "google", "target": "google"},
        reports, [])
    assert rec["location_blocked"] is False
    assert reports == ["auth_err"]


def test_probe_line_skips_clean_for_direct():
    line = probe_mod.probe_line({"provider": "groq", "status": "ok",
                                 "route": "direct", "egress": "direct",
                                 "clean": None, "model": "m",
                                 "latency_s": 0.5})
    assert "clean=" not in line


def test_cache_file_shape_is_secret_free(tmp_path):
    from factory.precard.provider_lease_policy import load_clean_cache
    path = str(tmp_path / "clean_cache.json")
    gc.remember_success("s-9", "google", 5, now=NOW, path=path)
    raw = json.load(open(path, encoding="utf-8"))
    assert set(raw) == {"saved_at", "entries"}
    assert set(raw["entries"][0]) == {
        "server_id", "provider", "last_ok_ts", "latency_ms"}
    assert "://" not in json.dumps(raw)  # no links/URLs persisted
