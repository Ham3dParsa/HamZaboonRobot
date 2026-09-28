"""T11 — screening intake validation + collision + upload (UX-3/4/5/10, OQ-2/5/6).

Locked rules:
- ``_screening_parse_words`` splits multiline+comma, cap 2500 FAIL-FAST
  (``_ScreeningOverCap`` with total + excess, never a silent trim);
  2501 words -> POST 400 + excess count, zero spawn.
- Output names sanitize fa+lat+digits+``-``+``_`` -> ``-`` (server +
  client + live preview).
- Named runs collide NEVER silently: ``GET /api/screening/exists``
  preflight + ``collision_dialog`` (4 options: auto ``_v2`` /
  overwrite-with-confirm / inline rename / full cancel) BEFORE spawn;
  the POST re-checks (409 ``{collision: true}``) so a skipped dialog
  can never overwrite.
- ``POST /api/files/upload`` allowlisted-dirs-only (outside -> 400,
  same-name -> 409); uploads re-list and re-pick from the dialog.

Hermetic: tmp data root, Flask test client with fake children.
Live IT-T11-01..04: real Chromium + real console server (only the
screening spawn/exists endpoints stubbed at the HTTP layer where
noted); screenshots to ``.opencode/plans/factory/shots/``.
No secrets anywhere.
"""

import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from factory.webui import server as webui

SHOTS_DIR = os.path.join(
    PROJECT_ROOT, ".opencode", "plans", "factory", "shots")

FA_TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _norm_digits(text):
    return str(text or "").translate(FA_TO_ASCII)


