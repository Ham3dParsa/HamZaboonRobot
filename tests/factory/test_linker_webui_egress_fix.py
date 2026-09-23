"""Locked egress/cancel/wordlist fixes: route-based model tunnel, pid cancel,
polymorphic wordlist.

Hermetic: fake leases/openers/procs only — never the network, never real
children. Secrets: names only, values never asserted.
"""

import json
import os
import sys
import urllib.request as _url

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.linking import cli
from factory.linking.webui import server as webui

HTML_PATH = os.path.join(PROJECT_ROOT, "factory", "linking", "webui",
                         "index.html")

KID_APPLE = "en-apple-en-noun-AAAA1111"
KID_RUN = "en-run-en-verb-BBBB2222"

FAKE_LEASE = {"lease_id": "aa11bb22cc33", "mode": "tunnel",
              "proxy_url": "http://127.0.0.1:19999",
              "server_id": "srv-t", "provider": "openrouter",
              "target": "openrouter"}


def _keyed(monkeypatch, var):
    """One resolvable key NAME server-side (value stays in-memory)."""
    monkeypatch.setattr(webui, "_provider_key_var", lambda p: var)
    monkeypatch.setattr(webui, "_operator_key_values", lambda: {})
    import factory.precard.provider_lease_policy as _net
    monkeypatch.setattr(_net, "resolve_key",
                        lambda v: "k-test" if v == var else "")


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload)


def _header_map(req):
    return {k.lower(): v for k, v in req.header_items()}


# ─── Item 1: route-based model-list tunnel ────────────────────────────

def test_model_list_leased_openrouter_uses_tunnel_proxy(monkeypatch):
    """Leased-route OpenAI-compatible rows list through OUR proxy."""
    _keyed(monkeypatch, "OPENROUTER_API_KEY")
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "test leased"))
    leased = []

    def _fake_lease(provider, **kwargs):
        leased.append(provider)
        return dict(FAKE_LEASE), None

    monkeypatch.setattr(webui, "lease_tunnel_for_run", _fake_lease)
    seen = {}

    class _FakeOpener:
        def open(self, req, timeout=None):
            seen["url"] = req.full_url
            seen["headers"] = _header_map(req)
            return _FakeResp({"data": [{"id": "m1"}, {"id": "m2"}]})

    def _fake_opener(*handlers):
        seen["handlers"] = handlers
        return _FakeOpener()

    monkeypatch.setattr(_url, "build_opener", _fake_opener)
    models, err = webui.provider_model_list("openrouter")
    assert err is None
    assert models == ["m1", "m2"]
    assert leased == ["openrouter"]
    assert seen["url"].endswith("/models")
    assert seen["headers"].get("authorization") == "Bearer k-test"
    proxies = seen["handlers"][0].proxies
    assert proxies == {"http": FAKE_LEASE["proxy_url"],
                       "https": FAKE_LEASE["proxy_url"]}


def test_model_list_groq_flag_off_means_row_default_direct(monkeypatch):
    """Flag empty => groq row default (direct): no lease, straight fetch."""
    _keyed(monkeypatch, "GROQ_API_KEY")
    assert webui.route_for_provider("groq", tunneled=set())[0] == "direct"

    def _boom(*args, **kwargs):
        raise AssertionError("no lease on the flag-off direct route")

    monkeypatch.setattr(webui, "lease_tunnel_for_run", _boom)
    seen = {}

    def _fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return _FakeResp({"data": [{"id": "g1"}]})

    monkeypatch.setattr(_url, "urlopen", _fake_urlopen)
    models, err = webui.provider_model_list("groq", tunneled=set())
    assert err is None
    assert models == ["g1"]
    assert seen["url"].startswith("https://api.groq.com")
    assert seen["url"].endswith("/models")


