"""Live browser proof: REAL mechanical run -> deferred handoff (no mocks).

Drives REAL Chromium against a REAL console server subprocess (own
isolated data root + fixtures, alternate port, pid-targeted stop).
No model is ever called: the mechanical pass is offline CPU, and the
handoff stops at the arbiter tab note (starting the arbiter run would
need a live provider). Batch guard uses the REAL /api/batches store.

Flow: tab 1 (index 1) runs mechanical over 12 senses -> counts show
2 approved / 10 deferred -> log buffer non-empty -> handoff button
enabled -> click -> tab 2 (index 2) shows the deferred note -> issue
a real batch -> tab 3 (index 3) disables the issue button with the
gentle «یک بسته فعال در انتظار است» notice (server 400 stays backstop).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SERVER_PATH = os.path.join(
    PROJECT_ROOT, "factory", "webui", "server.py")


def _free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _wait_ready(base, timeout=30):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    base + "/api/engine_info", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception as exc:
            last = exc
        time.sleep(0.5)
    raise AssertionError(
        "live console never became ready at %s (%r)" % (base, last))


def _write_fixtures(tmpdir):
    """12 screened senses + vendor table with 2 LINK rows + 1 short."""
    screened_path = os.path.join(tmpdir, "screened.jsonl")
    senses = [
        ("alpha", "alpha#1", "en-alpha-en-verb-A1",
         "move fast on foot quickly across ground"),
        ("beta", "beta#1", "en-beta-en-verb-B1",
         "carry heavy weight forward daily with care"),
        ("gamma", "gamma#1", "en-gamma-en-verb-G1", "An error."),
    ]
    for num in range(4, 13):
        senses.append(("w%d" % num, "w%d#1" % num,
                       "en-w%d-en-verb-X%d" % (num, num),
                       "some ordinary sense gloss number %d here" % num))
    with open(screened_path, "w", encoding="utf-8") as handle:
        for lemma, short, full, gloss in senses:
            handle.write(json.dumps({
                "lemma": lemma, "sense": {
                    "sense_id": short, "id": full,
                    "glosses": [gloss],
                    "examples": [{"text": "example %s" % short}],
                    "tags": []}}, ensure_ascii=False) + "\n")
    table_path = os.path.join(tmpdir, "table.tsv")
    with open(table_path, "w", encoding="utf-8") as handle:
        handle.write("kaikki_sense_id\twordnet_sensekey\tmethod\t"
                     "evidence\tprovenance\n")
        handle.write("en-alpha-en-verb-A1\talpha%2:38:00::\tLINK:2-sig\t"
                     "Sa:j=0.40+Sb:fast\trules:v0\n")
        handle.write("en-beta-en-verb-B1\tbeta%2:33:00::\tLINK:2-sig\t"
                     "Sa:j=0.42+Sb:heavy\trules:v0\n")
        handle.write("en-gamma-en-verb-G1\tgamma%2:38:01::\tJUDGE-PENDING\t"
                     "Sa:j=0.20\trules:v0\n")
    return screened_path, table_path


@pytest.fixture(scope="module")
def mech_console(tmp_path_factory):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        pytest.skip("playwright not installed: %s" % exc)
    tmpdir = str(tmp_path_factory.mktemp("mech-live"))
    screened, table = _write_fixtures(tmpdir)
    data_root = os.path.join(tmpdir, "data")
    os.makedirs(data_root)
    port = _free_port()
    assert port != 5561, "must run on an alternate port, never the default"
    env = dict(os.environ)
    env["HAMZABAN_DATA_ROOT"] = data_root
    env["HAMZABAN_SCREENED_PATH"] = screened
    env["HAMZABAN_LINK_TABLE"] = table
    log_path = os.path.join(tmpdir, "server.log")
    log_handle = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, SERVER_PATH,
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=PROJECT_ROOT, env=env,
        stdout=log_handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, close_fds=True)
    base = "http://127.0.0.1:%d" % port
    try:
        _wait_ready(base)
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as exc:
                pytest.skip("chromium cannot launch here: %s" % exc)
            try:
                yield {"base": base, "browser": browser,
                       "tmpdir": tmpdir}
            finally:
                browser.close()
    finally:
        log_handle.close()
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:
            pass


def _api(base, method, path, payload=None):
    import urllib.error as _errors

    data = (json.dumps(payload).encode("utf-8")
            if payload is not None else None)
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except _errors.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _new_page(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    return page, errors, crashes


def _odd(errors):
    return [e for e in errors if not (
        "Failed to load resource" in e and (" 502" in e or " 503" in e))]


def test_mechanical_run_handoff_and_batch_guard_live_browser(mech_console):
    browser, base = mech_console["browser"], mech_console["base"]
    page, errors, crashes = _new_page(browser)
    batch_id = ""
    try:
        page.goto(base + "/")
        page.click('#view-linking .cockpit-tabs '
                   '.tab-link[data-tab-index="1"]')
        page.wait_for_selector("#mechanical-run-card", timeout=15000)
        # module wiring lands async: click until the run provably starts
        # (log streams) or visibly fails (error slot), bounded retries.
        started = False
        for _attempt in range(6):
            page.click("#btn-mechanical-run")
            try:
                page.wait_for_function(
                    "document.getElementById('mechanical-log').textContent.length > 0"
                    " || document.getElementById('mechanical-err').textContent.trim() !== ''",
                    timeout=5000)
                started = True
                break
            except Exception:
                continue
        assert started, "mechanical run never started: " + page.inner_text(
            "#mechanical-err")
        assert page.inner_text("#mechanical-err").strip() == "", \
            page.inner_text("#mechanical-err")
        page.wait_for_function(
            "document.getElementById('mechanical-run-state')"
            ".textContent.includes('بیکار')",
            timeout=30000)
        page.wait_for_function(
            "document.getElementById('mechanical-counts')"
            ".textContent.includes('تأیید')",
            timeout=15000)
        counts = page.inner_text("#mechanical-counts")
        assert "۲" in counts, counts  # 2 approved (alpha, beta)
        assert "۱۰" in counts, counts  # 10 deferred
        # log buffer resolved slow-vs-hung: senses streamed through it
        page.wait_for_function(
            "document.getElementById('mechanical-log')"
            ".textContent.includes('alpha#1')",
            timeout=15000)
        assert "started" in page.inner_text("#mechanical-log")
        page.wait_for_function(
            "!document.getElementById('btn-mechanical-handoff').disabled",
            timeout=15000)
        page.screenshot(path=os.path.join(
            mech_console["tmpdir"], "shot-mech-tab2-desktop.png"))
        # handoff lands on the arbiter tab with the deferred note
        page.click("#btn-mechanical-handoff")
        page.wait_for_function(
            "document.querySelector('#view-linking .cockpit-tabs "
            ".tab-link.active').getAttribute('data-tab-index') === '2'",
            timeout=5000)
        page.wait_for_function(
            "document.getElementById('arbiter-handoff-note')"
            ".textContent.includes('۱۰')",
            timeout=5000)
        note = page.inner_text("#arbiter-handoff-note")
        assert "گزینش مکانیکی" in note, note
        page.screenshot(path=os.path.join(
            mech_console["tmpdir"], "shot-mech-tab3-handoff.png"))
        # real active batch -> tab 3 guard: disabled + gentle notice
        status, body = _api(base, "POST", "/api/batches", {"size": 10})
        assert status == 200, body
        batch_id = body["batch"]["id"]
        page.click('#view-linking .cockpit-tabs '
                   '.tab-link[data-tab-index="3"]')
        page.wait_for_function(
            "document.getElementById('btn-issue-batch').disabled === true",
            timeout=10000)
        guard = page.inner_text("#batch-active-note")
        assert "یک بسته فعال در انتظار است" in guard, guard
        # server error path stays as backstop, never the primary signal
        status, _body = _api(base, "POST", "/api/batches", {"size": 10})
        assert status == 400
        assert not crashes, crashes
        assert not _odd(errors), _odd(errors)
    finally:
        page.close()
        if batch_id:
            try:
                _api(base, "POST",
                     "/api/batches/%s/cancel" % batch_id, {})
            except Exception:
                pass