def _words(n):
    """n distinct valid lemmas (letter-only, server regex-safe)."""
    out = []
    for i in range(n):
        out.append("%c%c%c" % (97 + (i // 676) % 26,
                               97 + (i // 26) % 26,
                               97 + i % 26))
    return out


@pytest.fixture()
def _idle_screening():
    def _reset():
        with webui._SCREENING_LOCK:
            webui._SCREENING.update(
                proc=None, pid=None, status="idle", words=[],
                out_dir="", started=None, started_iso=None,
                exit_code=None, log=[], manifest=None, note="")

    _reset()
    yield
    _reset()


class _FakeProc:
    pid = 4242

    def __init__(self, lines=(), code=0):
        self.stdout = iter(list(lines))
        self._code = code
        self._done = threading.Event()
        self._done.set()

    def poll(self):
        return self._code if self._done.is_set() else None

    def wait(self, timeout=None):
        return self._code


@pytest.fixture()
def _roots(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "data_root", lambda: str(tmp_path))
    monkeypatch.setenv("HAMZABAN_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(webui, "_browse_roots",
                        lambda: [{"path": str(tmp_path),
                                  "label": "data root"}])
    return tmp_path


def _client():
    return webui.app.test_client()


# ── parsing: multiline split + 2500 fail-fast ──

def test_parse_words_multiline_and_comma():
    assert webui._screening_parse_words("run\nlight,take\nget") == [
        "run", "light", "take", "get"]


def test_parse_words_over_cap_raises_with_excess():
    with pytest.raises(webui._ScreeningOverCap) as info:
        webui._screening_parse_words(",".join(_words(2501)))
    assert info.value.total == 2501
    assert info.value.excess == 1
    assert info.value.limit == 2500


def test_run_over_cap_400_with_excess_zero_spawn(
        _roots, _idle_screening, monkeypatch):
    """2501 words -> 400 + excess 1, no child spawned, still idle."""
    import subprocess as _sub

    def _no_spawn(*args, **kwargs):
        raise AssertionError("must not spawn over cap")

    monkeypatch.setattr(_sub, "Popen", _no_spawn)
    client = _client()
    resp = client.post("/api/screening/run",
                       json={"words": ",".join(_words(2501))})
    assert resp.status_code == 400, resp.get_json()
    body = resp.get_json()
    assert body["over_cap"] is True
    assert body["excess"] == 1
    assert body["total"] == 2501
    assert client.get("/api/screening/status").get_json(
    )["screening"]["status"] == "idle"


def test_run_at_cap_spawns(_roots, _idle_screening, monkeypatch):
    """Exactly 2500 words passes validation (201 with a fake child)."""
    import subprocess as _sub

    monkeypatch.setattr(_sub, "Popen", lambda argv, **kw: _FakeProc())
    client = _client()
    resp = client.post("/api/screening/run",
                       json={"words": ",".join(_words(2500)),
                             "reprocess_duplicates": True})
    assert resp.status_code == 201, resp.get_json()


# ── name sanitize: fa+lat+digits+-+_ ──

def test_clean_out_name_keeps_fa_lat_digits():
    assert webui._screening_clean_out_name("Demo X!") == "demo-x"
    assert webui._screening_clean_out_name("a_b-c") == "a_b-c"
    assert webui._screening_clean_out_name("آزمون ۱۲۳!") == "آزمون-۱۲۳"
    assert webui._screening_clean_out_name("  ///  ") == ""


# ── collision: never silent ──

def _seed_named_run(root, name="demo"):
    base = os.path.join(str(root), "proof-linker", "screened", name)
    os.makedirs(base, exist_ok=True)
    marker = os.path.join(base, "screened.manifest.json")
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write('{"kept_total": 1}')
    return base, marker


def test_exists_preflight_reports_collision(_roots):
    base, _ = _seed_named_run(_roots)
    client = _client()
    hit = client.get("/api/screening/exists",
                     query_string={"out_name": "demo"}).get_json()
    assert hit["exists"] is True
    assert hit["out_name"] == "demo"
    assert os.path.abspath(hit["path"]) == os.path.abspath(base)
    miss = client.get("/api/screening/exists",
                      query_string={"out_name": "demo-fresh"}).get_json()
    assert miss["exists"] is False
    assert client.get("/api/screening/exists",
                      query_string={"out_name": "///"}).status_code == 400


def test_named_rerun_without_choice_is_409(
        _roots, _idle_screening, monkeypatch):
    """Second same-name run with no dialog choice -> 409, zero spawn."""
    import subprocess as _sub

    _seed_named_run(_roots)
    monkeypatch.setattr(
        _sub, "Popen",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not spawn on collision")))
    client = _client()
    resp = client.post("/api/screening/run",
                       json={"words": "run", "out_name": "demo"})
    assert resp.status_code == 409, resp.get_json()
    assert resp.get_json()["collision"] is True


def test_collision_auto_overwrite_rename(_roots, _idle_screening, monkeypatch):
    """Each dialog option -> correct outcome; first output intact."""
    import subprocess as _sub

    base, marker = _seed_named_run(_roots)
    seen = {}
    monkeypatch.setattr(
        _sub, "Popen",
        lambda argv, **kw: seen.setdefault("argv", list(argv))
        or _FakeProc())
    client = _client()

    # auto -> demo_v2, marker intact
    resp = client.post("/api/screening/run",
                       json={"words": "run", "out_name": "demo",
                             "collision": "auto",
                             "reprocess_duplicates": True})
    assert resp.status_code == 201, resp.get_json()
    argv = seen["argv"]
    out_dir = argv[argv.index("--out-dir") + 1]
    assert os.path.abspath(out_dir) == os.path.abspath(base + "_v2")
    assert open(marker, encoding="utf-8").read() == '{"kept_total": 1}'
    with webui._SCREENING_LOCK:
        webui._SCREENING.update(proc=None, status="idle", started=None,
                                started_iso=None)

    # rename -> demo-fresh, marker intact
    seen.clear()
    resp = client.post("/api/screening/run",
                       json={"words": "run", "out_name": "demo-fresh",
                             "reprocess_duplicates": True})
    assert resp.status_code == 201, resp.get_json()
    argv = seen["argv"]
    out_dir = argv[argv.index("--out-dir") + 1]
    assert os.path.abspath(out_dir) == os.path.abspath(
        os.path.join(str(_roots), "proof-linker", "screened",
                     "demo-fresh"))
    assert open(marker, encoding="utf-8").read() == '{"kept_total": 1}'
    with webui._SCREENING_LOCK:
        webui._SCREENING.update(proc=None, status="idle", started=None,
                                started_iso=None)

    # overwrite (dialog-confirmed) -> same dir spawns
    seen.clear()
    resp = client.post("/api/screening/run",
                       json={"words": "run", "out_name": "demo",
                             "collision": "overwrite",
                             "reprocess_duplicates": True})
    assert resp.status_code == 201, resp.get_json()
    argv = seen["argv"]
    assert os.path.abspath(
        argv[argv.index("--out-dir") + 1]) == os.path.abspath(base)


# ── upload: allowlisted dirs only, re-selectable ──

def test_upload_roundtrip_and_reselectable(_roots):
    client = _client()
    payload = "alpha\nbeta\ngamma\n".encode("utf-8")
    resp = client.post("/api/files/upload",
                       data={"dir": str(_roots),
                             "file": (io.BytesIO(payload), "t11-words.txt")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["name"] == "t11-words.txt"
    assert open(body["path"], "rb").read() == payload
    # Re-listable (re-selectable from the dialog listing).
    ok, error, listed = webui._list_dir(str(_roots))
    assert ok, error
    assert "t11-words.txt" in [e["name"] for e in listed["entries"]]
    # Same name again -> 409, never a silent overwrite.
    resp = client.post("/api/files/upload",
                       data={"dir": str(_roots),
                             "file": (io.BytesIO(payload), "t11-words.txt")},
                       content_type="multipart/form-data")
    assert resp.status_code == 409


def test_upload_outside_allowlist_rejected(_roots, tmp_path):
    client = _client()
    outside = tmp_path.parent / "t11-outside-allowlist"
    outside.mkdir(exist_ok=True)
    resp = client.post("/api/files/upload",
                       data={"dir": str(outside),
                             "file": (io.BytesIO(b"x\n"), "evil.txt")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400, resp.get_json()
    assert not (outside / "evil.txt").exists()


# ── live browser IT-T11-01..04 ──

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


@pytest.fixture(scope="module")
def live_console(tmp_path_factory):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        pytest.skip("playwright not installed: %s" % exc)
    tmpdir = str(tmp_path_factory.mktemp("t11-live"))
    port = _free_port()
    assert port != 5561, "must run on an alternate port, never the default"
    env = dict(os.environ)
    log_path = os.path.join(tmpdir, "server.log")
    log_handle = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(PROJECT_ROOT, "factory", "webui",
                                      "server.py"),
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
                       "tmpdir": tmpdir, "log": log_path}
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


def _t11_shots_dir():
    return os.environ.get("T11_SHOTS_DIR") or SHOTS_DIR


def _t11_new_page(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    return page, errors, crashes


def _t11_odd(errors):
    return [e for e in errors if not (
        "Failed to load resource" in e and (" 502" in e or " 503" in e))]


def _t11_open_screening(page, base, via_menu=False):
    page.goto(base + "/")
    page.wait_for_selector(
        'button.nav-btn[data-view-target="view-screening"]', timeout=15000)
    if via_menu:
        page.click("#menu-toggle-btn")
        page.wait_for_timeout(400)
    page.click('button.nav-btn[data-view-target="view-screening"]')
    page.wait_for_selector("#view-screening.active", timeout=15000)
    page.wait_for_timeout(600)


def _t11_assert_clean(errors, crashes):
    assert not crashes, crashes
    assert not _t11_odd(errors), _t11_odd(errors)


def _t11_idle_status(route):
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps({"screening": {
                      "status": "idle", "run_id": None, "resumed": False,
                      "pid": None, "exit_code": None, "elapsed": None,
                      "elapsed_human": None, "started_iso": None,
                      "words": [], "out_dir": "", "log": [],
                      "manifest": None, "note": ""}}))


def test_t11_01_over_cap_fa_error_no_spawn_live_browser(live_console):
    """IT-T11-01: paste 2501 words -> fa error with excess ۱, no run."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t11_new_page(browser)
    calls = {"n": 0}

    def run_route(route):
        calls["n"] += 1
        route.fulfill(status=201, content_type="application/json",
                      body=json.dumps({"screening": {"status": "running"}}))

    try:
        page.route("**/api/screening/run", run_route)
        page.route("**/api/screening/status", _t11_idle_status)
        page.route("**/api/screening/exists*",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps({"out_name": "x", "path": "/tmp/x",
                                        "exists": False})))
        _t11_open_screening(page, base)
        words = ["%c%c%c" % (97 + (i // 676) % 26, 97 + (i // 26) % 26,
                             97 + i % 26) for i in range(2501)]
        page.evaluate(
            "document.getElementById('screening-words').value = `%s`; "
            "document.getElementById('screening-words')"
            ".dispatchEvent(new Event('input', {bubbles: true}))"
            % "\\n".join(words))
        page.wait_for_function(
            "document.getElementById('screening-words-count')"
            ".textContent.includes('۲۵۰۱')",
            timeout=5000)
        page.click("#screening-start")
        page.wait_for_selector("#screening-err .form-error", timeout=5000)
        err = page.inner_text("#screening-err")
        assert "سقف" in err and "2500" in _norm_digits(err), err
        assert "۱" in err, err  # excess count in Persian digits
        page.wait_for_timeout(800)
        assert calls["n"] == 0, calls  # zero spawn
        _t11_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t11_02_bad_row_cites_row_number_live_browser(live_console):
    """IT-T11-02: bad row -> error cites the row number, no run."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t11_new_page(browser)
    calls = {"n": 0}

    def run_route(route):
        calls["n"] += 1
        route.fulfill(status=201, content_type="application/json",
                      body=json.dumps({"screening": {"status": "running"}}))

    try:
        page.route("**/api/screening/run", run_route)
        page.route("**/api/screening/status", _t11_idle_status)
        _t11_open_screening(page, base)
        page.fill("#screening-words", "run\nBAD WORD!\ntake")
        page.click("#screening-start")
        page.wait_for_selector("#screening-err .form-error", timeout=5000)
        err = page.inner_text("#screening-err")
        assert "ردیف" in err, err
        assert "۲" in err, err  # second row cited in Persian digits
        page.wait_for_timeout(800)
        assert calls["n"] == 0, calls
        _t11_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t11_03_collision_four_options_live_browser(live_console):
    """IT-T11-03: run demo twice -> 4-option dialog; each option verified."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t11_new_page(browser)
    seen = {"runs": 0, "polls": 0, "polls_at_run": 0, "bodies": []}

    def run_route(route):
        seen["runs"] += 1
        seen["bodies"].append(route.request.post_data_json)
        seen["polls_at_run"] = seen["polls"]
        route.fulfill(status=201, content_type="application/json",
                      body=json.dumps({"screening": {
                          "status": "running", "run_id": "t11",
                          "resumed": False, "pid": 1, "exit_code": None,
                          "elapsed": None, "elapsed_human": None,
                          "started_iso": None, "words": [],
                          "out_dir": "/tmp/demo", "log": [],
                          "manifest": None, "note": ""}}))

    def status_route(route):
        seen["polls"] += 1
        if seen["runs"] > 0 and \
                seen["polls"] - seen["polls_at_run"] >= 2:
            body = {"screening": {
                "status": "completed", "run_id": "t11",
                "resumed": False, "pid": 1, "exit_code": 0,
                "elapsed": 3.0, "elapsed_human": "۳ ثانیه",
                "started_iso": "2026-09-28T00:00:00+00:00",
                "words": ["run"], "out_dir": "/tmp/demo",
                "log": ["done"], "manifest": None, "note": ""}}
        elif seen["runs"] > 0:
            body = {"screening": {
                "status": "running", "run_id": "t11",
                "resumed": False, "pid": 1, "exit_code": None,
                "elapsed": None, "elapsed_human": None,
                "started_iso": None, "words": [],
                "out_dir": "/tmp/demo", "log": [],
                "manifest": None, "note": ""}}
        else:
            body = {"screening": {
                "status": "idle", "run_id": None, "resumed": False,
                "pid": None, "exit_code": None, "elapsed": None,
                "elapsed_human": None, "started_iso": None,
                "words": [], "out_dir": "", "log": [],
                "manifest": None, "note": ""}}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))

    def exists_route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"out_name": "demo",
                                       "path": "/tmp/demo",
                                       "exists": True}))

    def wait_settled():
        page.wait_for_function(
            "!document.getElementById('screening-start').disabled",
            timeout=20000)

    try:
        page.route("**/api/screening/run", run_route)
        page.route("**/api/screening/status", status_route)
        page.route("**/api/screening/exists*", exists_route)
        _t11_open_screening(page, base)
        page.fill("#screening-words", "run,light,take")
        page.fill("#screening-out-name", "demo")

        # Dialog shows all 4 options; overwrite locked behind confirm.
        page.click("#screening-start")
        page.wait_for_selector(
            "#collision-dialog:not([hidden])", timeout=10000)
        for sel in ("#collision-auto", "#collision-overwrite",
                    "#collision-rename-go", "#collision-cancel"):
            assert page.is_visible(sel), sel
        assert page.is_disabled("#collision-overwrite")
        page.check("#collision-overwrite-confirm")
        assert not page.is_disabled("#collision-overwrite")
        os.makedirs(_t11_shots_dir(), exist_ok=True)
        page.screenshot(path=os.path.join(
            _t11_shots_dir(), "shot-t11-collision-desktop.png"))

        # 1) auto -> collision=auto, no overwrite of the first output.
        page.click("#collision-auto")
        page.wait_for_function(
            "document.getElementById('collision-dialog')"
            ".hasAttribute('hidden')",
            timeout=5000)
        wait_settled()
        assert seen["runs"] == 1, seen
        assert seen["bodies"][-1].get("collision") == "auto", seen
        assert seen["bodies"][-1].get("out_name") == "demo", seen

        # 2) overwrite (confirmed) -> collision=overwrite.
        page.click("#screening-start")
        page.wait_for_selector(
            "#collision-dialog:not([hidden])", timeout=10000)
        page.check("#collision-overwrite-confirm")
        page.click("#collision-overwrite")
        page.wait_for_function(
            "document.getElementById('collision-dialog')"
            ".hasAttribute('hidden')",
            timeout=5000)
        wait_settled()
        assert seen["runs"] == 2, seen
        assert seen["bodies"][-1].get("collision") == "overwrite", seen

        # 3) inline rename -> fresh out_name, no collision flag.
        page.click("#screening-start")
        page.wait_for_selector(
            "#collision-dialog:not([hidden])", timeout=10000)
        page.fill("#collision-rename", "demo-fresh")
        page.click("#collision-rename-go")
        page.wait_for_function(
            "document.getElementById('collision-dialog')"
            ".hasAttribute('hidden')",
            timeout=5000)
        wait_settled()
        assert seen["runs"] == 3, seen
        assert seen["bodies"][-1].get("out_name") == "demo-fresh", seen
        assert "collision" not in seen["bodies"][-1], seen

        # 4) full cancel -> zero new requests.
        page.click("#screening-start")
        page.wait_for_selector(
            "#collision-dialog:not([hidden])", timeout=10000)
        page.click("#collision-cancel")
        page.wait_for_function(
            "document.getElementById('collision-dialog')"
            ".hasAttribute('hidden')",
            timeout=5000)
        page.wait_for_timeout(500)
        assert seen["runs"] == 3, seen
        _t11_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t11_04_upload_lands_and_repicks_live_browser(live_console):
    """IT-T11-04: upload -> under data root -> re-pickable from dialog."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    # NOTE: the source file must live OUTSIDE the stubbed dialog root —
    # uploading a same-name file is a 409 by design (never overwrites).
    srcdir = os.path.join(os.path.dirname(tmpdir), "t11-up-src")
    os.makedirs(srcdir, exist_ok=True)
    upfile = os.path.join(srcdir, "t11-up.txt")
    with open(upfile, "w", encoding="utf-8") as handle:
        handle.write("alpha\nbeta\ngamma\n")
    page, errors, crashes = _t11_new_page(browser)
    try:
        page.route("**/api/files/roots",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps(
                           {"roots": [{"path": tmpdir,
                                       "label": "t11 fixtures"}],
                            "files": {}})))
        page.route("**/api/screening/status", _t11_idle_status)
        _t11_open_screening(page, base)
        page.click("#screening-pick-input")
        page.wait_for_selector(
            "#data-dialog:not([hidden])", timeout=10000)
        page.wait_for_timeout(800)
        page.set_input_files("#data-dialog-upload-file", upfile)
        page.click("#data-dialog-upload")
        page.wait_for_function(
            "document.getElementById('data-dialog-tbody')"
            ".textContent.includes('t11-up.txt')",
            timeout=15000)
        landed = os.path.join(tmpdir, "t11-up.txt")
        assert os.path.isfile(landed), landed
        page.click("#data-dialog-tbody tr:has-text('t11-up.txt')"
                   " button:has-text('انتخاب به‌عنوان ورودی')")
        page.wait_for_function(
            "document.getElementById('data-dialog')"
            ".hasAttribute('hidden')",
            timeout=10000)
        page.wait_for_function(
            "document.getElementById('screening-words-count')"
            ".textContent.trim() === '۳'",
            timeout=5000)
        assert "alpha" in page.input_value("#screening-words")
        _t11_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t11_collision_tablet_shot_live_browser(live_console):
    """Tablet: 4-option collision dialog renders + tablet screenshot."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        page.route("**/api/screening/status", _t11_idle_status)
        page.route("**/api/screening/exists*",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps({"out_name": "demo",
                                        "path": "/tmp/demo",
                                        "exists": True})))
        _t11_open_screening(page, base, via_menu=True)
        # Tablet accordion is single-open: fill A1 first, then open A2
        # for the name, then A4 for the start button.
        page.fill("#screening-words", "run,light,take")
        page.click("#screening-acc-a2 > summary")
        page.wait_for_timeout(400)
        page.fill("#screening-out-name", "demo")
        page.click("#screening-acc-a4 > summary")
        page.wait_for_timeout(400)
        page.click("#screening-start")
        page.wait_for_selector(
            "#collision-dialog:not([hidden])", timeout=10000)
        for sel in ("#collision-auto", "#collision-overwrite",
                    "#collision-rename-go", "#collision-cancel"):
            assert page.is_visible(sel), sel
        _t11_assert_clean(errors, crashes)
        os.makedirs(_t11_shots_dir(), exist_ok=True)
        page.screenshot(path=os.path.join(
            _t11_shots_dir(), "shot-t11-collision-tablet.png"))
    finally:
        page.close()