def test_model_list_groq_flag_on_means_leased(monkeypatch):
    """Flag listing groq => leased: model list rides OUR tunnel proxy."""
    _keyed(monkeypatch, "GROQ_API_KEY")
    assert webui.route_for_provider("groq", tunneled={"groq"})[0] == "leased"
    leased = []

    def _fake_lease(provider, **kwargs):
        leased.append(provider)
        lease = dict(FAKE_LEASE)
        lease["provider"] = "groq"
        lease["target"] = "groq"
        return lease, None

    monkeypatch.setattr(webui, "lease_tunnel_for_run", _fake_lease)

    def _boom(req, timeout=None):
        raise AssertionError("flagged groq must never fetch direct")

    monkeypatch.setattr(_url, "urlopen", _boom)
    seen = {}

    class _FakeOpener:
        def open(self, req, timeout=None):
            seen["url"] = req.full_url
            seen["headers"] = _header_map(req)
            return _FakeResp({"data": [{"id": "g1"}]})

    def _fake_opener(*handlers):
        seen["handlers"] = handlers
        return _FakeOpener()

    monkeypatch.setattr(_url, "build_opener", _fake_opener)
    models, err = webui.provider_model_list("groq", tunneled={"groq"})
    assert err is None
    assert models == ["g1"]
    assert leased == ["groq"]
    assert seen["url"].startswith("https://api.groq.com")
    assert seen["url"].endswith("/models")
    assert seen["headers"].get("authorization") == "Bearer k-test"
    proxies = seen["handlers"][0].proxies
    assert proxies == {"http": FAKE_LEASE["proxy_url"],
                       "https": FAKE_LEASE["proxy_url"]}


def test_model_list_direct_avalai_skips_lease(monkeypatch):
    """Direct-route rows never lease and fetch straight."""
    _keyed(monkeypatch, "AVALAI_API_KEY")

    def _boom(*args, **kwargs):
        raise AssertionError("no lease on the direct route")

    monkeypatch.setattr(webui, "lease_tunnel_for_run", _boom)
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("direct", "test direct"))
    seen = {}

    def _fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return _FakeResp({"data": [{"id": "a1"}]})

    monkeypatch.setattr(_url, "urlopen", _fake_urlopen)
    models, err = webui.provider_model_list("avalai")
    assert err is None
    assert models == ["a1"]
    assert seen["url"].endswith("/models")


def test_model_list_google_leased_uses_proxy_and_remembers(monkeypatch):
    """Google keeps its leased path: proxy + key header + exit remember."""
    _keyed(monkeypatch, "GOOGLE_AI_API_KEY")
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "test leased"))
    monkeypatch.setattr(webui, "lease_tunnel_for_run",
                        lambda p, **k: (dict(FAKE_LEASE), None))
    remembered = []
    seen = {}

    class _FakeOpener:
        def open(self, req, timeout=None):
            seen["headers"] = _header_map(req)
            return _FakeResp({"models": [{"name": "models/g1"}]})

    monkeypatch.setattr(_url, "build_opener",
                        lambda *h: _FakeOpener())
    models, err = webui.provider_model_list(
        "google",
        remember_fn=lambda sid, prov, lat: remembered.append((sid, prov)))
    assert err is None
    assert models == ["g1"]
    assert seen["headers"].get("x-goog-api-key") == "k-test"
    assert remembered == [("srv-t", "google")]


# ─── Item 2: pid persistence + cancel ─────────────────────────────────

class _LiveProc:
    """Controllable child: terminate exits fast (unless stubborn)."""

    def __init__(self, pid, stubborn=False):
        import threading as _threading

        self.pid = pid
        self.stubborn = stubborn
        self.terminated = False
        self.killed = False
        self._code = None
        self._done = _threading.Event()

    def __iter__(self):
        return iter([])

    @property
    def stdout(self):
        return self

    def poll(self):
        return self._code

    def terminate(self):
        self.terminated = True
        if not self.stubborn:
            self._code = -15
            self._done.set()

    def kill(self):
        self.killed = True
        self._code = -9
        self._done.set()

    def wait(self, timeout=None):
        import subprocess as _subprocess

        if self._done.wait(timeout):
            return self._code
        raise _subprocess.TimeoutExpired("fake-child", timeout)


def _run_client(tmp_path, monkeypatch, procs):
    """Isolated app client; Popen serves the given fake procs in order."""
    monkeypatch.setattr(webui, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(webui, "PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.setattr(webui, "RUNS_DIR", str(tmp_path / "runs"))
    registry = tmp_path / "runs.json"
    registry.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(webui, "REGISTRY_PATH", str(registry))
    monkeypatch.setattr(webui, "_operator_key_values", lambda: {})
    monkeypatch.setattr(webui, "lease_tunnel_for_run",
                        lambda p: (None, None))
    import subprocess as _sub

    def _fake_popen(argv, **kwargs):
        return procs.pop(0)

    monkeypatch.setattr(_sub, "Popen", _fake_popen)
    return webui.app.test_client()


def _words_file(tmp_path, name="words.json"):
    path = tmp_path / name
    path.write_text(json.dumps([{"kind": "word", "text": "go"}]),
                    encoding="utf-8")
    return str(path)


def _create_linking_run(client, words, out="links.tsv"):
    return client.post("/api/runs", json={"flow": "linking",
                                          "provider": "avalai",
                                          "sample": words, "out": out})


def test_create_run_persists_pid(tmp_path, monkeypatch):
    """Each run record carries its child pid durably."""
    proc = _LiveProc(pid=4242)
    client = _run_client(tmp_path, monkeypatch, [proc])
    try:
        resp = _create_linking_run(client, _words_file(tmp_path))
        assert resp.status_code == 201
        rec = resp.get_json()["run"]
        assert rec["pid"] == 4242
        listed = client.get("/api/runs").get_json()["runs"]
        assert listed[0]["pid"] == 4242
    finally:
        proc.terminate()
        webui._procs.pop(resp.get_json()["run"]["id"], None)


def test_cancel_stops_child_by_pid_and_marks_failed(tmp_path, monkeypatch):
    """Cancel signals THAT child only; record goes failed/operator-stopped."""
    first, second = _LiveProc(pid=1111), _LiveProc(pid=2222)
    client = _run_client(tmp_path, monkeypatch, [first, second])
    try:
        r1 = _create_linking_run(client, _words_file(tmp_path),
                                 out="a.tsv").get_json()["run"]
        r2 = _create_linking_run(client, _words_file(tmp_path),
                                 out="b.tsv").get_json()["run"]
        resp = client.post("/api/runs/%s/cancel" % r1["id"])
        assert resp.status_code == 200
        rec = resp.get_json()["run"]
        assert rec["status"] == "failed"
        assert "operator-stopped" in (rec["stop_reason"] or "")
        assert "1111" in (rec["stop_reason"] or "")
        assert first.terminated is True
        assert first.killed is False  # terminate sufficed: no force-kill
        assert second.terminated is False and second.killed is False
        assert second.poll() is None  # still running, untouched
        kept = client.get("/api/runs/%s" % r1["id"]).get_json()["run"]
        assert kept["status"] == "failed"
        live = client.get("/api/runs").get_json()["runs"]
        assert [r for r in live if r["id"] == r2["id"]][0]["status"] \
            == "running"
    finally:
        second.terminate()
        webui._procs.pop(r1["id"], None)
        webui._procs.pop(r2["id"], None)


def test_cancel_force_kills_stubborn_child(tmp_path, monkeypatch):
    """A child ignoring terminate gets force-killed after the grace."""
    monkeypatch.setattr(webui, "CANCEL_GRACE_SECONDS", 0.2)
    proc = _LiveProc(pid=5555, stubborn=True)
    client = _run_client(tmp_path, monkeypatch, [proc])
    try:
        rid = _create_linking_run(client, _words_file(tmp_path),
                                  out="e.tsv").get_json()["run"]["id"]
        resp = client.post("/api/runs/%s/cancel" % rid)
        assert resp.status_code == 200
        rec = resp.get_json()["run"]
        assert rec["status"] == "failed"
        assert rec["exit_code"] == -9
        assert "force-killed" in (rec["stop_reason"] or "")
        assert proc.terminated is True and proc.killed is True
    finally:
        webui._procs.pop(rid, None)


def test_cancel_unknown_404_and_terminal_409(tmp_path, monkeypatch):
    """Unknown runs 404; re-cancelling a terminal run 409s with the record."""
    proc = _LiveProc(pid=3333)
    client = _run_client(tmp_path, monkeypatch, [proc])
    assert client.post("/api/runs/nope/cancel").status_code == 404
    try:
        rid = _create_linking_run(client, _words_file(tmp_path),
                                  out="c.tsv").get_json()["run"]["id"]
        assert client.post("/api/runs/%s/cancel" % rid).status_code == 200
        resp = client.post("/api/runs/%s/cancel" % rid)
        assert resp.status_code == 409
        assert resp.get_json()["run"]["status"] == "failed"
    finally:
        proc.terminate()
        webui._procs.pop(rid, None)


def test_cancel_pid_mismatch_refuses_without_signalling(tmp_path,
                                                        monkeypatch):
    """Live pid != recorded pid: refuse, never signal the wrong process."""
    proc = _LiveProc(pid=2222)
    client = _run_client(tmp_path, monkeypatch, [proc])
    try:
        rid = _create_linking_run(client, _words_file(tmp_path),
                                  out="d.tsv").get_json()["run"]["id"]
        records = webui._load_registry_migrated()
        webui._find_record(records, rid)["pid"] = 1111
        webui._save_registry(records)
        resp = client.post("/api/runs/%s/cancel" % rid)
        assert resp.status_code == 409
        assert proc.terminated is False and proc.killed is False
        kept = client.get("/api/runs/%s" % rid).get_json()["run"]
        assert kept["status"] == "running"
    finally:
        proc.terminate()
        webui._procs.pop(rid, None)


def test_cancel_bare_pid_verified_match_signals(tmp_path, monkeypatch):
    """Restarted server + matching fingerprint: the bare pid is signalled."""
    monkeypatch.setattr(webui, "_pid_identity",
                        lambda pid: (1111.0, "spawn-probe"))
    proc = _LiveProc(pid=4242)
    client = _run_client(tmp_path, monkeypatch, [proc])
    try:
        rec = _create_linking_run(client, _words_file(tmp_path),
                                  out="f.tsv").get_json()["run"]
        rid = rec["id"]
        assert rec["pid"] == 4242
        assert rec["pid_create_time"] == 1111.0
        marker = rec["pid_marker"]
        assert marker and marker.endswith("f.tsv")
        # Simulate a restart: the live handle is gone, the child runs on.
        webui._procs.pop(rid, None)
        monkeypatch.setattr(
            webui, "_pid_identity",
            lambda pid: (1111.0, "python -m factory.linking.cli link "
                                 "--out %s" % marker))
        calls = []

        def _fake_term(proc_, pid_, grace_seconds=None, **kwargs):
            calls.append((proc_, pid_))
            return None, ""

        monkeypatch.setattr(webui, "_terminate_child", _fake_term)
        resp = client.post("/api/runs/%s/cancel" % rid)
        assert resp.status_code == 200
        assert calls == [(None, 4242)]  # bare pid, verified, signalled
        done = resp.get_json()["run"]
        assert done["status"] == "failed"
        assert "operator-stopped" in (done["stop_reason"] or "")
        assert "4242" in (done["stop_reason"] or "")
    finally:
        proc.terminate()
        webui._procs.pop(rid, None)


def test_cancel_bare_pid_mismatch_refuses_without_signalling(
        tmp_path, monkeypatch):
    """Restarted server + reused pid (wrong cmdline or start time): 409."""
    monkeypatch.setattr(webui, "_pid_identity",
                        lambda pid: (2222.0, "spawn-probe"))
    proc = _LiveProc(pid=7777)
    client = _run_client(tmp_path, monkeypatch, [proc])
    try:
        rid = _create_linking_run(client, _words_file(tmp_path),
                                  out="g.tsv").get_json()["run"]["id"]
        stored = webui._find_record(webui._load_registry_migrated(), rid)
        marker = stored["pid_marker"]
        assert stored["pid_create_time"] == 2222.0 and marker
        webui._procs.pop(rid, None)  # restarted server: bare-pid path
        calls = []

        def _fake_term(proc_, pid_, grace_seconds=None, **kwargs):
            calls.append((proc_, pid_))
            return None, ""

        monkeypatch.setattr(webui, "_terminate_child", _fake_term)
        # Same start time, unrelated command line (pid reuse).
        monkeypatch.setattr(webui, "_pid_identity",
                            lambda pid: (2222.0, "python unrelated-daemon"))
        resp = client.post("/api/runs/%s/cancel" % rid)
        assert resp.status_code == 409
        assert "unknown target" in resp.get_json()["error"]
        # Same command line, different start time (pid reuse, later boot).
        monkeypatch.setattr(
            webui, "_pid_identity",
            lambda pid: (9999.0, "python -m factory.linking.cli link "
                                 "--out %s" % marker))
        resp = client.post("/api/runs/%s/cancel" % rid)
        assert resp.status_code == 409
        assert "unknown target" in resp.get_json()["error"]
        assert calls == []  # never signalled the stranger
        kept = client.get("/api/runs/%s" % rid).get_json()["run"]
        assert kept["status"] == "running"
    finally:
        proc.terminate()
        webui._procs.pop(rid, None)


def test_cancel_bare_pid_unverifiable_refuses_without_signalling(
        tmp_path, monkeypatch):
    """Pre-fix record without a fingerprint: bare-pid cancel refuses."""
    proc = _LiveProc(pid=8888)
    client = _run_client(tmp_path, monkeypatch, [proc])
    try:
        rid = _create_linking_run(client, _words_file(tmp_path),
                                  out="h.tsv").get_json()["run"]["id"]
        records = webui._load_registry_migrated()
        old = webui._find_record(records, rid)
        old.pop("pid_create_time", None)  # pre-fix record shape
        old.pop("pid_marker", None)
        webui._save_registry(records)
        webui._procs.pop(rid, None)  # restarted server: bare-pid path
        calls = []

        def _fake_term(proc_, pid_, grace_seconds=None, **kwargs):
            calls.append((proc_, pid_))
            return None, ""

        monkeypatch.setattr(webui, "_terminate_child", _fake_term)
        monkeypatch.setattr(webui, "_pid_identity",
                            lambda pid: (3333.0, "python something-live"))
        resp = client.post("/api/runs/%s/cancel" % rid)
        assert resp.status_code == 409
        assert "unknown target" in resp.get_json()["error"]
        assert calls == []
        kept = client.get("/api/runs/%s" % rid).get_json()["run"]
        assert kept["status"] == "running"
    finally:
        proc.terminate()
        webui._procs.pop(rid, None)


def test_cancel_route_registered_and_html_wires_stop_button():
    """Route exists; the red stop button sits by the progress indicator."""
    rules = sorted(r.rule for r in webui.app.url_map.iter_rules())
    assert "/api/runs/<run_id>/cancel" in rules
    with open(HTML_PATH, encoding="utf-8") as handle:
        text = handle.read()
    assert 'id="btn-stop-run"' in text
    assert "solid-danger" in text
    assert 'id="stop-status"' in text
    label_at = text.index('id="watch-progress-label"')
    stop_at = text.index('id="btn-stop-run"')
    cli_at = text.index('id="watch-cli"')
    assert label_at < stop_at < cli_at  # next to progress, before receipt
    assert "stopSelectedRun" in text
    assert "/cancel" in text and "'POST'" in text
    assert "$('btn-stop-run').addEventListener" in text


# ─── Item 3: polymorphic wordlist ─────────────────────────────────────

def test_read_wordlist_polymorphic(tmp_path):
    """{ lines extract text/lemma (screening outputs); others read direct."""
    path = tmp_path / "mixed.txt"
    path.write_text("\n".join([
        "apple",
        '{"text": "run"}',
        '{"lemma": "book", "sense": {"sense_id": "book#0"}}',
        '{"text": "  spaced  "}',
        "{oops",
        "[1, 2]",
        '{"nope": 1}',
        "",
        "# comment",
        "take off",
    ]) + "\n", encoding="utf-8")
    assert cli.read_wordlist(str(path)) == [
        "apple", "run", "book", "spaced", "[1, 2]", "take off"]


def test_read_wordlist_plain_regression(tmp_path):
    """Plain text files read exactly as before."""
    path = tmp_path / "plain.txt"
    path.write_text("apple\nrun\n\n# note\n", encoding="utf-8")
    assert cli.read_wordlist(str(path)) == ["apple", "run"]


def test_validate_sample_file_accepts_plain_wordlist(tmp_path):
    """Plain text word lists validate (gold 0) instead of corrupt-JSON."""
    path = tmp_path / "words.txt"
    path.write_text("apple\nrun\n", encoding="utf-8")
    ok, err, info = webui.validate_sample_file(str(path))
    assert ok is True and err == ""
    assert info == {"rows": 2, "gold": 0}


def test_validate_sample_file_accepts_screening_jsonl(tmp_path):
    """Screening JSONL lines validate via lemma extraction."""
    path = tmp_path / "screened.jsonl"
    path.write_text("\n".join([
        '{"lemma": "run", "sense": {"sense_id": "run#0"}}',
        '{"text": "apple"}',
    ]) + "\n", encoding="utf-8")
    ok, err, info = webui.validate_sample_file(str(path))
    assert ok is True and err == ""
    assert info == {"rows": 2, "gold": 0}


def test_validate_sample_file_still_rejects_corrupt(tmp_path):
    """Unparseable single-object lines keep the corrupt-JSON refusal."""
    bad = tmp_path / "bad.txt"
    bad.write_text("{oops", encoding="utf-8")
    ok, err, _ = webui.validate_sample_file(str(bad))
    assert ok is False and "خوانا نیست" in err


def test_link_screening_wordlist_end_to_end(tmp_path, capsys):
    """Screening output as --words ends the zero-row failure."""
    import csv

    table = tmp_path / "mini.tsv"
    with open(table, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=cli.TABLE_FIELDNAMES,
                                delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows([
            {"kaikki_sense_id": KID_APPLE, "wordnet_sensekey": "a%1:00::",
             "method": "LINK:2-sig", "evidence": "Sa:j=0.5",
             "provenance": "unit-test"},
            {"kaikki_sense_id": KID_RUN, "wordnet_sensekey": "r%2:00::",
             "method": "twin-pending", "evidence": "t",
             "provenance": "unit-test"},
        ])
    words = tmp_path / "screened.jsonl"
    words.write_text("\n".join([
        '{"lemma": "apple", "sense": {"sense_id": "x#0"}}',
        '{"text": "%s"}' % KID_RUN,
    ]) + "\n", encoding="utf-8")
    out = str(tmp_path / "subset.tsv")
    rc = cli.main(["link", "--words", str(words), "--out", out,
                   "--table", str(table), "--progress"])
    assert rc == 0
    with open(out, encoding="utf-8", newline="") as handle:
        kept = list(csv.DictReader(handle, delimiter="\t"))
    assert {r["kaikki_sense_id"] for r in kept} == {KID_APPLE, KID_RUN}
    assert "kept=2" in capsys.readouterr().err


# ─── Warning 1: stale-handle race ───────────────────────────────────

class _ExitedProc:
    """Handle whose child already reaped (poll non-None before signal)."""

    pid = 9999

    def poll(self):
        return 0

    def terminate(self):
        raise AssertionError("exited handle must never be signalled")

    def kill(self):
        raise AssertionError("exited handle must never be signalled")

    def wait(self, timeout=None):
        raise AssertionError("exited handle must never be waited on")


def test_terminate_child_skips_signalling_when_already_exited():
    """Poll-first: an already-exited handle returns, never signals."""
    code, note = webui._terminate_child(_ExitedProc(), 9999)
    assert code == 0
    assert "already finished" in note


def test_terminate_child_reverifies_bare_pid_before_kill(
        tmp_path, monkeypatch):
    """TOCTOU: pid reused between lock and signal is never signalled."""
    monkeypatch.setattr(webui, "_pid_identity",
                        lambda pid: (1111.0, "spawn-probe"))
    proc = _LiveProc(pid=4242)
    client = _run_client(tmp_path, monkeypatch, [proc])
    try:
        rid = _create_linking_run(client, _words_file(tmp_path),
                                  out="t.tsv").get_json()["run"]["id"]
        webui._procs.pop(rid, None)  # restarted server: bare-pid path
        marker = webui._find_record(
            webui._load_registry_migrated(), rid)["pid_marker"]
        calls = []

        def _flipping_identity(pid):
            calls.append(pid)
            if len(calls) == 1:
                return (1111.0, "python -m factory.linking.cli link "
                                "--out %s" % marker)  # lock-time: match
            return (1111.0, "python unrelated-daemon")  # signal-time: reuse

        monkeypatch.setattr(webui, "_pid_identity", _flipping_identity)
        import os as _os
        signalled = []
        monkeypatch.setattr(_os, "kill",
                            lambda pid, sig: signalled.append((pid, sig)))
        resp = client.post("/api/runs/%s/cancel" % rid)
        assert resp.status_code == 409
        assert "unknown target" in resp.get_json()["error"]
        assert signalled == []  # re-verify refused before any kill
        kept = client.get("/api/runs/%s" % rid).get_json()["run"]
        assert kept["status"] == "running"
    finally:
        proc.terminate()
        webui._procs.pop(rid, None)


# ─── Warning 2: grace-window misreport ──────────────────────────────

class _NaturalFinishProc(_LiveProc):
    """Child finishing naturally (exit 0) exactly at the signal."""

    def terminate(self):
        self.terminated = True
        self._code = 0
        self._done.set()


def test_cancel_natural_zero_exit_returns_already_finished(
        tmp_path, monkeypatch):
    """Zero-exit during grace: 409 already_finished, done never cancelled."""
    proc = _NaturalFinishProc(pid=6666)
    client = _run_client(tmp_path, monkeypatch, [proc])
    try:
        rid = _create_linking_run(client, _words_file(tmp_path),
                                  out="n.tsv").get_json()["run"]["id"]
        resp = client.post("/api/runs/%s/cancel" % rid)
        assert resp.status_code == 409
        body = resp.get_json()
        assert body.get("already_finished") is True
        assert "already_finished" in body["error"]
        assert "already finished" in body["error"]
        rec = body["run"]
        assert rec["status"] == "done"
        assert rec["exit_code"] == 0
        assert not rec.get("stop_reason")  # finished, never cancelled
        kept = client.get("/api/runs/%s" % rid).get_json()["run"]
        assert kept["status"] == "done"
    finally:
        webui._procs.pop(rid, None)


def test_cancel_finished_ui_alignment():
    """Stop button + status line show finished as finished, never cancelled."""
    with open(HTML_PATH, encoding="utf-8") as handle:
        text = handle.read()
    assert "already_finished" in text  # cancel path branches on the shape
    assert "اجرا به پایان رسیده است." in text  # finished wording, not stopped
    assert "btn.disabled = !live" in text  # button dead unless running


# ─── Warning 3: proven-exit write-back for every leased route ───────

def _leased_openai_models(monkeypatch, provider, lease_provider):
    remembered = []
    seen = {}

    class _FakeOpener:
        def open(self, req, timeout=None):
            seen["url"] = req.full_url
            return _FakeResp({"data": [{"id": "m1"}]})

    monkeypatch.setattr(_url, "build_opener", lambda *h: _FakeOpener())
    models, err = webui.provider_model_list(
        provider,
        remember_fn=lambda sid, prov, lat: remembered.append((sid, prov)))
    return models, err, remembered


def test_model_list_leased_openrouter_remembers(monkeypatch):
    """Leased openrouter success warms its own provider-scoped cache."""
    _keyed(monkeypatch, "OPENROUTER_API_KEY")
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "test leased"))
    monkeypatch.setattr(webui, "lease_tunnel_for_run",
                        lambda p, **k: (dict(FAKE_LEASE), None))
    models, err, remembered = _leased_openai_models(
        monkeypatch, "openrouter", "openrouter")
    assert err is None
    assert models == ["m1"]
    assert remembered == [("srv-t", "openrouter")]


def test_model_list_leased_groq_remembers(monkeypatch):
    """Leased groq success warms its own provider-scoped cache."""
    _keyed(monkeypatch, "GROQ_API_KEY")
    monkeypatch.setattr(webui, "route_for_provider",
                        lambda p, **k: ("leased", "test leased"))
    lease = dict(FAKE_LEASE)
    lease["provider"] = "groq"
    lease["target"] = "groq"
    monkeypatch.setattr(webui, "lease_tunnel_for_run",
                        lambda p, **k: (lease, None))
    models, err, remembered = _leased_openai_models(
        monkeypatch, "groq", "groq")
    assert err is None
    assert models == ["m1"]
    assert remembered == [("srv-t", "groq")]
