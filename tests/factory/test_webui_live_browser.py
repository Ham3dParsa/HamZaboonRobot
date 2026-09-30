"""Live browser proof: preset caps save+edit and candidate-card geometry.

Both tests drive REAL Chromium against a REAL console server subprocess
(spawned on a free alternate port, readiness-polled with a bounded
timeout, never waited on, pid-targeted stop at teardown). Fixtures are
data files only (screened JSONL, run candidates JSON, link-table TSV in
tmp) — no mocked endpoints, no file:// shortcuts, no stubbed geometry.

Bug 1: type 15 (minute) + 500 (daily) into the caps fields, save, read
the catalog table back, and assert the row shows exactly those values
(hourly stays unlimited); then load the row into the form, re-save with
a new daily value, and assert the SAME row updates with no duplicates.

Bug 2: open the linking cabin, click the run#25 queue row, and assert
every rendered sense-candidate card shows its full text (no hidden
overflow / mid-word cut) with the select button balanced in the card
header.
"""

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


def _shared_presets_dir():
    """Where the live server actually stores presets (shared data root,
    outside git — the per-console dir is only a migration source now)."""
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    from factory.core.env_loader import data_root
    return os.path.join(data_root(), "webui", "presets")

FA_TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _norm_digits(text):
    return str(text or "").translate(FA_TO_ASCII)


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
    """Screened export (30 senses, run#25 mid-queue) + run + table."""
    screened_path = os.path.join(tmpdir, "screened.jsonl")
    full25 = "en-run-25-verb-AbCdEfGh"
    with open(screened_path, "w", encoding="utf-8") as handle:
        for num in range(1, 31):
            short = "run#%d" % num
            full = ("en-run-%d-verb-AbCdEfGh" % num) if num != 25 else full25
            rec = {"lemma": "run",
                   "sense": {"sense_id": short, "id": full,
                             "glosses": ["sense %d gloss" % num],
                             "examples": [{"text": "sense %d example" % num}]}}
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
    run_path = os.path.join(tmpdir, "candidates.json")
    blob = {full25: {"top3": [
        {"sensekey": "run%25verb%25run%3Averb%3Arun%3A01",
         "gloss": ("to move fast on foot so that both feet leave the ground "
                   "with every single step taken forward across a long "
                   "distance without pause or rest along the way"),
         "lemmas": ["sprint", "dash",
                    "scamper", "moveveryquicklywithoutpausingforbreath",
                    "hasten", "rush", "scurry", "bolt"],
         "examples": [{"text": ("She sprinted across the finish line while "
                                "the crowd kept cheering her onward.")}],
         "fires": ["lemma-jaccard"], "jaccard": 0.91},
        {"sensekey": "test%25verb%25test%3Averb%3Atest%3A02",
         "gloss": "to try out an idea in practice",
         "lemmas": ["try", "test", "sample"],
         "examples": [{"text": "They tested the idea in practice."}],
         "fires": [], "jaccard": 0.4}]}}
    with open(run_path, "w", encoding="utf-8") as handle:
        json.dump(blob, handle, ensure_ascii=False)
    table_path = os.path.join(tmpdir, "table.tsv")
    with open(table_path, "w", encoding="utf-8") as handle:
        handle.write("sense_id\twordnet_sensekey\tmethod\tevidence\n")
    return screened_path, run_path, table_path, full25


@pytest.fixture(scope="module")
def live_console(tmp_path_factory):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        pytest.skip("playwright not installed: %s" % exc)
    tmpdir = str(tmp_path_factory.mktemp("live"))
    screened, run, table, full25 = _write_fixtures(tmpdir)
    port = _free_port()
    assert port != 5561, "must run on an alternate port, never the default"
    env = dict(os.environ)
    env["HAMZABAN_SCREENED_PATH"] = screened
    env["HAMZABAN_LINK_TABLE"] = table
    env["HAMZABAN_CANDIDATES_RUN"] = run
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
                       "tmpdir": tmpdir, "full25": full25,
                       "log": log_path}
            finally:
                browser.close()
    finally:
        log_handle.close()
        # pidfile-targeted stop: SIGTERM the exact child, bounded wait,
        # escalate only when still alive — never an unbounded wait.
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:
            pass


def _providers_page(browser, base):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(base + "/")
    page.wait_for_timeout(1200)
    # Phase 2: navigation is data-attribute driven (no inline handlers or
    # window globals) — drive the real nav button like an operator would.
    page.click('button.nav-btn[data-view-target="view-providers"]')
    page.wait_for_timeout(600)
    return page


def test_preset_caps_save_and_edit_live_browser(live_console):
    """Type 15 + 500, save, table shows exactly those; edit re-saves clean."""
    browser, base = live_console["browser"], live_console["base"]
    tag = "live-%d" % os.getpid()
    page = _providers_page(browser, base)
    try:
        opts = page.evaluate(
            "[...document.getElementById('preset-provider').options]"
            ".map(o=>o.value)")
        assert opts, "provider select must list real registry providers"
        provider = "avalai" if "avalai" in opts else opts[0]
        page.select_option("#preset-provider", provider)
        page.fill("#preset-label", tag)
        page.fill("#preset-model", "m-live")
        page.fill("#preset-rpm", "15")
        page.fill("#preset-rph", "")
        page.fill("#preset-rpd", "500")
        page.click("#btn-save-judge-preset")
        page.wait_for_selector(
            "#preset-catalog-tbody tr", timeout=15000)
        page.wait_for_timeout(800)
        cells = page.evaluate(
            "[...document.querySelectorAll('#preset-catalog-tbody tr')]"
            ".map(tr=>[...tr.cells].map(td=>td.innerText))")
        mine = [c for c in cells if c and _norm_digits(c[0]) == tag]
        assert len(mine) == 1, cells
        minute, hourly, daily = (
            _norm_digits(mine[0][3]), _norm_digits(mine[0][4]),
            _norm_digits(mine[0][5]))
        assert minute == "15", mine[0]
        assert "نامحدود" in mine[0][4], mine[0]
        assert hourly == "نامحدود", mine[0]
        assert daily == "500", mine[0]
        # EDIT: load the row into the form, change daily, re-save.
        page.evaluate(
            "[...document.querySelectorAll('#preset-catalog-tbody tr')]"
            ".filter(tr=>tr.cells[0].innerText.includes('%s'))[0]"
            ".querySelectorAll('button')[0].click()" % tag)
        page.wait_for_timeout(800)
        assert _norm_digits(page.input_value("#preset-rpm")) == "15"
        assert _norm_digits(page.input_value("#preset-rpd")) == "500"
        page.fill("#preset-rpd", "600")
        page.click("#btn-save-judge-preset")
        page.wait_for_timeout(1200)
        cells = page.evaluate(
            "[...document.querySelectorAll('#preset-catalog-tbody tr')]"
            ".map(tr=>[...tr.cells].map(td=>td.innerText))")
        mine = [c for c in cells
                if c and _norm_digits(c[0]) == tag]
        assert len(mine) == 1, cells  # same preset, no duplicates
        assert _norm_digits(mine[0][5]) == "600", mine[0]
        assert _norm_digits(mine[0][3]) == "15", mine[0]
        page.screenshot(path=os.path.join(
            live_console["tmpdir"], "caps-table.png"))
    finally:
        page.close()
        req = urllib.request.Request(
            base + "/api/ai_presets/" + tag, method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
        leftover = os.path.join(_shared_presets_dir(), tag + ".json")
        if os.path.isfile(leftover):
            os.remove(leftover)


def test_mechanical_tab_panel_replaces_manual_form_live_browser(live_console):
    """Tab 1 is the mechanical panel; the manual-review form is gone.

    Obsoletes the candidate-card geometry test (manual form
    route-deleted by the mechanical sprint): tab-1 shows the run card
    (run/log/handoff), the tab reads «گزینش نامزدها», and no manual
    voting DOM remains anywhere.
    """
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        page.goto(base + "/")
        page.click('#view-linking .cockpit-tabs .tab-link[data-tab-index="1"]')
        page.wait_for_selector("#mechanical-run-card", timeout=15000)
        assert page.is_visible("#mechanical-run-card")
        assert page.is_visible("#btn-mechanical-run")
        assert "گزینش نامزدها" in page.inner_text(
            '#view-linking .cockpit-tabs .tab-link[data-tab-index="1"]')
        for gone in ("#sense-detail", "#candidates-stack", "#btn-reject-all",
                     "#btn-record-link", "#btn-skip-next",
                     "#arbiter-verdict-list"):
            assert page.evaluate(
                "document.querySelector('%s') === null" % gone), gone
        page.screenshot(path=os.path.join(
            live_console["tmpdir"], "mechanical-tab.png"))
    finally:
        page.close()




# ── T07 screening cabin controls + live tab (IT-T07-01..05) ──
# Real Chromium against the real console server; only the
# /api/screening/* endpoints are stubbed at the HTTP layer (Playwright
# route interception) with the exact Wave-1 backend shapes, because the
# real export child needs the multi-GB Kaikki index that CI never has.
# All DOM/render/filter/reconnect/handoff assertions run against the
# real served page with zero JS faults. Words below are letter-only so
# the REAL ledger_preview regex keeps all 500 (digits would be dropped
# server-side and fresh_count would read 0).
_T07_WORDS500 = ["%c%c" % (97 + i // 26, 97 + i % 26) for i in range(500)]


def _t07_manifest():
    return {
        "kept_total": 12, "dropped_total": 8,
        "per_lemma": [
            {"lemma": "run", "input_senses": 10, "kept": 7, "dropped": 3,
             "drops": [
                 {"sense_id": "run#1", "reason": "twin_r3 duplicate"},
                 {"sense_id": "run#2", "reason": "proper_r2 proper noun"},
                 {"sense_id": "run#3", "reason": "other obsolete"}]},
            {"lemma": "light", "input_senses": 6, "kept": 3, "dropped": 3},
            {"lemma": "take", "input_senses": 4, "kept": 2, "dropped": 2,
             "drops": [
                 {"sense_id": "take#1", "reason": "twin_r3 duplicate"}]},
        ],
        "drop_reasons": {"twin_r3": 5, "proper_r2": 2, "other": 1},
    }


def _t07_running_body():
    return {"screening": {
        "status": "running", "run_id": "t07-run", "resumed": False,
        "pid": 4242, "exit_code": None, "elapsed": 4.2,
        "elapsed_human": "۴ ثانیه",
        "started_iso": "2026-09-27T00:00:00+00:00",
        "words": ["run"], "out_dir": "/tmp/t07-out",
        "log": ["t07-line-1", "t07-line-2"], "manifest": None, "note": ""}}


def _t07_completed_body(out="/tmp/t07-out"):
    return {"screening": {
        "status": "completed", "run_id": "t07-run", "resumed": False,
        "pid": 4242, "exit_code": 0, "elapsed": 12.0,
        "elapsed_human": "۱۲ ثانیه",
        "started_iso": "2026-09-27T00:00:00+00:00",
        "words": ["run", "light", "take"], "out_dir": out,
        "log": ["kept=12 dropped=8 out=" + out],
        "manifest": _t07_manifest(), "note": ""}}


def _t07_shots_dir(live_console):
    return os.environ.get("T07_SHOTS_DIR") or live_console["tmpdir"]


def _t07_new_page(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    return page, errors, crashes


def _t07_odd(errors):
    return [e for e in errors if not (
        "Failed to load resource" in e and (" 502" in e or " 503" in e))]


def _t07_open_screening(page, base, via_menu=False):
    page.goto(base + "/")
    page.wait_for_selector(
        'button.nav-btn[data-view-target="view-screening"]', timeout=15000)
    if via_menu:  # tablet/phone: nav lives behind the hamburger toggle
        page.click("#menu-toggle-btn")
        page.wait_for_timeout(400)
    page.click('button.nav-btn[data-view-target="view-screening"]')
    page.wait_for_selector("#view-screening.active", timeout=15000)
    page.wait_for_timeout(600)


def _t07_assert_clean(errors, crashes):
    assert not crashes, crashes
    assert not _t07_odd(errors), _t07_odd(errors)


def test_t07_01_paste_start_poll_handoff_live_browser(live_console):
    """500-line paste → preview ۵۰۰ → busy → poll → metrics → handoff."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    polls = {"n": 0}

    def run_route(route):
        time.sleep(1.0)  # hold the POST open so the busy text is observable
        route.fulfill(status=201, content_type="application/json",
                      body=json.dumps(_t07_running_body()))

    def status_route(route):
        polls["n"] += 1
        body = (_t07_completed_body()
                if polls["n"] >= 3 else _t07_running_body())
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))

    try:
        page.route("**/api/screening/run", run_route)
        page.route("**/api/screening/status", status_route)
        _t07_open_screening(page, base)
        page.fill("#screening-words", "\n".join(_T07_WORDS500))
        page.wait_for_function(
            "document.getElementById('screening-words-count')"
            ".textContent.trim() !== '۰'",
            timeout=5000)
        assert _norm_digits(
            page.inner_text("#screening-words-count")) == "500"
        # A3 ledger preview against the REAL endpoint: all fresh.
        page.wait_for_function(
            "document.getElementById('screening-ledger')"
            ".textContent.includes('تازه')",
            timeout=10000)
        assert _norm_digits(
            page.inner_text("#screening-ledger")) == "500 تازه، 0 تکراری"
        page.click("#screening-start")
        page.wait_for_function(
            "document.getElementById('screening-start')"
            ".textContent.includes('در حال شروع')",
            timeout=5000)
        page.wait_for_function(
            "!document.getElementById('screening-handoff').disabled",
            timeout=20000)
        assert _norm_digits(
            page.inner_text("#screening-m-kept")) == "12"
        assert _norm_digits(
            page.inner_text("#screening-m-twins")) == "5"
        assert _norm_digits(
            page.inner_text("#screening-m-proper")) == "2"
        assert _norm_digits(
            page.inner_text("#screening-m-other")) == "1"
        assert _norm_digits(
            page.inner_text("#screening-elapsed")) == "12 ثانیه"
        page.wait_for_function(
            "document.querySelectorAll("
            "'#screening-per-lemma-tbody tr[data-lemma]').length === 3",
            timeout=5000)
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _t07_shots_dir(live_console), "shot-t07-cabin-desktop.png"))
    finally:
        page.close()


def _t07_completed_page(browser, base):
    page, errors, crashes = _t07_new_page(browser)
    page.route("**/api/screening/status",
               lambda route: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps(_t07_completed_body())))
    _t07_open_screening(page, base)
    page.wait_for_function(
        "document.querySelectorAll("
        "'#screening-per-lemma-tbody tr[data-lemma]').length === 3",
        timeout=15000)
    return page, errors, crashes


def test_t07_02_filter_client_side_counter_live_browser(live_console):
    """Filter narrows rows with zero server calls; N-of-M counter exact."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    calls = {"n": 0}

    def status_route(route):
        calls["n"] += 1
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_t07_completed_body()))

    try:
        page.route("**/api/screening/status", status_route)
        _t07_open_screening(page, base)
        page.wait_for_function(
            "document.querySelectorAll("
            "'#screening-per-lemma-tbody tr[data-lemma]').length === 3",
            timeout=15000)
        before = calls["n"]
        page.fill("#screening-filter", "light")
        page.wait_for_function(
            "document.querySelectorAll("
            "'#screening-per-lemma-tbody tr[data-lemma]').length === 1",
            timeout=5000)
        assert _norm_digits(
            page.inner_text("#screening-visible-count")) == \
            "1 نمایان از 3 سطر"
        page.wait_for_timeout(1500)
        assert calls["n"] == before, calls  # no server round-trip while filtering
        page.fill("#screening-filter", "")
        page.wait_for_function(
            "document.querySelectorAll("
            "'#screening-per-lemma-tbody tr[data-lemma]').length === 3",
            timeout=5000)
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t07_03_row_click_detail_live_browser(live_console):
    """Row click → same-lemma counts + dropped ids + reasons; row marked."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_completed_page(browser, base)
    try:
        page.click("#screening-per-lemma-tbody tr[data-lemma='run']")
        page.wait_for_function(
            "document.getElementById('screening-detail')"
            ".textContent.includes('run#1')",
            timeout=5000)
        detail = page.inner_text("#screening-detail")
        assert "run#1" in detail and "run#2" in detail, detail
        # Group A glossary: server reason classes render Persian —
        # twin_r3 → حذف دوقلو (R3), proper_r2 → حذف اسم خاص (R2).
        assert "حذف دوقلو" in detail and "R3" in detail, detail
        assert "حذف اسم خاص" in detail and "R2" in detail, detail
        assert "twin_r3" not in detail and "proper_r2" not in detail, detail
        assert "gloss" not in detail.lower(), detail
        marked = page.eval_on_selector(
            "#screening-per-lemma-tbody tr.sel", "el => el.dataset.lemma")
        assert marked == "run", marked
        # Lemma without drop ids → honest empty, counts still shown.
        page.click("#screening-per-lemma-tbody tr[data-lemma='light']")
        page.wait_for_function(
            "document.getElementById('screening-detail')"
            ".textContent.includes('خلاصه سرور نیست')",
            timeout=5000)
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t07_04_refresh_mid_run_resumes_live_browser(live_console):
    """Refresh mid-run → running resumed with non-empty log tail."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)

    def status_route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"screening": {
                          "status": "running", "run_id": "t07-run",
                          "resumed": True, "pid": 4242, "exit_code": None,
                          "elapsed": None,
                          "elapsed_human": "۲ دقیقه و ۵ ثانیه",
                          "started_iso": "2026-09-27T00:00:00+00:00",
                          "words": [], "out_dir": "/tmp/t07-out",
                          "log": ["tail-line-6", "tail-line-7"],
                          "manifest": None, "note": ""}}))

    try:
        page.route("**/api/screening/status", status_route)
        _t07_open_screening(page, base)
        page.wait_for_function(
            "document.getElementById('screening-state')"
            ".textContent.includes('در حال اجرا')",
            timeout=10000)
        page.wait_for_function(
            "document.getElementById('screening-log')"
            ".textContent.includes('tail-line-7')",
            timeout=5000)
        assert page.is_visible("#screening-resumed")
        assert _norm_digits(
            page.inner_text("#screening-elapsed")) == "2 دقیقه و 5 ثانیه"
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t07_05_complete_handoff_opens_linking_live_browser(live_console):
    """Complete → banner with out path → handoff opens the linking cabin."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_completed_page(browser, base)
    try:
        page.wait_for_function(
            "!document.getElementById('screening-handoff').disabled",
            timeout=10000)
        assert page.is_visible("#screening-handoff-banner")
        assert "/tmp/t07-out" in \
            page.inner_text("#screening-handoff-banner")
        page.click("#screening-handoff")
        page.wait_for_timeout(1200)
        assert page.evaluate(
            "document.getElementById('view-linking')"
            ".classList.contains('active')") is True
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t07_cabin_tablet_accordion_shot_live_browser(live_console):
    """Tablet ≤1024px: control column becomes an accordion above workspace."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        page.route("**/api/screening/status",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps(_t07_completed_body())))
        _t07_open_screening(page, base, via_menu=True)
        page.wait_for_function(
            "document.querySelectorAll("
            "'#screening-per-lemma-tbody tr[data-lemma]').length === 3",
            timeout=15000)
        assert page.is_visible(".screening-controls > summary")
        layout = page.evaluate(
            "getComputedStyle(document.querySelector('.screening-layout'))"
            ".gridTemplateColumns")
        assert " " not in layout.strip(), layout  # single column stacked
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _t07_shots_dir(live_console), "shot-t07-cabin-tablet.png"))
    finally:
        page.close()


def test_shell_chrome_no_console_errors_live_browser(live_console):
    """Phase-2 shell proof: tabs, modal, preset save, queue filter, 0 errors.

    Drives the extracted ES-module shell (single module script tag, no
    inline handlers, provider events over hz:*-refreshed) through the
    operator chrome: every nav button, every linking tab, the model
    modal open/close, a preset save, and a live queue-filter pass —
    with zero JS console errors and zero uncaught page errors.
    """
    browser, base = live_console["browser"], live_console["base"]
    tag = "chrome-%d" % os.getpid()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    crashes = []
    page.on("console",
            lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        page.goto(base + "/")
        # P5/R2: queue lives in tab 0 (hidden until its tab opens).
        page.click('#view-linking .cockpit-tabs .tab-link[data-tab-index="0"]')
        page.wait_for_selector("#queue-list .queue-item", timeout=15000)
        page.wait_for_timeout(800)
        # single module script tag, zero inline handlers
        assert page.evaluate(
            "document.querySelectorAll('script').length") == 1
        assert page.evaluate(
            "document.querySelectorAll('[onclick]').length") == 0
        assert page.evaluate(
            "document.querySelector('script').type") == "module"
        # every nav button activates its view (data-view-target wiring)
        for view in ("view-linking", "view-providers", "view-telemetry",
                     "view-paths", "view-screening", "view-precard",
                     "view-pilot", "view-transfer"):
            page.click(
                'button.nav-btn[data-view-target="%s"]' % view)
            page.wait_for_timeout(250)
            assert page.evaluate(
                "document.getElementById('%s')"
                ".classList.contains('active')" % view), view
        # linking tabs switch and persist the active tab
        # (scoped to #view-linking: the screening cabin owns its own
        # cockpit-tabs pair since T07, so a global count would be 7)
        page.click('button.nav-btn[data-view-target="view-linking"]')
        page.wait_for_timeout(300)
        n_tabs = page.evaluate(
            "document.querySelectorAll('#view-linking .cockpit-tabs .tab-link').length")
        assert n_tabs == 5, n_tabs
        for idx in range(n_tabs):
            page.evaluate(
                "document.querySelectorAll('#view-linking .cockpit-tabs .tab-link')"
                "[%d].click()" % idx)
            page.wait_for_timeout(200)
            assert page.evaluate(
                "document.querySelectorAll('#view-linking .cockpit-tabs .tab-link')"
                "[%d].classList.contains('active')" % idx), idx
        # screening cabin tabs switch independently (T07 live tab + T08 shell)
        page.click('button.nav-btn[data-view-target="view-screening"]')
        page.wait_for_timeout(300)
        assert page.evaluate(
            "document.querySelectorAll("
            "'#view-screening .cockpit-tabs .tab-link').length") == 2
        page.click("#screening-tabbtn-2")
        page.wait_for_timeout(300)
        assert page.evaluate(
            "document.getElementById('screening-tab-2').hidden") is False
        assert page.evaluate(
            "document.getElementById('screening-tab-1').hidden") is True
        page.click("#screening-tabbtn-1")
        page.wait_for_timeout(300)
        assert page.evaluate(
            "document.getElementById('screening-tab-1').hidden") is False
        page.click('button.nav-btn[data-view-target="view-linking"]')
        page.wait_for_timeout(300)
        # queue filter lives in tab 0 (P5/R2 panels).
        page.click('#view-linking .cockpit-tabs .tab-link[data-tab-index="0"]')
        page.wait_for_timeout(300)
        # queue filter narrows the 30-row list, clearing restores it
        page.fill("#queue-filter", "run#25")
        page.wait_for_timeout(400)
        assert page.evaluate(
            "document.querySelectorAll('#queue-list .queue-item').length") \
            == 1
        page.fill("#queue-filter", "")
        page.wait_for_timeout(400)
        assert page.evaluate(
            "document.querySelectorAll('#queue-list .queue-item').length") \
            == 30
        # providers: model modal opens and closes via its own buttons
        page.click('button.nav-btn[data-view-target="view-providers"]')
        page.wait_for_timeout(500)
        page.click("#btn-open-model-picker")
        page.wait_for_timeout(800)
        assert page.evaluate(
            "document.getElementById('model-picker').open") is True
        page.click("#btn-close-model-picker")
        page.wait_for_timeout(300)
        assert page.evaluate(
            "document.getElementById('model-picker').open") is False
        # providers: preset save round-trips through the catalog table
        opts = page.evaluate(
            "[...document.getElementById('preset-provider').options]"
            ".map(o=>o.value)")
        assert opts, "provider select must list real registry providers"
        provider = "avalai" if "avalai" in opts else opts[0]
        page.select_option("#preset-provider", provider)
        page.fill("#preset-label", tag)
        page.fill("#preset-model", "m-chrome")
        page.fill("#preset-rpm", "15")
        page.fill("#preset-rph", "")
        page.fill("#preset-rpd", "500")
        page.click("#btn-save-judge-preset")
        page.wait_for_selector(
            "#preset-catalog-tbody tr", timeout=15000)
        page.wait_for_timeout(800)
        cells = page.evaluate(
            "[...document.querySelectorAll('#preset-catalog-tbody tr')]"
            ".map(tr=>[...tr.cells].map(td=>td.innerText))")
        mine = [c for c in cells if c and _norm_digits(c[0]) == tag]
        assert len(mine) == 1, cells
        # zero JS faults: no uncaught page exception, and no console error
        # except the browser's own resource lines for upstream HTTP
        # statuses the UI already handles (502/503 from the keyless test
        # env — no keys, no supervisor). A 404 here (missing module) or
        # any other console error fails the test.
        assert not crashes, crashes
        odd = [e for e in errors if not (
            "Failed to load resource" in e
            and (" 502" in e or " 503" in e))]
        assert not odd, odd
        page.screenshot(path=os.path.join(
            live_console["tmpdir"], "shell-chrome.png"))
    finally:
        page.close()
        req = urllib.request.Request(
            base + "/api/ai_presets/" + tag, method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
        leftover = os.path.join(_shared_presets_dir(), tag + ".json")
        if os.path.isfile(leftover):
            os.remove(leftover)


# ── T08 screening history tab (IT-T08-01..04) ──
# Real Chromium against the real console server; only the Wave-1
# /api/runs/history shape is stubbed at the HTTP layer (Playwright
# route interception) with the exact backend rows
# {run_id, out_name, out_dir, started_iso, status, kept_total,
# dropped_total} newest-last. All DOM/filter/handoff assertions run
# against the real served page with zero JS faults.
def _t08_run(run_id, started_iso, out_dir="", status="completed",
             kept=0, dropped=0):
    return {"run_id": run_id, "out_name": run_id, "out_dir": out_dir,
            "started_iso": started_iso, "status": status,
            "kept_total": kept, "dropped_total": dropped}


def _t08_history_body(runs):
    return {"cabin": "screening", "runs": list(runs),
            "skipped": 0, "truncated": False}


def _t08_three_runs():
    return [
        _t08_run("t08-old", "2026-09-25T00:00:00+00:00",
                 "/tmp/t08-old", kept=1, dropped=2),
        _t08_run("t08-mid", "2026-09-26T00:00:00+00:00",
                 "/tmp/t08-mid", kept=3, dropped=4),
        _t08_run("t08-new", "2026-09-27T00:00:00+00:00",
                 "/tmp/t08-out", kept=5, dropped=6),
    ]


def _t08_shots_dir(live_console):
    return os.environ.get("T08_SHOTS_DIR") or live_console["tmpdir"]


def _t08_open_history(page, base, via_menu=False):
    _t07_open_screening(page, base, via_menu=via_menu)
    page.click("#screening-tabbtn-2")
    page.wait_for_function(
        "document.querySelectorAll("
        "'#screening-history-tbody tr[data-run-id]').length > 0",
        timeout=15000)


def test_t08_01_history_lists_three_runs_newest_last_live_browser(
        live_console):
    """History tab shows 3 seeded runs newest-last with exact counter."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/runs/history*",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps(
                           _t08_history_body(_t08_three_runs()))))
        _t08_open_history(page, base)
        order = page.evaluate(
            "[...document.querySelectorAll("
            "'#screening-history-tbody tr[data-run-id]')]"
            ".map(tr=>tr.getAttribute('data-run-id'))")
        assert order == ["t08-old", "t08-mid", "t08-new"], order
        assert _norm_digits(
            page.inner_text("#screening-history-count")) == \
            "3 نمایان از 3 اجرا"
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _t08_shots_dir(live_console),
            "shot-t08-history-desktop.png"))
    finally:
        page.close()


def test_t08_02_search_filters_client_side_live_browser(live_console):
    """Typing narrows rows instantly with zero extra server calls."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    calls = {"n": 0}

    def history_route(route):
        calls["n"] += 1
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(
                          _t08_history_body(_t08_three_runs())))

    try:
        page.route("**/api/runs/history*", history_route)
        _t08_open_history(page, base)
        before = calls["n"]
        assert before >= 1, calls
        page.fill("#screening-history-search", "t08-mid")
        page.wait_for_function(
            "document.querySelectorAll("
            "'#screening-history-tbody tr[data-run-id]').length === 1",
            timeout=5000)
        assert _norm_digits(
            page.inner_text("#screening-history-count")) == \
            "1 نمایان از 3 اجرا"
        page.wait_for_timeout(1500)
        assert calls["n"] == before, calls  # client-side only
        page.fill("#screening-history-search", "")
        page.wait_for_function(
            "document.querySelectorAll("
            "'#screening-history-tbody tr[data-run-id]').length === 3",
            timeout=5000)
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t08_03_record_handoff_arms_linking_live_browser(live_console):
    """Record handoff arms the linking banner with that run's path."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    seen = {"path": False}

    def screened_route(route):
        req = route.request
        # Page-load loadScreened() (no path) passes through with an
        # empty default; the per-record handoff must carry ?path=.
        if "path=" in (req.url or ""):
            seen["path"] = True
            body = {"path": "/tmp/t08-out/screened.jsonl",
                    "total": 0, "rows": [],
                    "truncated": False}
        else:
            body = {"path": "", "total": 0, "rows": [],
                    "truncated": False}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))

    try:
        page.route("**/api/runs/history*",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps(
                           _t08_history_body(_t08_three_runs()))))
        page.route("**/api/screened*", screened_route)
        _t08_open_history(page, base)
        page.click("#screening-history-tbody "
                   "tr[data-run-id='t08-new'] button")
        page.wait_for_function(
            "document.getElementById('view-linking')"
            ".classList.contains('active')",
            timeout=10000)
        page.wait_for_function(
            "document.getElementById('handoff-path')"
            ".textContent.includes('/tmp/t08-out/screened.jsonl')",
            timeout=10000)
        assert seen["path"] is True  # handoff went through ?path=
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t08_04_empty_history_honest_empty_live_browser(live_console):
    """Zero runs → titled honest empty, no bare-dash cells."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/runs/history*",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps(_t08_history_body([]))))
        _t07_open_screening(page, base)
        page.click("#screening-tabbtn-2")
        page.wait_for_function(
            "document.getElementById('screening-history-tbody')"
            ".textContent.includes('هنوز اجرایی')",
            timeout=15000)
        bare = page.evaluate(
            "[...document.querySelectorAll("
            "'#screening-history-tbody td')]"
            ".filter(td=>td.textContent.trim() === '—').length")
        assert bare == 0, bare
        titled = page.evaluate(
            "document.querySelector("
            "'#screening-history-tbody td').title.length > 0")
        assert titled is True
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t08_history_tablet_shot_live_browser(live_console):
    """Tablet ≤1024px: history tab renders + tablet screenshot."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        page.route("**/api/runs/history*",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps(
                           _t08_history_body(_t08_three_runs()))))
        _t08_open_history(page, base, via_menu=True)
        assert page.is_visible("#screening-history-table")
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _t08_shots_dir(live_console),
            "shot-t08-history-tablet.png"))
    finally:
        page.close()


# ── T09 slide-over data dialog + tablet accordion (IT-T09-01..05) ──
# Real Chromium against the real console server. Only /api/files/roots
# is stubbed at the HTTP layer (Playwright route interception) to point
# the dialog at the test's own fixture dir; list/mkdir/rename/words/pins
# all hit the REAL server (the fixture dir lives under the operator home
# browse root, so containment passes exactly as in production). Pins use
# unique per-pid names with API cleanup. Zero JS faults asserted.
def _t09_shots_dir(live_console):
    return os.environ.get("T09_SHOTS_DIR") or live_console["tmpdir"]


def _t09_seed(tmpdir):
    words = os.path.join(tmpdir, "words-t09.txt")
    with open(words, "w", encoding="utf-8") as handle:
        handle.write("alpha\nbeta\ngamma\n")
    dest = os.path.join(tmpdir, "t09-dest")
    os.makedirs(dest, exist_ok=True)
    return words, dest


def _t09_roots_route(tmpdir):
    """Mock roots shaped like the REAL server (P04+): each root carries
    its own files facts (the fixture words file when seeded)."""
    def _route(route):
        words = os.path.join(tmpdir, "words-t09.txt")
        if os.path.isfile(words):
            facts = {"path": words, "exists": True,
                     "size": os.path.getsize(words),
                     "lines": 3, "lines_label": "3", "truncated": False,
                     "mtime_iso": "2026-09-27T00:00:00+00:00",
                     "mtime_relative": "۱ دقیقه پیش",
                     "mtime_detail": "roots mock",
                     "cause": ""}
        else:
            facts = {"path": "", "exists": False, "size": 0,
                     "lines": 0, "lines_label": "0", "truncated": False,
                     "mtime_iso": None, "mtime_relative": "—",
                     "mtime_detail": "—", "cause": "file-missing"}
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(
                          {"roots": [{"path": tmpdir,
                                      "label": "t09 fixtures",
                                      "files": facts}],
                           "files": {}}))
    return _route


def _t09_open_dialog(page, base, pick_id):
    _t07_open_screening(page, base)
    # P05: pick buttons open the anchored picking-only popover first;
    # the full data browser comes from its «مرور کامل…» navigation row
    # (navigation, not an action — the popover itself never acts).
    # Rows-settled wait: the groups render async — clicking browse
    # before the render lands shifts the button under the cursor and
    # the click is lost (proven flake, fixed by waiting).
    page.click("#" + pick_id)
    page.wait_for_selector(
        "#cmd-popover:not([hidden])", timeout=10000)
    page.wait_for_function(
        "document.querySelectorAll('#cmd-popover li').length >= 3",
        timeout=15000)
    page.click("#cmd-popover-browse")
    page.wait_for_selector(
        "#data-dialog:not([hidden])", timeout=10000)
    page.wait_for_function(
        "document.getElementById('data-dialog-tbody')"
        ".textContent.includes('words-t09.txt')",
        timeout=15000)


def test_t09_01_pick_file_fills_a1_live_browser(live_console):
    """Dialog pick → A1 filled, count == file words, beside-column shot."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/files/roots", _t09_roots_route(tmpdir))
        _t09_open_dialog(page, base, "screening-pick-input")
        # Desktop: dialog docks opposite the control column, no overlap.
        cover = page.evaluate(
            "() => {"
            "  const d = document.getElementById('data-dialog')"
            "    .getBoundingClientRect();"
            "  const c = document.getElementById('screening-controls')"
            "    .getBoundingClientRect();"
            "  return !(d.right <= c.left || d.left >= c.right"
            "    || d.bottom <= c.top || d.top >= c.bottom);"
            "}")
        assert cover is False, "dialog must never cover the control column"
        page.screenshot(path=os.path.join(
            _t09_shots_dir(live_console), "shot-t09-dialog-desktop.png"))
        page.click("#data-dialog-tbody tr:has-text('words-t09.txt')"
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
        assert "gamma" in page.input_value("#screening-words")
        page.wait_for_function(
            "document.getElementById('screening-ledger')"
            ".textContent.includes('تازه')",
            timeout=10000)
        assert _norm_digits(
            page.inner_text("#screening-ledger")) == "3 تازه، 0 تکراری"
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t09_02_pick_dir_fills_a2_live_browser(live_console):
    """Dest pick → A2 filled with the dir path, focus returns to caller."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _, dest = _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/files/roots", _t09_roots_route(tmpdir))
        _t09_open_dialog(page, base, "screening-pick-dest")
        page.click("#data-dialog-tbody tr:has-text('t09-dest')"
                   " button:has-text('انتخاب به‌عنوان مقصد')")
        page.wait_for_function(
            "document.getElementById('data-dialog')"
            ".hasAttribute('hidden')",
            timeout=10000)
        value = page.input_value("#screening-out-dir")
        assert os.path.abspath(value) == os.path.abspath(dest), value
        focused = page.evaluate("document.activeElement.id")
        assert focused == "screening-out-dir", focused
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t09_03_pin_persists_across_reopen_live_browser(live_console):
    """Pin with a name → reopen console → still pinned; then unpinned."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    tag = "t09-live-%d" % os.getpid()
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/files/roots", _t09_roots_route(tmpdir))
        _t09_open_dialog(page, base, "screening-pick-input")
        page.fill("#data-dialog-pin-name", tag)
        page.click("#data-dialog-pin-add")
        page.wait_for_function(
            "document.getElementById('data-dialog-pins')"
            ".textContent.includes('%s')" % tag,
            timeout=10000)
        page.click("#data-dialog-close")
        page.close()
        # "Reopen": a fresh page against the same live server process.
        page, errors, crashes = _t07_new_page(browser)
        try:
            page.route("**/api/files/roots", _t09_roots_route(tmpdir))
            _t09_open_dialog(page, base, "screening-pick-input")
            assert tag in page.inner_text("#data-dialog-pins")
        finally:
            pass
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()
        req = urllib.request.Request(
            base + "/api/files/pins/" + tag, method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass


def test_t09_04_no_delete_mkdir_rename_live_browser(live_console):
    """No delete control anywhere; mkdir + same-parent rename work."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    made = os.path.join(tmpdir, "t09-mkdir-live")
    renamed = os.path.join(tmpdir, "t09-renamed-live")
    try:
        page.route("**/api/files/roots", _t09_roots_route(tmpdir))
        _t09_open_dialog(page, base, "screening-pick-input")
        labels = page.evaluate(
            "[...document.querySelectorAll('#data-dialog button')]"
            ".map(b=>b.textContent.trim())")
        assert not any(t == "حذف" for t in labels), labels
        assert not any("حذف فایل" in t for t in labels), labels
        page.fill("#data-dialog-mkdir-name", "t09-mkdir-live")
        page.click("#data-dialog-mkdir")
        page.wait_for_function(
            "document.getElementById('data-dialog-tbody')"
            ".textContent.includes('t09-mkdir-live')",
            timeout=10000)
        assert os.path.isdir(made)
        page.click("#data-dialog-tbody tr:has-text('t09-mkdir-live')"
                   " button:has-text('تغییر نام')")
        # NOTE: the inline editor replaces the name cell (input values are
        # not textContent), so the row no longer matches :has-text after.
        page.wait_for_selector(
            "#data-dialog-tbody input[aria-label='نام تازه']",
            timeout=5000)
        page.fill("#data-dialog-tbody input[aria-label='نام تازه']",
                  "t09-renamed-live")
        page.click("#data-dialog-tbody button:has-text('تأیید')")
        page.wait_for_function(
            "document.getElementById('data-dialog-tbody')"
            ".textContent.includes('t09-renamed-live')",
            timeout=10000)
        assert os.path.isdir(renamed)
        assert not os.path.exists(made)
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()
        for path in (renamed, made):
            try:
                if os.path.isdir(path):
                    os.rmdir(path)
            except OSError:
                pass


def test_t09_05_tablet_accordion_fullsheet_live_browser(live_console):
    """Tablet: A1-A4 accordion single-open; sheet never covers controls."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        page.route("**/api/files/roots", _t09_roots_route(tmpdir))
        _t07_open_screening(page, base, via_menu=True)
        order = page.evaluate(
            "[...document.querySelectorAll("
            "'#screening-card details.acc')].map(d=>d.id)")
        assert order == ["screening-acc-a1", "screening-acc-a2",
                         "screening-acc-a3", "screening-acc-a4"], order
        assert page.is_visible("#screening-acc-a2 > summary")
        page.click("#screening-acc-a2 > summary")
        page.wait_for_timeout(400)
        single = page.evaluate(
            "[...document.querySelectorAll("
            "'#screening-card details.acc')]"
            ".filter(d=>d.open).map(d=>d.id)")
        assert single == ["screening-acc-a2"], single
        page.click("#screening-acc-a4 > summary")
        page.wait_for_timeout(400)
        page.click("#screening-acc-a1 > summary")
        page.wait_for_timeout(400)
        # P05: pick opens the anchored popover; the full browser comes
        # from «مرور کامل…» after the async groups settle
        page.click("#screening-pick-input")
        page.wait_for_selector(
            "#cmd-popover:not([hidden])", timeout=10000)
        page.wait_for_function(
            "document.querySelectorAll('#cmd-popover li').length >= 3",
            timeout=15000)
        page.click("#cmd-popover-browse")
        page.wait_for_selector(
            "#data-dialog:not([hidden])", timeout=10000)
        wide = page.evaluate(
            "document.getElementById('data-dialog')"
            ".getBoundingClientRect().width")
        assert wide >= 700, wide  # full-sheet on tablet
        # The sheet stays below the control column in paint order: open
        # A4 (single-open closes A1 — the dialog is already open) and the
        # summary line + abort must be visible and topmost, never covered.
        page.click("#screening-acc-a4 > summary")
        page.wait_for_timeout(400)
        assert page.is_visible("#screening-status")
        topmost = page.evaluate(
            "() => {"
            "  const b = document.getElementById('screening-abort');"
            "  const r = b.getBoundingClientRect();"
            "  if (!r.width || !r.height) return 'empty';"
            "  const hit = document.elementFromPoint("
            "    r.left + r.width / 2, r.top + r.height / 2);"
            "  return (hit === b || (hit && b.contains(hit)))"
            "    ? 'abort-topmost' : 'covered';"
            "}")
        assert topmost == "abort-topmost", topmost
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _t09_shots_dir(live_console), "shot-t09-dialog-tablet.png"))
        # Focus returns to the caller: re-open A1 so the caller field is
        # visible, then close with Escape.
        page.click("#screening-acc-a1 > summary")
        page.wait_for_timeout(400)
        page.keyboard.press("Escape")
        page.wait_for_function(
            "document.getElementById('data-dialog')"
            ".hasAttribute('hidden')",
            timeout=5000)
        assert page.evaluate(
            "document.activeElement.id") == "screening-words"
    finally:
        page.close()


# ── T10 paths T3 wiring + formatting sweep (IT-T10-01..04) ──
# Real Chromium against the real console server; only /api/files/roots
# and /api/screening/status are stubbed at the HTTP layer (Playwright
# route interception) with the exact backend shapes. All DOM/title/
# badge/log assertions run against the real served page with zero JS
# faults. T11 seams (intake/collision/upload) are never touched here.
def _t10_shots_dir(live_console):
    return os.environ.get("T10_SHOTS_DIR") or live_console["tmpdir"]


def _t10_root_facts(screened_exists=True, over_cap=True):
    """One root's OWN facts (P04/L4 shape: root.files, not global)."""
    if not screened_exists:
        return {"path": "/tmp/t10-screened.jsonl", "exists": False,
                "size": 0, "lines": 0, "lines_label": "0",
                "truncated": False, "mtime_iso": None,
                "mtime_relative": "—", "mtime_detail": "—",
                "cause": "file-missing"}
    return {
        "path": "/tmp/t10-screened.jsonl",
        "exists": True,
        "size": 12345,
        "lines": 50000 if over_cap else 7,
        "lines_label": "50000+" if over_cap else "7",
        "truncated": bool(over_cap),
        "mtime_iso": "2026-09-27T00:00:00+00:00",
        "mtime_relative": "۵ دقیقه پیش",
        "mtime_detail": "شمسی ۱۴۰۵/۰۷/۰۵ (Asia/Tehran) • میلادی 2026-09-27 (UTC)",
        "cause": "",
    }


def _t10_files(screened_exists=True, over_cap=True):
    """Decoy global key (P04/L4 negative proof): the renderer must NOT
    read it — per-row facts ride each root's own files. Values are
    chosen to never collide with any per-root fixture."""
    _ = (screened_exists, over_cap)
    return {"kaikki_raw": {"path": "/tmp/t10-global-decoy.jsonl",
                           "exists": True, "size": 99999, "lines": 99,
                           "lines_label": "99", "truncated": False,
                           "mtime_iso": "2026-09-27T00:00:00+00:00",
                           "mtime_relative": "۹۹ دقیقه پیش",
                           "mtime_detail": "decoy"},
            "screened": {"path": "/tmp/t10-global-decoy.jsonl",
                         "exists": True, "size": 99999, "lines": 99,
                         "lines_label": "99", "truncated": False,
                         "mtime_iso": "2026-09-27T00:00:00+00:00",
                         "mtime_relative": "۹۹ دقیقه پیش",
                         "mtime_detail": "decoy"}}


def _t10_root(path, label, facts=None):
    row = {"path": path, "label": label}
    if facts is not None:
        row["files"] = facts
    return row


def _t10_roots_route(roots, files=None):
    def _route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"roots": roots,
                                       "files": files or {}}))
    return _route


def _t10_open_paths(page, base, via_menu=False):
    page.goto(base + "/")
    page.wait_for_selector(
        'button.nav-btn[data-view-target="view-paths"]', timeout=15000)
    if via_menu:
        page.click("#menu-toggle-btn")
        page.wait_for_timeout(400)
    page.click('button.nav-btn[data-view-target="view-paths"]')
    page.wait_for_selector("#view-paths.active", timeout=15000)
    page.wait_for_function(
        "document.querySelectorAll('#paths-tbody tr').length > 0",
        timeout=15000)


def test_t10_01_paths_row_shows_live_facts_live_browser(live_console):
    """IT-T10-01: paths row shows its OWN root facts (exists/size/۵۰۰۰۰+/mtime)."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    roots = [_t10_root(tmpdir, "t10 fixtures",
                       _t10_root_facts(True, True))]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/files/roots",
                   _t10_roots_route(roots, _t10_files(True, True)))
        _t10_open_paths(page, base)
        page.wait_for_function(
            "document.getElementById('paths-tbody')"
            ".textContent.includes('۵۰۰۰۰+')",
            timeout=10000)
        body = page.inner_text("#paths-tbody")
        assert "۵۰۰۰۰+" in body, body
        assert "۱۲۳۴۵" in body, body  # fa size from the row's own facts
        assert "۵ دقیقه پیش" in body, body  # fa mtime from the row's own facts
        # P04/L4 negative proof: the global decoy (۹۹۹۹۹/۹۹) is never
        # repeated into any row — per-row values come only from the row.
        assert "۹۹۹۹۹" not in body, body
        assert "۹۹ دقیقه پیش" not in body, body
        bare = page.evaluate(
            "[...document.querySelectorAll('#paths-tbody td')]"
            ".filter(td=>td.textContent.trim() === '—'"
            " && !(td.title && td.title.length > 0)).length")
        assert bare == 0, bare
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _t10_shots_dir(live_console), "shot-t10-paths-desktop.png"))
    finally:
        page.close()


def test_t10_02_dead_root_drops_badge_matches_live_browser(live_console):
    """IT-T10-02: remove a root dir → row gone, badge count matches."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    two = [_t10_root(tmpdir, "t10-a", _t10_root_facts(True, False)),
           _t10_root(os.path.join(tmpdir, "t10-b"), "t10-b")]
    os.makedirs(os.path.join(tmpdir, "t10-b"), exist_ok=True)
    one = [_t10_root(tmpdir, "t10-a", _t10_root_facts(True, False))]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/files/roots",
                   _t10_roots_route(two, _t10_files(True, False)))
        _t10_open_paths(page, base)
        page.wait_for_function(
            "document.querySelectorAll('#paths-tbody tr').length === 2",
            timeout=10000)
        assert _norm_digits(
            page.inner_text("#paths-badge")) == "2 ریشه زنده"
        # Root removed server-side (dead root drops): re-stub with one
        # root and reload — the row is gone and the badge matches.
        page.unroute("**/api/files/roots")
        page.route("**/api/files/roots",
                   _t10_roots_route(one, _t10_files(True, False)))
        page.reload()
        _t10_open_paths(page, base)
        page.wait_for_function(
            "document.querySelectorAll('#paths-tbody tr').length === 1",
            timeout=10000)
        assert _norm_digits(
            page.inner_text("#paths-badge")) == "1 ریشه زنده"
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t10_03_every_dash_titled_live_browser(live_console):
    """IT-T10-03: every — in paths + screening metrics has a title cause."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    roots = [_t10_root(tmpdir, "t10 fixtures")]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/files/roots",
                   _t10_roots_route(roots, _t10_files(False, False)))
        page.route("**/api/screening/status",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps({"screening": {
                           "status": "idle", "run_id": None,
                           "resumed": False, "pid": None,
                           "exit_code": None, "elapsed": None,
                           "elapsed_human": "—",
                           "started_iso": None, "words": [],
                           "out_dir": "", "log": [], "manifest": None,
                           "note": ""}})))
        _t10_open_paths(page, base)
        page.wait_for_timeout(800)
        bare_paths = page.evaluate(
            "[...document.querySelectorAll('#view-paths')]"
            ".flatMap(sec => [...sec.querySelectorAll('td,span,div,bdi')])"
            ".filter(elm => elm.textContent.trim() === '—'"
            " && !(elm.title && elm.title.length > 0)).length")
        assert bare_paths == 0, bare_paths
        _t07_open_screening(page, base)
        page.wait_for_function(
            "document.getElementById('screening-m-input')"
            ".textContent.includes('—')",
            timeout=10000)
        bare_metrics = page.evaluate(
            "[...document.querySelectorAll("
            "'#screening-metrics .mini-val, #screening-elapsed,"
            " #screening-out-path')]"
            ".filter(elm => elm.textContent.trim() === '—'"
            " && !(elm.title && elm.title.length > 0)).length")
        assert bare_metrics == 0, bare_metrics
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t10_04_log_box_three_states_live_browser(live_console):
    """IT-T10-04: log box idle→live→final, each with its correct text."""
    browser, base = live_console["browser"], live_console["base"]
    states = {
        "idle": {"screening": {
            "status": "idle", "run_id": None, "resumed": False,
            "pid": None, "exit_code": None, "elapsed": None,
            "elapsed_human": "—", "started_iso": None, "words": [],
            "out_dir": "", "log": [], "manifest": None, "note": ""}},
        "running": {"screening": {
            "status": "running", "run_id": "t10-run", "resumed": False,
            "pid": 4242, "exit_code": None, "elapsed": 4.2,
            "elapsed_human": "۴ ثانیه",
            "started_iso": "2026-09-27T00:00:00+00:00",
            "words": ["run"], "out_dir": "/tmp/t10-out",
            "log": [], "manifest": None, "note": ""}},
        "final": {"screening": {
            "status": "completed", "run_id": "t10-run",
            "resumed": False, "pid": 4242, "exit_code": 0,
            "elapsed": 12.0, "elapsed_human": "۱۲ ثانیه",
            "started_iso": "2026-09-27T00:00:00+00:00",
            "words": ["run"], "out_dir": "/tmp/t10-out",
            "log": [], "manifest": None, "note": ""}},
    }
    for key, expect in (("idle", "هنوز اجرایی شروع نشده"),
                        ("running", "در حال اجرا"),
                        ("final", "گزارشی از سرور نرسید")):
        page, errors, crashes = _t07_new_page(browser)
        try:
            payload = states[key]

            def _mk_status_route(body):
                def _r(route):
                    route.fulfill(status=200,
                                  content_type="application/json",
                                  body=json.dumps(body))
                return _r

            page.route("**/api/screening/status",
                       _mk_status_route(payload))
            _t07_open_screening(page, base)
            page.wait_for_function(
                "document.getElementById('screening-log')"
                ".textContent.includes('%s')" % expect,
                timeout=10000)
            title = page.eval_on_selector(
                "#screening-log", "el => el.title || ''")
            assert len(title) > 0, (key, title)
            _t07_assert_clean(errors, crashes)
        finally:
            page.close()


def test_t10_paths_tablet_shot_live_browser(live_console):
    """Tablet ≤1024px: paths table renders + tablet screenshot."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    roots = [_t10_root(tmpdir, "t10 fixtures",
                       _t10_root_facts(True, True))]
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        page.route("**/api/files/roots",
                   _t10_roots_route(roots, _t10_files(True, True)))
        _t10_open_paths(page, base, via_menu=True)
        page.wait_for_function(
            "document.getElementById('paths-tbody')"
            ".textContent.includes('۵۰۰۰۰+')",
            timeout=10000)
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _t10_shots_dir(live_console), "shot-t10-paths-tablet.png"))
    finally:
        page.close()


# ── T12 cross-cabin inheritance + final polish (IT-T12-01..04) ──
# Real Chromium against the real console server. Screening is the locked
# reference (T07-T11); linking/precard/pilot inherit its names/shapes
# (OQ-10): byte-identical field labels, withBusy server buttons, handoff
# banner with path + next-cabin button, 3-part error box, titled honest
# empties. No new endpoints are called below — precard/pilot شروع reports
# the unwired backend honestly; linking keeps its queue-driven intake
# (R2 deviation → follow-up ticket, never a silent fix).
def _t12_shots_dir(live_console):
    return os.environ.get("T12_SHOTS_DIR") or live_console["tmpdir"]


def _t12_open_cabin(page, base, view, via_menu=False):
    page.goto(base + "/")
    page.wait_for_selector(
        "button.nav-btn[data-view-target=\"%s\"]" % view, timeout=15000)
    if via_menu:
        page.click("#menu-toggle-btn")
        page.wait_for_timeout(400)
    page.click("button.nav-btn[data-view-target=\"%s\"]" % view)
    page.wait_for_selector("#%s.active" % view, timeout=15000)
    page.wait_for_timeout(400)


def test_t12_01_field_names_byte_identical_live_browser(live_console):
    """IT-T12-01: precard/pilot labels byte-identical to screening."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        _t12_open_cabin(page, base, "view-screening")

        def _labels(prefix):
            return tuple(
                page.inner_text("label[for=\"%s-%s\"]" % (prefix, field))
                for field in ("words", "out-name", "out-dir"))

        ref = _labels("screening")
        assert ref[0].startswith("واژه‌ها"), ref
        assert ref[1] == "نام خروجی", ref
        assert ref[2].startswith("مقصد"), ref
        ref_abort = page.inner_text("#screening-abort")
        assert ref_abort == "توقف اجرا", ref_abort
        for cabin in ("precard", "pilot"):
            _t12_open_cabin(page, base, "view-" + cabin)
            assert _labels(cabin) == ref, cabin  # byte-identical, no synonyms
            assert page.inner_text(
                "#%s-abort" % cabin) == ref_abort, cabin
            assert "شروع" in page.inner_text("#%s-start" % cabin), cabin
            assert "تحویل" in page.inner_text("#%s-handoff" % cabin), cabin
        # Linking keeps its queue-driven intake (R2): handoff next button
        # + error slot exist, static dashes carry title causes.
        _t12_open_cabin(page, base, "view-linking")
        assert "تحویل" in page.inner_text("#linking-handoff-next")
        assert page.evaluate(
            "!!document.getElementById(\"queue-err\")") is True
        assert page.evaluate(
            "!!document.querySelector(\"#queue-list\")") is True
        bare = page.evaluate(
            "[...document.querySelectorAll("
            "'#view-linking #m-agree, #view-linking #m-saved')]"
            ".filter(el => el.textContent.trim() === \"—\""
            " && !(el.title && el.title.length > 0)).length")
        assert bare == 0, bare
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t12_02_server_buttons_busy_live_browser(live_console):
    """IT-T12-02: every server button shows busy, no double-click."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        for cabin in ("precard", "pilot"):
            _t12_open_cabin(page, base, "view-" + cabin)
            page.click("#%s-start" % cabin)
            page.wait_for_function(
                "document.getElementById(\"%s-start\")"
                ".textContent.includes(\"در حال شروع\")" % cabin,
                timeout=5000)
            assert page.is_disabled("#%s-start" % cabin), cabin
            page.wait_for_selector(
                "#%s-err .form-error" % cabin, timeout=10000)

        def _slow(route):
            time.sleep(0.9)
            route.continue_()

        page.route("**/api/screened*", _slow)
        # NOTE: explicit nav (not a bare goto) — view-memory from the
        # precard/pilot loop above would otherwise reopen a hidden view.
        _t12_open_cabin(page, base, "view-linking")
        # P5/R2: queue lives in tab 0 (hidden until its tab opens).
        page.click('#view-linking .cockpit-tabs .tab-link[data-tab-index="0"]')
        page.wait_for_selector("#queue-list .queue-item", timeout=15000)
        page.click("#btn-refresh-screened")
        page.wait_for_function(
            "document.getElementById(\"btn-refresh-screened\")"
            ".textContent.includes(\"در حال\")",
            timeout=5000)
        assert page.is_disabled("#btn-refresh-screened")
        page.wait_for_function(
            "!document.getElementById(\"btn-refresh-screened\").disabled",
            timeout=15000)
        # R5: clean reload of the default input — no event-arg garbage.
        page.wait_for_function(
            "document.getElementById(\"handoff-path\")"
            ".textContent.includes(\"screened.jsonl\")",
            timeout=15000)
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t12_03_handoff_banner_per_output_live_browser(live_console):
    """IT-T12-03: completed output → banner with path + next button."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/screening/status",
                   lambda route: route.fulfill(
                       status=200, content_type="application/json",
                       body=json.dumps(_t07_completed_body())))
        _t12_open_cabin(page, base, "view-screening")
        page.wait_for_function(
            "!document.getElementById(\"screening-handoff\").disabled",
            timeout=15000)
        assert page.is_visible("#screening-handoff-banner")
        assert "/tmp/t07-out" in \
            page.inner_text("#screening-handoff-banner")
        page.unroute("**/api/screening/status")
        # Linking: real screened load arms the strip + next button.
        _t12_open_cabin(page, base, "view-linking")
        page.wait_for_function(
            "document.getElementById(\"handoff-path\")"
            ".textContent.includes(\"screened.jsonl\")",
            timeout=15000)
        assert page.is_visible("#linking-handoff-next")
        page.click("#linking-handoff-next")
        page.wait_for_selector("#view-precard.active", timeout=5000)
        # Precard/pilot: hidden banner DOM parity (path slot + next).
        for cabin in ("precard", "pilot"):
            _t12_open_cabin(page, base, "view-" + cabin)
            assert page.evaluate(
                "document.getElementById(\"%s-handoff-banner\")"
                ".hasAttribute(\"hidden\")" % cabin) is True
            assert "تحویل" in page.inner_text(
                "#%s-handoff-next" % cabin), cabin
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t12_04_errors_in_three_part_box_live_browser(live_console):
    """IT-T12-04: every error lands in the 3-part box (retry + copy)."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        _t12_open_cabin(page, base, "view-precard")
        page.click("#precard-start")
        page.wait_for_selector("#precard-err .form-error", timeout=10000)
        code = page.eval_on_selector(
            "#precard-err .form-error", "el => el.getAttribute(\"data-code\")")
        assert code, code
        btns = page.evaluate(
            "[...document.querySelectorAll("
            "\"#precard-err .form-error-actions button\")]"
            ".map(b=>b.textContent)")
        assert any("تلاش دوباره" in b for b in btns), btns
        assert any("کپی گزارش" in b for b in btns), btns
        # Retry re-arms busy → error again.
        page.click(
            "#precard-err .form-error-actions "
            "button:has-text(\"تلاش دوباره\")")
        page.wait_for_function(
            "document.getElementById(\"precard-start\")"
            ".textContent.includes(\"در حال شروع\")",
            timeout=5000)
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()
    # Linking: forced 500 → queue-err box; retry after unroute clears it.
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/screened*",
                   lambda route: route.fulfill(
                       status=500, content_type="application/json",
                       body=json.dumps({"error": "t12 forced"})))
        page.goto(base + "/")
        # Queue-err lives in tab 0 (the queue panel).
        page.click('#view-linking .cockpit-tabs .tab-link[data-tab-index="0"]')
        page.wait_for_selector("#queue-err .form-error", timeout=15000)
        page.unroute("**/api/screened*")
        page.click(
            "#queue-err .form-error-actions "
            "button:has-text(\"تلاش دوباره\")")
        page.wait_for_function(
            "document.getElementById(\"queue-err\")"
            ".textContent.trim() === \"\"",
            timeout=15000)
        # The 500 above is deliberately injected to prove the error box
        # (the UI handles it — box + retry proven just above), so its
        # browser resource line is excused like the keyless-env 502/503s.
        assert not crashes, crashes
        odd = [e for e in errors if not (
            "Failed to load resource" in e
            and (" 500" in e or " 502" in e or " 503" in e))]
        assert not odd, odd
    finally:
        page.close()


def test_t12_cabins_desktop_shot_live_browser(live_console):
    """Desktop 1440px: visit all cabins, screenshot the conformance card."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        for view in ("view-screening", "view-linking",
                     "view-pilot", "view-precard"):
            _t12_open_cabin(page, base, view)
        assert page.is_visible("#precard-card")
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _t12_shots_dir(live_console), "shot-t12-cabins-desktop.png"))
    finally:
        page.close()


def test_t12_cabins_tablet_shot_live_browser(live_console):
    """Tablet 820px: cabins via hamburger, screenshot the pilot card."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    errs, crashes = [], []
    page.on("console",
            lambda msg: errs.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        for view in ("view-screening", "view-linking",
                     "view-precard", "view-pilot"):
            _t12_open_cabin(page, base, view, via_menu=True)
        assert page.is_visible("#pilot-card")
        assert not crashes, crashes
        odd = [e for e in errs if not (
            "Failed to load resource" in e
            and (" 502" in e or " 503" in e))]
        assert not odd, odd
        page.screenshot(path=os.path.join(
            _t12_shots_dir(live_console), "shot-t12-cabins-tablet.png"))
    finally:
        page.close()


# ── T04 reconnect gaps (IT-T04-01..03) + T05 corrupt-skip (IT-T05-03) ──
# T07-04 proves resume-shape rendering but never reloads the page; T08-01
# and T08-03 already cover IT-T05-01 (list) and IT-T05-02 (handoff), so
# only the four gaps below are added — no duplicates.
def _t04_spawn_isolated_console(tmpdir):
    """Fresh REAL console on its own DATA_ROOT (restart-recovery pattern).

    Returns (proc, base, root). Caller must stop the proc (terminate,
    bounded wait, kill fallback) — mirrors the live_console teardown.
    """
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    from factory.webui import run_status as _run_status  # noqa: F401
    root = os.path.join(tmpdir, "data-root")
    os.makedirs(root, exist_ok=True)
    screened = os.path.join(tmpdir, "screened.jsonl")
    with open(screened, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(
            {"lemma": "run",
             "sense": {"sense_id": "run#1"}}) + "\n")
    run_path = os.path.join(tmpdir, "candidates.json")
    with open(run_path, "w", encoding="utf-8") as handle:
        json.dump({}, handle)
    table_path = os.path.join(tmpdir, "table.tsv")
    with open(table_path, "w", encoding="utf-8") as handle:
        handle.write("sense_id\twordnet_sensekey\tmethod\tevidence\n")
    port = _free_port()
    assert port != 5561, "must run on an alternate port, never the default"
    env = dict(os.environ)
    env["HAMZABAN_DATA_ROOT"] = root
    env["HAMZABAN_SCREENED_PATH"] = screened
    env["HAMZABAN_LINK_TABLE"] = table_path
    env["HAMZABAN_CANDIDATES_RUN"] = run_path
    log_handle = open(os.path.join(tmpdir, "server2.log"), "ab")
    proc = subprocess.Popen(
        [sys.executable, SERVER_PATH,
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=PROJECT_ROOT, env=env,
        stdout=log_handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, close_fds=True)
    base = "http://127.0.0.1:%d" % port
    try:
        _wait_ready(base)
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass
        log_handle.close()
        raise
    return proc, base, root, log_handle


def _t04_stop(proc, log_handle):
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:
        pass
    try:
        log_handle.close()
    except Exception:
        pass


def test_t04_01_reload_mid_run_resumes_live_browser(
        live_console, tmp_path):
    """IT-T04-01: real reload mid-run → same run resumes with log tail."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)

    def status_route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"screening": {
                          "status": "running", "run_id": "t04-reload",
                          "resumed": True, "pid": 4242, "exit_code": None,
                          "elapsed": None,
                          "elapsed_human": "2 \u062f\u0642\u06cc\u0642\u0647",
                          "started_iso": "2026-09-27T00:00:00+00:00",
                          "words": [], "out_dir": "/tmp/t04-out",
                          "log": ["tail-line-6", "tail-line-7"],
                          "manifest": None, "note": ""}}))

    try:
        page.route("**/api/screening/status", status_route)
        _t07_open_screening(page, base)
        page.wait_for_function(
            "document.getElementById('screening-log')"
            ".textContent.includes('tail-line-7')",
            timeout=10000)
        page.reload()  # the gap T07-04 never exercises: a real reload
        _t07_open_screening(page, base)
        page.wait_for_function(
            "document.getElementById('screening-state')"
            ".textContent.includes('\u062f\u0631 \u062d\u0627\u0644 \u0627\u062c\u0631\u0627')",
            timeout=10000)
        page.wait_for_function(
            "document.getElementById('screening-log')"
            ".textContent.includes('tail-line-7')",
            timeout=10000)
        assert page.is_visible("#screening-resumed")
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_t04_02_restart_console_recovers_run_live_browser(
        live_console, tmp_path):
    """IT-T04-02: fresh console proc + T04 disk file → run/started_iso/tail.

    The isolated server never ran anything in-memory: the ONLY state is
    the real run_status disk record + the real screening.log tail, so a
    resumed running view proves restart recovery (no stubs anywhere).
    """
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    from factory.webui import run_status as _run_status
    browser = live_console["browser"]
    tmpdir = str(tmp_path)
    proc, base2, root, log_handle = _t04_spawn_isolated_console(tmpdir)
    try:
        out_dir = os.path.join(root, "proof-linker", "screened")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "screening.log"),
                  "w", encoding="utf-8") as handle:
            handle.write("boot-line-1\ntail-line-6\ntail-line-7\n")
        _run_status.write(root, "screening", {
            "run_id": "t04-restart", "pid": os.getpid(),
            "started_iso": "2026-09-27T00:00:00+00:00",
            "out_dir": out_dir, "out_name": "t04-restart",
            "words_hash": "ev", "status": "running"})
        with urllib.request.urlopen(
                base2 + "/api/screening/status", timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))["screening"]
        assert body["run_id"] == "t04-restart", body
        assert body["started_iso"] == "2026-09-27T00:00:00+00:00", body
        assert "tail-line-7" in (body["log"] or []), body
        page, errors, crashes = _t07_new_page(browser)
        try:
            _t07_open_screening(page, base2)
            page.wait_for_function(
                "document.getElementById('screening-state')"
                ".textContent.includes('\u062f\u0631 \u062d\u0627\u0644 \u0627\u062c\u0631\u0627')",
                timeout=10000)
            page.wait_for_function(
                "document.getElementById('screening-log')"
                ".textContent.includes('tail-line-7')",
                timeout=10000)
            assert page.is_visible("#screening-resumed")
            _t07_assert_clean(errors, crashes)
        finally:
            page.close()
    finally:
        _t04_stop(proc, log_handle)


def test_t04_03_completed_reload_shows_final_live_browser(
        live_console, tmp_path):
    """IT-T04-03: completed run → real reload keeps final metrics (no idle)."""
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    from factory.webui import run_status as _run_status
    browser = live_console["browser"]
    tmpdir = str(tmp_path)
    proc, base2, root, log_handle = _t04_spawn_isolated_console(tmpdir)
    try:
        out_dir = os.path.join(root, "proof-linker", "screened")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "screened.manifest.json"),
                  "w", encoding="utf-8") as handle:
            json.dump({"kept_total": 12, "dropped_total": 8,
                       "per_lemma": [
                           {"lemma": "run", "input_senses": 10,
                            "kept": 7, "dropped": 3}],
                       "drop_reasons": {"twin_r3": 5, "proper_r2": 2,
                                        "other": 1}}, handle)
        _run_status.write(root, "screening", {
            "run_id": "t04-final", "pid": 4242,
            "started_iso": "2026-09-27T00:00:00+00:00",
            "out_dir": out_dir, "out_name": "t04-final",
            "words_hash": "ev", "status": "completed"})
        page, errors, crashes = _t07_new_page(browser)
        try:
            _t07_open_screening(page, base2)
            page.wait_for_function(
                "document.getElementById('screening-m-kept')"
                ".textContent.trim() !== '\u2014'",
                timeout=15000)
            assert _norm_digits(
                page.inner_text("#screening-m-kept")) == "12"
            page.reload()  # completed state must survive a real reload
            _t07_open_screening(page, base2)
            page.wait_for_function(
                "document.getElementById('screening-m-kept')"
                ".textContent.trim() !== '\u2014'",
                timeout=15000)
            assert _norm_digits(
                page.inner_text("#screening-m-kept")) == "12"
            assert _norm_digits(
                page.inner_text("#screening-m-twins")) == "5"
            idle = page.inner_text("#screening-state")
            assert "\u062a\u06a9\u0645\u06cc\u0644" in idle, idle
            _t07_assert_clean(errors, crashes)
        finally:
            page.close()
    finally:
        _t04_stop(proc, log_handle)


def test_t05_03_corrupt_run_skipped_live_browser(
        live_console, tmp_path):
    """IT-T05-03: corrupt run dirs skipped + counted, never a 500."""
    browser = live_console["browser"]
    tmpdir = str(tmp_path)
    proc, base2, root, log_handle = _t04_spawn_isolated_console(tmpdir)
    try:
        runs = os.path.join(root, "webui", "screening_runs")
        good = os.path.join(runs, "t05-good")
        os.makedirs(good, exist_ok=True)
        with open(os.path.join(good, "run.json"),
                  "w", encoding="utf-8") as handle:
            json.dump({"run_id": "t05-good", "out_name": "t05-good",
                       "out_dir": "/tmp/t05-good",
                       "started_iso": "2026-09-27T00:00:00+00:00",
                       "status": "completed",
                       "kept_total": 5, "dropped_total": 6}, handle)
        bad = os.path.join(runs, "t05-bad")
        os.makedirs(bad, exist_ok=True)
        with open(os.path.join(bad, "run.json"),
                  "w", encoding="utf-8") as handle:
            handle.write("{not json")
        noid = os.path.join(runs, "t05-noid")
        os.makedirs(noid, exist_ok=True)
        with open(os.path.join(noid, "run.json"),
                  "w", encoding="utf-8") as handle:
            json.dump({"out_name": "x"}, handle)
        with urllib.request.urlopen(
                base2 + "/api/runs/history?cabin=screening",
                timeout=10) as resp:
            assert resp.status == 200, resp.status  # never a 500
            payload = json.loads(resp.read().decode("utf-8"))
        assert [r["run_id"] for r in payload["runs"]] == ["t05-good"]
        assert payload["skipped"] == 2, payload
        page, errors, crashes = _t07_new_page(browser)
        try:
            _t07_open_screening(page, base2)
            page.click("#screening-tabbtn-2")
            page.wait_for_function(
                "document.querySelectorAll("
                "'#screening-history-tbody tr[data-run-id]').length === 1",
                timeout=15000)
            assert "t05-good" in \
                page.inner_text("#screening-history-tbody")
            _t07_assert_clean(errors, crashes)
        finally:
            page.close()
    finally:
        _t04_stop(proc, log_handle)


# ── Wave 1 / P03: sticky control + inner workspace scroll (PUX-B5+B6) ──
# IT-BC03-01 (control rect fixed after workspace scroll, action buttons
# clickable without page scroll) + IT-BC03-02 (Tab reaches all three
# action buttons without moving the page) + desktop no-page-scroll cap.
def test_screening_sticky_control_inner_scroll_live_browser(live_console):
    """Control column fixed while workspace scrolls; no page-level scroll."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        page.goto(base + "/")
        page.click(
            'button.nav-btn[data-view-target="view-screening"]')
        page.wait_for_selector("#screening-controls", timeout=15000)
        page.wait_for_timeout(600)
        # Tall-content load: pad the per-lemma table so the workspace
        # genuinely overflows (otherwise the scroll below is a no-op and
        # the rect assertions below prove nothing).
        page.evaluate(
            "const tb = document.getElementById("
            "'screening-per-lemma-tbody');"
            " for (let i = 0; i < 200; i++) {"
            " const tr = document.createElement('tr');"
            " const td = document.createElement('td');"
            " td.textContent = 'filler-lemma-' + i;"
            " tr.append(td); tb.append(tr); }")
        page.wait_for_timeout(300)
        overflow = page.evaluate(
            "(() => { const w = document.querySelector("
            "'main.workspace-area');"
            " return w.scrollHeight - w.clientHeight; })()")
        assert overflow > 200, overflow
        before = page.evaluate(
            "document.getElementById('screening-controls')"
            ".getBoundingClientRect().top")
        page.evaluate(
            "const w = document.querySelector('main.workspace-area');"
            " w.scrollTo(0, w.scrollHeight);")
        page.wait_for_timeout(400)
        stuck1 = page.evaluate(
            "document.getElementById('screening-controls')"
            ".getBoundingClientRect().top")
        page.evaluate(
            "const w = document.querySelector('main.workspace-area');"
            " w.scrollTo(0, w.scrollHeight - 200);")
        page.wait_for_timeout(400)
        stuck2 = page.evaluate(
            "document.getElementById('screening-controls')"
            ".getBoundingClientRect().top")
        # Pinned once stuck: two deep scroll positions, one rect; and the
        # stuck position is at/above the natural position (never scrolled
        # away with the content).
        assert abs(stuck1 - stuck2) <= 2, (stuck1, stuck2)
        assert stuck1 <= before + 2, (before, stuck1)
        boxes = page.evaluate(
            "() => {"
            "  const vh = window.innerHeight;"
            "  return ['screening-start', 'screening-abort',"
            "    'screening-handoff'].map((id) => {"
            "    const r = document.getElementById(id)"
            "      .getBoundingClientRect();"
            "    return {id, top: r.top, bottom: r.bottom, vh};"
            "  });"
            "}")
        for box in boxes:
            assert box["top"] >= 0, box
            assert box["bottom"] <= box["vh"] + 1, box
        page_scroll = page.evaluate(
            "document.documentElement.scrollHeight - window.innerHeight")
        assert page_scroll <= 8, page_scroll
        # IT-BC03-02: keyboard-only Tab reaches all three action buttons
        # without moving the page. (abort/handoff are runtime-disabled
        # until a run starts, so the test enables them to traverse the
        # layout order — the assertion is about scroll, not run state.)
        page.evaluate(
            "['screening-start', 'screening-abort', 'screening-handoff']"
            ".forEach((id) => { document.getElementById(id)"
            ".removeAttribute('disabled'); });")
        page.evaluate("document.getElementById('screening-start').focus()")
        page_top = page.evaluate("window.scrollY")
        seen = []
        for _ in range(2):
            page.keyboard.press("Tab")
            page.wait_for_timeout(150)
            seen.append(page.evaluate(
                "document.activeElement && document.activeElement.id"))
        assert page.evaluate("window.scrollY") == page_top, seen
        assert seen == ["screening-abort", "screening-handoff"], seen
    finally:
        page.close()


def _bc03_shots_dir():
    return os.environ.get("BC03_SHOTS_DIR") or os.path.join(
        PROJECT_ROOT, ".opencode", "plans", "factory", "shots")


def _bc03_open_cabin(page, base, view, via_menu=False):
    page.goto(base + "/")
    page.wait_for_selector(
        'button.nav-btn[data-view-target="%s"]' % view, timeout=15000)
    if via_menu:  # tablet: nav lives behind the hamburger toggle
        page.click("#menu-toggle-btn")
        page.wait_for_timeout(400)
    page.click('button.nav-btn[data-view-target="%s"]' % view)
    page.wait_for_selector("#%s.active" % view, timeout=15000)
    page.wait_for_timeout(400)


# IT-BC03-03 (tab-level): every cabin keeps its own sticky control +
# inner scroll — switch tabs, each cabin's action buttons stay visible
# with no page-level scroll.
def test_cabins_sticky_control_per_tab_live_browser(live_console):
    """Each cabin tab keeps sticky control + inner scroll, no page scroll."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        # Linking has queue-driven intake (no start/abort trio): its
        # sticky control is the inspector column + inner-scrolling queue.
        cabins = [
            ("view-screening", "#screening-controls",
             ["screening-start", "screening-abort", "screening-handoff"]),
            ("view-linking", ".inspector-column", []),
            ("view-precard", "#precard-actions",
             ["precard-start", "precard-abort", "precard-handoff"]),
            ("view-pilot", "#pilot-actions",
             ["pilot-start", "pilot-abort", "pilot-handoff"]),
        ]
        for view, control_sel, buttons in cabins:
            _bc03_open_cabin(page, base, view)
            sticky = page.evaluate(
                "(sel) => { const el = document.querySelector(sel);"
                " if (!el) return 'missing:' + sel;"
                " return getComputedStyle(el).position; }", control_sel)
            assert sticky == "sticky", (view, control_sel, sticky)
            page_scroll = page.evaluate(
                "document.documentElement.scrollHeight - window.innerHeight")
            assert page_scroll <= 8, (view, page_scroll)
            boxes = page.evaluate(
                "(ids) => ids.map((id) => { const el ="
                " document.getElementById(id); if (!el) return {id, miss: 1};"
                " const r = el.getBoundingClientRect();"
                " return {id, top: r.top, bottom: r.bottom,"
                " vh: window.innerHeight}; })", buttons)
            for box in boxes:
                assert not box.get("miss"), (view, box)
                assert box["top"] >= 0, (view, box)
                assert box["bottom"] <= box["vh"] + 1, (view, box)
            if view == "view-linking":
                queue_scroll = page.evaluate(
                    "() => { const q = document.getElementById("
                    "'batch-review-list'); if (!q) return 'missing';"
                    " return getComputedStyle(q).overflowY; }")
                assert queue_scroll == "auto", queue_scroll
    finally:
        page.close()


def test_bc03_layout_desktop_shot_live_browser(live_console):
    """Desktop 1280px: tall screening workspace, shot proves sticky."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        _bc03_open_cabin(page, base, "view-screening")
        page.evaluate(
            "const tb = document.getElementById("
            "'screening-per-lemma-tbody');"
            " for (let i = 0; i < 200; i++) {"
            " const tr = document.createElement('tr');"
            " const td = document.createElement('td');"
            " td.textContent = 'filler-lemma-' + i;"
            " tr.append(td); tb.append(tr); }")
        page.evaluate(
            "const w = document.querySelector('main.workspace-area');"
            " w.scrollTo(0, w.scrollHeight);")
        page.wait_for_timeout(400)
        page.screenshot(path=os.path.join(
            _bc03_shots_dir(), "shot-bc-p03-layout-desktop.png"))
    finally:
        page.close()


def test_bc03_layout_tablet_shot_live_browser(live_console):
    """Tablet 820px: screening cabin via hamburger, shot proves control."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    try:
        _bc03_open_cabin(page, base, "view-screening", via_menu=True)
        assert page.is_visible("#screening-controls")
        page.screenshot(path=os.path.join(
            _bc03_shots_dir(), "shot-bc-p03-layout-tablet.png"))
    finally:
        page.close()


# ── P04 unified file/history manager (IT-BC04-01..04) ──
# Live Chromium against the live console server. /api/files/roots is
# stubbed at the HTTP layer ONLY to shape per-root facts (the server
# shape itself is proven hermetically in test_webui_data_root.py);
# words/resolve/pins hit the REAL server. The global files key carries
# a decoy — any global-repeat regression fails the negative asserts.
def _bc04_shots_dir():
    return os.environ.get("BC04_SHOTS_DIR") or os.path.join(
        PROJECT_ROOT, ".opencode", "plans", "factory", "shots")


def _bc04_facts(size, lines_label, mtime_relative, path="/tmp/bc04.jsonl"):
    return {"path": path, "exists": True, "size": size,
            "lines": 0, "lines_label": lines_label, "truncated": False,
            "mtime_iso": "2026-09-27T00:00:00+00:00",
            "mtime_relative": mtime_relative,
            "mtime_detail": "شمسی ۱۴۰۵/۰۷/۰۵ • میلادی 2026-09-27",
            "cause": ""}


def _bc04_roots_route(roots):
    def _route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"roots": roots,
                                       "files": _t10_files(True, True)}))
    return _route


def test_bc04_01_rows_show_own_root_facts_live_browser(live_console):
    """IT-BC04-01: two differing roots → each row shows its own facts."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    roots = [
        {"path": tmpdir, "label": "bc04-a",
         "files": _bc04_facts(1111, "11", "۱ ساعت پیش",
                              os.path.join(tmpdir, "a.jsonl"))},
        {"path": os.path.join(tmpdir, "bc04-b"), "label": "bc04-b",
         "files": _bc04_facts(2222, "22", "۲ ساعت پیش",
                              os.path.join(tmpdir, "bc04-b",
                                           "b.jsonl"))},
    ]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/files/roots", _bc04_roots_route(roots))
        _t10_open_paths(page, base)
        page.wait_for_function(
            "document.getElementById('paths-tbody')"
            ".textContent.includes('۱۱۱۱')",
            timeout=10000)
        rows = page.evaluate(
            "[...document.querySelectorAll('#paths-tbody tr')]"
            ".map(tr => tr.textContent)")
        assert len(rows) == 2, rows
        assert "۱۱۱۱" in rows[0] and "۲۲۲۲" not in rows[0], rows
        assert "۲۲۲۲" in rows[1] and "۱۱۱۱" not in rows[1], rows
        assert "۱۱ سطر" in rows[0] and "۲۲ سطر" in rows[1], rows
        assert "۱ ساعت پیش" in rows[0], rows
        assert "۲ ساعت پیش" in rows[1], rows
        # global decoy never leaks into any row
        assert "۹۹۹۹۹" not in "".join(rows), rows
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc04_02_missing_file_titled_empty_live_browser(live_console):
    """IT-BC04-02: root without a file → titled — with cause, no bare."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    roots = [{"path": tmpdir, "label": "bc04-empty",
              "files": {"path": "", "exists": False, "size": 0,
                        "lines": 0, "lines_label": "0",
                        "truncated": False, "mtime_iso": None,
                        "mtime_relative": "—", "mtime_detail": "—",
                        "cause": "file-missing"}}]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/files/roots", _bc04_roots_route(roots))
        _t10_open_paths(page, base)
        page.wait_for_function(
            "document.querySelectorAll('#paths-tbody tr').length === 1",
            timeout=10000)
        bare = page.evaluate(
            "[...document.querySelectorAll('#paths-tbody td')]"
            ".filter(td=>td.textContent.trim() === '—'"
            " && !(td.title && td.title.length > 0)).length")
        assert bare == 0, bare
        titles = page.evaluate(
            "[...document.querySelectorAll("
            "'#paths-tbody td.honest-empty')].map(td=>td.title)")
        assert titles, titles
        assert any("فایلی در این ریشه نیست" in t for t in titles), titles
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def _bc04_open_dest_dialog(page, base, tmpdir):
    page.route("**/api/files/roots", _t09_roots_route(tmpdir))
    _t07_open_screening(page, base)
    # P05: pick opens the popover; the full browser (with the P04
    # preset + free-text block) comes from «مرور کامل…» after the
    # async groups settle (same lost-click race guard as T09).
    page.click("#screening-pick-dest")
    page.wait_for_selector(
        "#cmd-popover:not([hidden])", timeout=10000)
    page.wait_for_function(
        "document.querySelectorAll('#cmd-popover li').length >= 3",
        timeout=15000)
    page.click("#cmd-popover-browse")
    page.wait_for_selector(
        "#data-dialog:not([hidden])", timeout=10000)
    page.wait_for_function(
        "document.querySelectorAll("
        "'#data-dialog-preset option').length > 1",
        timeout=15000)


def _bc04_reopen_dest_dialog(page):
    """Re-open the full dest browser through the P05 popover."""
    page.click("#screening-pick-dest")
    page.wait_for_selector(
        "#cmd-popover:not([hidden])", timeout=10000)
    page.wait_for_function(
        "document.querySelectorAll('#cmd-popover li').length >= 3",
        timeout=15000)
    page.click("#cmd-popover-browse")
    page.wait_for_selector(
        "#data-dialog:not([hidden])", timeout=10000)
    page.wait_for_function(
        "document.querySelectorAll("
        "'#data-dialog-preset option').length > 1",
        timeout=15000)


def test_bc04_03_preset_custom_picks_live_browser(live_console):
    """IT-BC04-03: preset pick fills; custom valid fills; custom invalid
    → fa error with no pick."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _, dest = _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        _bc04_open_dest_dialog(page, base, tmpdir)
        # preset pick → input fills with the resolved abspath
        page.select_option("#data-dialog-preset", tmpdir)
        page.click("#data-dialog-preset-pick")
        page.wait_for_function(
            "document.getElementById('data-dialog')"
            ".hasAttribute('hidden')",
            timeout=10000)
        assert os.path.abspath(
            page.input_value("#screening-out-dir")) == os.path.abspath(
                tmpdir)
        assert page.evaluate("document.activeElement.id") == \
            "screening-out-dir"
        # custom valid path → validated + fills
        _bc04_reopen_dest_dialog(page)
        page.fill("#data-dialog-custom", dest)
        page.click("#data-dialog-custom-pick")
        page.wait_for_function(
            "document.getElementById('data-dialog')"
            ".hasAttribute('hidden')",
            timeout=10000)
        assert os.path.abspath(
            page.input_value("#screening-out-dir")) == os.path.abspath(
                dest)
        # custom invalid path → fa error, no pick, dialog stays open
        _bc04_reopen_dest_dialog(page)
        page.fill("#data-dialog-custom", "/bc04-outside-allowlist-xyz")
        page.click("#data-dialog-custom-pick")
        page.wait_for_function(
            "document.getElementById('data-dialog-err')"
            ".textContent.includes('ریشه‌های مجاز')",
            timeout=10000)
        assert os.path.abspath(
            page.input_value("#screening-out-dir")) == os.path.abspath(
                dest)
        assert page.evaluate(
            "!document.getElementById('data-dialog')"
            ".hasAttribute('hidden')") is True
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc04_04_same_manager_recents_live_browser(live_console):
    """IT-BC04-04: preset + custom picks both land through the same
    manager (one recents list, no second picker dialect)."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _, dest = _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        _bc04_open_dest_dialog(page, base, tmpdir)
        page.select_option("#data-dialog-preset", tmpdir)
        page.click("#data-dialog-preset-pick")
        page.wait_for_function(
            "document.getElementById('data-dialog')"
            ".hasAttribute('hidden')",
            timeout=10000)
        _bc04_reopen_dest_dialog(page)
        page.fill("#data-dialog-custom", dest)
        page.click("#data-dialog-custom-pick")
        page.wait_for_function(
            "document.getElementById('data-dialog')"
            ".hasAttribute('hidden')",
            timeout=10000)
        recents = page.evaluate(
            "JSON.parse(localStorage.getItem('hz-file-recents') || '[]')"
            ".map(r => r.path)")
        assert os.path.abspath(tmpdir) in [
            os.path.abspath(p) for p in recents], recents
        assert os.path.abspath(dest) in [
            os.path.abspath(p) for p in recents], recents
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc04_manager_desktop_shot_live_browser(live_console):
    """Desktop 1440px: dest dialog with preset + free-text block (shot)."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        _bc04_open_dest_dialog(page, base, tmpdir)
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _bc04_shots_dir(), "shot-bc-p04-manager-desktop.png"))
    finally:
        page.close()


def test_bc04_manager_tablet_shot_live_browser(live_console):
    """Tablet 820px: dest dialog via hamburger (shot)."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        page.route("**/api/files/roots", _t09_roots_route(tmpdir))
        _t07_open_screening(page, base, via_menu=True)
        # tablet: A1–A4 accordion is single-open — expand A2 (dest) so
        # the caller button is visible (same pattern as IT-T09-05)
        page.click("#screening-acc-a2 > summary")
        page.wait_for_timeout(400)
        page.click("#screening-pick-dest")
        page.wait_for_selector(
            "#cmd-popover:not([hidden])", timeout=10000)
        page.wait_for_function(
            "document.querySelectorAll('#cmd-popover li').length >= 3",
            timeout=15000)
        page.click("#cmd-popover-browse")
        page.wait_for_selector(
            "#data-dialog:not([hidden])", timeout=10000)
        assert page.is_visible("#data-dialog-custom-pick")
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _bc04_shots_dir(), "shot-bc-p04-manager-tablet.png"))
    finally:
        page.close()


# ── P05 anchored picking-only popover (IT-BC05-01..05) ──
# Live Chromium against the live console server. /api/files/roots is
# stubbed at the HTTP layer ONLY to shape roots/facts (server shape is
# proven hermetically); words/resolve/pins hit the REAL server. The
# popover never mutates: the tests assert zero POST/PUT/DELETE while it
# is open and no action buttons inside it.
def _bc05_shots_dir():
    return os.environ.get("BC05_SHOTS_DIR") or os.path.join(
        PROJECT_ROOT, ".opencode", "plans", "factory", "shots")


def _bc05_open_popover(page, base, tmpdir, pick_id="screening-pick-input"):
    page.route("**/api/files/roots", _t09_roots_route(tmpdir))
    _t07_open_screening(page, base)
    page.click("#" + pick_id)
    page.wait_for_selector(
        "#cmd-popover:not([hidden])", timeout=10000)
    page.wait_for_function(
        "document.querySelectorAll('#cmd-popover li').length >= 3",
        timeout=15000)


def test_bc05_01_popover_anchored_no_column_live_browser(live_console):
    """IT-BC05-01: click «انتخاب فایل…» → transient layer anchored at
    the button; page grid unchanged; control column never covered."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        grid_before = None
        page.route("**/api/files/roots", _t09_roots_route(tmpdir))
        _t07_open_screening(page, base)
        grid_before = page.evaluate(
            "getComputedStyle(document.querySelector("
            "'main.workspace-area')).overflowY")
        page.click("#screening-pick-input")
        page.wait_for_selector(
            "#cmd-popover:not([hidden])", timeout=10000)
        # transient layer, not a layout column: fixed positioning, the
        # full dialog stays hidden, no dialog body class is added
        pos = page.evaluate(
            "getComputedStyle(document.getElementById("
            "'cmd-popover')).position")
        assert pos == "fixed", pos
        assert page.evaluate(
            "document.getElementById('data-dialog')"
            ".hasAttribute('hidden')") is True
        assert page.evaluate(
            "document.body.classList.contains('has-data-dialog')") \
            is False
        assert page.evaluate(
            "getComputedStyle(document.querySelector("
            "'main.workspace-area')).overflowY") == grid_before
        # anchored at the button (nearby) and inside the viewport
        gap = page.evaluate(
            "() => {"
            "  const p = document.getElementById('cmd-popover')"
            "    .getBoundingClientRect();"
            "  const b = document.getElementById('screening-pick-input')"
            "    .getBoundingClientRect();"
            "  const vh = window.innerHeight, vw = window.innerWidth;"
            "  return {dx: Math.min(Math.abs(p.left - b.left),"
            "    Math.abs(p.right - b.right)),"
            "    inside: p.top >= 0 && p.left >= 0"
            "      && p.bottom <= vh + 1 && p.right <= vw + 1};"
            "}")
        assert gap["inside"] is True, gap
        assert gap["dx"] < 500, gap
        # never covers the control column
        cover = page.evaluate(
            "() => {"
            "  const p = document.getElementById('cmd-popover')"
            "    .getBoundingClientRect();"
            "  const c = document.getElementById('screening-controls')"
            "    .getBoundingClientRect();"
            "  return !(p.right <= c.left || p.left >= c.right"
            "    || p.bottom <= c.top || p.top >= c.bottom);"
            "}")
        assert cover is False, "popover must never cover the control column"
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc05_02_keyboard_only_cycle_pick_live_browser(live_console):
    """IT-BC05-02: keyboard-only — Tab stays in the layer, Up/Down
    cycles every row, Enter picks, focus returns to the invoker."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        _bc05_open_popover(page, base, tmpdir)
        # keyboard-only from here (no mouse): focus the invoker, open
        # with Enter, then Tab stays on the single tab-stop
        page.keyboard.press("Escape")
        page.wait_for_function(
            "document.getElementById('cmd-popover')"
            ".hasAttribute('hidden')",
            timeout=5000)
        page.evaluate(
            "document.getElementById('screening-pick-input').focus()")
        page.keyboard.press("Enter")
        page.wait_for_selector(
            "#cmd-popover:not([hidden])", timeout=10000)
        page.wait_for_function(
            "document.activeElement.id === 'cmd-popover-filter'",
            timeout=5000)
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        assert page.evaluate("document.activeElement.id") == \
            "cmd-popover-filter"
        # cycle: walk every row with Down (null-safe), then prove the
        # wrap lands on «مرور کامل…» and cycles back to the first row
        total = page.evaluate(
            "document.querySelectorAll("
            "'#cmd-popover li.cmd-row:not(.cmd-disabled)').length")
        assert total >= 1, total
        seen = set()
        for _ in range(total):
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(120)
            active = page.evaluate(
                "(() => { const n = document.querySelector("
                "'#cmd-popover li.cmd-row.active');"
                " return n ? n.textContent : null; })()")
            assert active, "every Down step must land on a row"
            seen.add(active)
        assert len(seen) == total, (len(seen), total)
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(120)
        assert page.evaluate(
            "document.getElementById('cmd-popover-browse')"
            ".classList.contains('active')") is True
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(120)
        assert page.evaluate(
            "document.querySelector("
            "'#cmd-popover li.cmd-row.active') !== null") is True
        # deterministic pick: narrow to the seeded words file, Down to
        # its row, Enter fills A1 and returns focus to the invoker
        page.fill("#cmd-popover-filter", "words-t09")
        page.wait_for_function(
            "document.querySelectorAll("
            "'#cmd-popover li.cmd-row:not(.cmd-disabled)').length === 1",
            timeout=5000)
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(150)
        # Enter picks the active row: words land in A1, popover closes,
        # focus returns to the invoking button
        page.keyboard.press("Enter")
        page.wait_for_function(
            "document.getElementById('cmd-popover')"
            ".hasAttribute('hidden')",
            timeout=10000)
        page.wait_for_function(
            "document.getElementById('screening-words-count')"
            ".textContent.trim() === '۳'",
            timeout=10000)
        assert "alpha" in page.input_value("#screening-words")
        assert page.evaluate("document.activeElement.id") == \
            "screening-pick-input"
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc05_03_escape_outside_cancel_live_browser(live_console):
    """IT-BC05-03: Escape / outside-click closes with no selection and
    focus back on the invoker."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        _bc05_open_popover(page, base, tmpdir)
        before = page.input_value("#screening-words")
        page.keyboard.press("Escape")
        page.wait_for_function(
            "document.getElementById('cmd-popover')"
            ".hasAttribute('hidden')",
            timeout=5000)
        assert page.input_value("#screening-words") == before
        assert page.evaluate("document.activeElement.id") == \
            "screening-pick-input"
        # outside-click: reopen, click the workspace nav, same outcome
        page.click("#screening-pick-input")
        page.wait_for_selector(
            "#cmd-popover:not([hidden])", timeout=10000)
        page.click('button.nav-btn[data-view-target="view-screening"]')
        page.wait_for_function(
            "document.getElementById('cmd-popover')"
            ".hasAttribute('hidden')",
            timeout=5000)
        assert page.input_value("#screening-words") == before
        assert page.evaluate("document.activeElement.id") == \
            "screening-pick-input"
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc05_04_filter_client_side_no_fetch_live_browser(live_console):
    """IT-BC05-04: typing filters all three groups with titled empties;
    zero server calls after the popover settles."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    calls = []
    page.on("request", lambda req: calls.append(
        (req.method, req.url)) if "/api/" in req.url else None)
    try:
        _bc05_open_popover(page, base, tmpdir)
        page.wait_for_timeout(800)
        del calls[:]
        # positive filter: the mocked root label matches in paths
        page.fill("#cmd-popover-filter", "t09")
        page.wait_for_function(
            "document.querySelector("
            "'section[data-group=\"paths\"]')"
            ".textContent.includes('t09')",
            timeout=5000)
        assert page.evaluate(
            "document.querySelectorAll("
            "'section[data-group=\"paths\"] li.cmd-row').length") >= 1
        # negative filter: every group shows a titled empty, none vanishes
        page.fill("#cmd-popover-filter", "bc05-no-such-row-xyz")
        page.wait_for_function(
            "document.querySelectorAll("
            "'#cmd-popover li.cmd-empty').length === 3",
            timeout=5000)
        titles = page.evaluate(
            "[...document.querySelectorAll("
            "'#cmd-popover li.cmd-empty')].map(li=>li.title)")
        assert all(len(t) > 0 for t in titles), titles
        groups = page.evaluate(
            "document.querySelectorAll("
            "'#cmd-popover section.cmd-group').length")
        assert groups == 3, groups
        assert calls == [], calls
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc05_05_picking_only_no_actions_live_browser(live_console):
    """IT-BC05-05: no action buttons inside; the whole session performs
    zero mutations (no POST/PUT/DELETE)."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _, dest = _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    mutating = []
    page.on("request", lambda req: mutating.append(
        (req.method, req.url))
        if req.method in ("POST", "PUT", "DELETE") else None)
    try:
        _bc05_open_popover(page, base, tmpdir, "screening-pick-dest")
        labels = page.evaluate(
            "[...document.querySelectorAll('#cmd-popover button')]"
            ".map(b=>b.textContent.trim())")
        for banned in ("ساخت پوشه", "بارگذاری", "تغییر نام", "حذف",
                       "سنجاق"):
            assert not any(banned in t for t in labels), labels
        # every row carries a usefulness sentence + an effect line, and
        # facts from its own root (fa) or a titled cause
        rows = page.evaluate(
            "[...document.querySelectorAll("
            "'#cmd-popover li.cmd-row')].map(li=>li.textContent)")
        assert rows, rows
        for text in rows:
            assert "می‌نشیند" in text, text  # effect line
        facts_titles = page.evaluate(
            "[...document.querySelectorAll("
            "'#cmd-popover .cmd-facts')].map(s=>s.title)")
        assert facts_titles and all(
            len(t) > 0 for t in facts_titles), facts_titles
        # picking a dest fills A2 with no mutation along the way
        page.fill("#cmd-popover-filter", "t09")
        page.wait_for_timeout(400)
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(150)
        page.keyboard.press("Enter")
        page.wait_for_function(
            "document.getElementById('cmd-popover')"
            ".hasAttribute('hidden')",
            timeout=10000)
        value = page.input_value("#screening-out-dir")
        assert value, value
        assert mutating == [], mutating
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc05_popover_desktop_shot_live_browser(live_console):
    """Desktop 1440px: anchored popover with three titled groups (shot)."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        _bc05_open_popover(page, base, tmpdir)
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _bc05_shots_dir(), "shot-bc-p05-popover-desktop.png"))
    finally:
        page.close()


def test_bc05_popover_tablet_shot_live_browser(live_console):
    """Tablet 820px: popover via hamburger + A1 accordion (shot)."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        page.route("**/api/files/roots", _t09_roots_route(tmpdir))
        _t07_open_screening(page, base, via_menu=True)
        # tablet accordion starts with A1 open — only expand when closed
        # (a blind summary click would toggle it shut, same trap as T09-05)
        if not page.evaluate(
                "document.getElementById('screening-acc-a1').open"):
            page.click("#screening-acc-a1 > summary")
            page.wait_for_timeout(400)
        page.click("#screening-pick-input")
        page.wait_for_selector(
            "#cmd-popover:not([hidden])", timeout=10000)
        assert page.is_visible("#cmd-popover-filter")
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _bc05_shots_dir(), "shot-bc-p05-popover-tablet.png"))
    finally:
        page.close()


# ── P06 shared paged list p50 + titled empties (IT-BC06-01..04) ──
# Live Chromium against the live console server. /api/screened,
# /api/runs/history and /api/screening/status are stubbed at the HTTP
# layer ONLY to shape list volume (server shapes are proven
# hermetically); candidates/labels/words hit the REAL server. The
# popover itself is untouched by P06 (its titled group-empty is only
# asserted, never restyled).
def _bc06_shots_dir():
    return os.environ.get("BC06_SHOTS_DIR") or os.path.join(
        PROJECT_ROOT, ".opencode", "plans", "factory", "shots")


def _bc06_screened_route(n):
    """Serve n flat queue rows shaped like the REAL /api/screened."""
    def _route(route):
        rows = [{"sense_id": "bc06#%d" % i,
                 "lemma": "lemma%d" % (i % 50),
                 "gloss": "sense gloss number %d" % i,
                 "example": "example sentence %d" % i}
                for i in range(1, n + 1)]
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(
                          {"rows": rows, "total": n, "path": "bc06-mock"}))
    return _route


def _bc06_history_route(runs):
    def _route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"runs": runs}))
    return _route


def _bc06_status_route(manifest):
    def _route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(
                          {"screening": {
                              "status": ("completed"
                                         if manifest is not None
                                         else "idle"),
                              "elapsed": None, "elapsed_human": None,
                              "started_iso": None, "run_id": None,
                              "resumed": False, "exit_code": None,
                              "log": [], "manifest": manifest,
                              "out_path": "", "words": []}}))
    return _route


def _bc06_open_linking(page, base, via_menu=False):
    page.goto(base + "/")
    page.wait_for_selector(
        'button.nav-btn[data-view-target="view-linking"]', timeout=15000)
    if via_menu:  # tablet/phone: nav lives behind the hamburger toggle
        page.click("#menu-toggle-btn")
        page.wait_for_timeout(400)
    page.click('button.nav-btn[data-view-target="view-linking"]')
    # P5/R2: the cabin opens on the persisted tab (default: supervised);
    # intake tests start from tab 0 explicitly.
    page.click('#view-linking .cockpit-tabs .tab-link[data-tab-index="0"]')
    page.wait_for_selector(
        "#queue-list .queue-item, #queue-list .p-meta", timeout=15000)
    page.wait_for_timeout(600)


def _bc06_queue_count(page):
    return page.evaluate(
        "document.querySelectorAll('#queue-list .queue-item').length")


def _bc06_first_queue_text(page):
    return page.evaluate(
        "document.querySelector('#queue-list .queue-item').textContent")


def test_bc06_01_paged_500_queue_live_browser(live_console):
    """IT-BC06-01: 500-row queue mounts one 50-row page; pager
    next/prev turns pages with an exact counter."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/screened", _bc06_screened_route(500))
        _bc06_open_linking(page, base)
        page.wait_for_function(
            "document.querySelectorAll("
            "'#queue-list .queue-item').length === 50",
            timeout=15000)
        assert _bc06_queue_count(page) == 50
        assert _norm_digits(
            page.inner_text("#queue-remaining")) == "500 از 500 مورد"
        assert page.evaluate(
            "document.getElementById('queue-pager')"
            ".hasAttribute('hidden')") is False
        assert _norm_digits(page.inner_text(
            "#queue-pager [data-pager='label']")) == "صفحه 1 از 10"
        first = _bc06_first_queue_text(page)
        assert "bc06#1" in first, first
        page.click("#queue-pager [data-pager='next']")
        page.wait_for_function(
            "document.querySelector("
            "'#queue-pager [data-pager=\"label\"]')"
            ".textContent.includes('۲')",
            timeout=5000)
        assert _bc06_queue_count(page) == 50
        second = _bc06_first_queue_text(page)
        assert "bc06#51" in second, second
        assert second != first
        assert _norm_digits(
            page.inner_text("#queue-remaining")) == "500 از 500 مورد"
        page.click("#queue-pager [data-pager='prev']")
        page.wait_for_function(
            "document.querySelector("
            "'#queue-pager [data-pager=\"label\"]')"
            ".textContent.includes('۱')",
            timeout=5000)
        assert _bc06_first_queue_text(page) == first
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc06_02_filter_spans_pages_live_browser(live_console):
    """IT-BC06-02: filter matches across all pages with an exact
    count; paging keeps the filter (no unfiltered leak)."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/screened", _bc06_screened_route(500))
        _bc06_open_linking(page, base)
        page.wait_for_function(
            "document.querySelectorAll("
            "'#queue-list .queue-item').length === 50",
            timeout=15000)
        # bc06#4 + bc06#40-49 + bc06#400-499 = 111 matches
        page.fill("#queue-filter", "bc06#4")
        page.wait_for_function(
            "document.getElementById('queue-remaining')"
            ".textContent.includes('۱۱۱')",
            timeout=5000)
        assert _norm_digits(
            page.inner_text("#queue-remaining")) == "111 از 500 مورد"
        assert _bc06_queue_count(page) == 50
        page.click("#queue-pager [data-pager='next']")
        page.wait_for_function(
            "document.querySelector("
            "'#queue-pager [data-pager=\"label\"]')"
            ".textContent.includes('۲')",
            timeout=5000)
        texts = page.evaluate(
            "[...document.querySelectorAll("
            "'#queue-list .queue-item')].map(el=>el.textContent)")
        assert len(texts) == 50, len(texts)
        assert all("bc06#4" in text for text in texts), texts[:3]
        assert _norm_digits(
            page.inner_text("#queue-remaining")) == "111 از 500 مورد"
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc06_03_keyboard_crosses_page_live_browser(live_console):
    """IT-BC06-03: Tab into the list, ArrowDown at the page edge
    turns the page via the pager; ArrowUp turns back; Enter
    still activates the focused row."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/screened", _bc06_screened_route(500))
        _bc06_open_linking(page, base)
        page.wait_for_function(
            "document.querySelectorAll("
            "'#queue-list .queue-item').length === 50",
            timeout=15000)
        page.evaluate(
            "document.querySelectorAll("
            "'#queue-list .queue-item')[49].focus()")
        assert "bc06#50" in page.evaluate(
            "document.activeElement.textContent")
        page.keyboard.press("ArrowDown")
        page.wait_for_function(
            "document.querySelector("
            "'#queue-pager [data-pager=\"label\"]')"
            ".textContent.includes('۲')",
            timeout=5000)
        focused = page.evaluate("document.activeElement.textContent")
        assert "bc06#51" in focused, focused
        page.keyboard.press("ArrowUp")
        page.wait_for_function(
            "document.querySelector("
            "'#queue-pager [data-pager=\"label\"]')"
            ".textContent.includes('۱')",
            timeout=5000)
        focused = page.evaluate("document.activeElement.textContent")
        assert "bc06#50" in focused, focused
        page.keyboard.press("Enter")
        # Enter activates the focused row: selection follows it (the
        # per-sense detail panel is gone with the manual form — the
        # queue's current-status marker carries the contract now).
        page.wait_for_function(
            "[...document.querySelectorAll('#queue-list .queue-item')]"
            ".filter(el=>el.textContent.includes('bc06#50')"
            " && el.textContent.includes('داوری جاری')).length === 1",
            timeout=5000)
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc06_04_six_empties_titled_live_browser(live_console):
    """IT-BC06-04: every one of the six empty states renders a fa
    sentence plus a title cause in the DOM."""
    browser, base = live_console["browser"], live_console["base"]
    # (a) queue no-rows: screened returns nothing
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/screened", _bc06_screened_route(0))
        _bc06_open_linking(page, base)
        page.wait_for_selector("#queue-list .p-meta", timeout=15000)
        empty = page.evaluate(
            "() => { const n = document.querySelector("
            "'#queue-list .p-meta');"
            " return {text: n.textContent, title: n.title}; }")
        assert len(empty["text"]) > 3, empty
        assert len(empty["title"]) > 3, empty
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()
    # (b) queue no-filter-match: rows exist, the filter matches none
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/screened", _bc06_screened_route(10))
        _bc06_open_linking(page, base)
        page.wait_for_function(
            "document.querySelectorAll("
            "'#queue-list .queue-item').length === 10",
            timeout=15000)
        page.fill("#queue-filter", "bc06-no-such-row-xyz")
        page.wait_for_selector("#queue-list .p-meta", timeout=5000)
        empty = page.evaluate(
            "() => { const n = document.querySelector("
            "'#queue-list .p-meta');"
            " return {text: n.textContent, title: n.title}; }")
        assert len(empty["text"]) > 3, empty
        assert len(empty["title"]) > 3, empty
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()
    # (c)+(d) history no-history + per-lemma no-rows on one page
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/runs/history*", _bc06_history_route([]))
        page.route("**/api/screening/status", _bc06_status_route(None))
        _t07_open_screening(page, base)
        page.click("#screening-tabbtn-2")
        page.wait_for_selector(
            "#screening-history-tbody td[title]", timeout=15000)
        hist = page.evaluate(
            "() => { const n = document.querySelector("
            "'#screening-history-tbody td');"
            " return {text: n.textContent, title: n.title}; }")
        assert len(hist["text"]) > 3, hist
        assert len(hist["title"]) > 3, hist
        lemma = page.evaluate(
            "() => { const n = document.querySelector("
            "'#screening-per-lemma-tbody td');"
            " return {text: n.textContent, title: n.title}; }")
        assert len(lemma["text"]) > 3, lemma
        assert len(lemma["title"]) > 3, lemma
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()
    # (e)+(f) popover group-empty + history missing-fact dash, one page
    tmpdir = live_console["tmpdir"]
    _t09_seed(tmpdir)
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/files/roots", _t09_roots_route(tmpdir))
        page.route("**/api/runs/history*", _bc06_history_route(
            [{"run_id": "", "out_name": "", "status": "completed",
              "out_dir": "", "started_iso": None,
              "kept_total": None, "dropped_total": None}]))
        _t07_open_screening(page, base)
        dash = page.evaluate(
            "[...document.querySelectorAll("
            "'#screening-history-tbody td')]"
            ".filter(td=>td.textContent.trim() === '—')"
            ".map(td=>td.title)")
        assert dash and all(len(t) > 0 for t in dash), dash
        _bc05_open_popover(page, base, tmpdir)
        page.fill("#cmd-popover-filter", "bc06-no-such-row-xyz")
        page.wait_for_function(
            "document.querySelectorAll("
            "'#cmd-popover li.cmd-empty').length === 3",
            timeout=5000)
        titles = page.evaluate(
            "[...document.querySelectorAll("
            "'#cmd-popover li.cmd-empty')].map(li=>li.title)")
        assert all(len(t) > 0 for t in titles), titles
        _t07_assert_clean(errors, crashes)
    finally:
        page.close()


def test_bc06_paged_desktop_shot_live_browser(live_console):
    """Desktop 1440px: 500-row queue shows one 50-row page plus
    the shared pager (shot)."""
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/screened", _bc06_screened_route(500))
        _bc06_open_linking(page, base)
        page.wait_for_function(
            "document.querySelectorAll("
            "'#queue-list .queue-item').length === 50",
            timeout=15000)
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _bc06_shots_dir(), "shot-bc-p06-paged-desktop.png"))
    finally:
        page.close()


def test_bc06_paged_tablet_shot_live_browser(live_console):
    """Tablet 820px: paged queue via hamburger nav (shot)."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 820, "height": 1180})
    errors, crashes = [], []
    page.on("console",
            lambda msg: errors.append(msg.text)
            if msg.type == "error" else None)
    page.on("pageerror", lambda exc: crashes.append(str(exc)))
    try:
        page.route("**/api/screened", _bc06_screened_route(500))
        _bc06_open_linking(page, base, via_menu=True)
        page.wait_for_function(
            "document.querySelectorAll("
            "'#queue-list .queue-item').length === 50",
            timeout=15000)
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _bc06_shots_dir(), "shot-bc-p06-paged-tablet.png"))
    finally:
        page.close()


def test_p4_arbiter_tab_panel_live_browser(live_console):
    """P4 tab-2 panel: renders, mocked run polls to done, jump works (shot).

    All arbiter endpoints are route-mocked: no model is ever called, no
    batch/labels/history is touched. API 404 paths are covered in
    test_webui_arbiter_runs.py; this test proves the panel behavior.
    """
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)
    polls = {"n": 0}

    def run_route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"run": {
                          "run_id": "p4-live", "status": "running",
                          "total": 2, "done": 0, "abstained": 0}}))

    def status_route(route):
        polls["n"] += 1
        done = polls["n"] >= 2
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"run": {
                          "run_id": "p4-live",
                          "status": "done" if done else "running",
                          "total": 2, "done": 2 if done else 0,
                          "abstained": 0}}))

    def verdicts_route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"verdicts": [
                          {"sense_id": "s#1", "verdict": "link",
                           "target_synset": "w%1:01::", "model": "m",
                           "gloss": "move fast", "candidates": ["w%1:01::"],
                           "duration_ms": 1200},
                          {"sense_id": "s#2", "verdict": None,
                           "target_synset": None, "model": "m",
                           "gloss": "carry weight", "candidates": [],
                           "duration_ms": 300}]}))

    def presets_route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ai_presets": [
                          {"name": "p4-live-preset", "provider": "stub",
                           "model": "stub-m"}]}))

    def log_route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"log": []}))

    try:
        page.route("**/api/ai_presets", presets_route)
        _bc06_open_linking(page, base)
        page.click('#view-linking .cockpit-tabs '
                   '.tab-link[data-tab-index="2"]')
        page.wait_for_selector("#arbiter-run-card", timeout=10000)
        assert page.is_visible("#arbiter-preset")
        assert page.is_visible("#btn-arbiter-run")
        page.route("**/api/arbiter/runs", run_route)
        page.route("**/api/arbiter/runs/p4-live", status_route)
        page.route("**/api/arbiter/runs/p4-live/verdicts", verdicts_route)
        page.route("**/api/arbiter/runs/p4-live/log*", log_route)
        page.wait_for_function(
            "document.getElementById('arbiter-preset').options.length === 1",
            timeout=10000)
        page.select_option("#arbiter-preset", "p4-live-preset")
        page.click("#btn-arbiter-run")
        page.wait_for_function(
            "document.querySelectorAll('#arbiter-verdict-tbody tr').length === 2",
            timeout=15000)
        progress = page.inner_text("#arbiter-progress")
        assert "۲" in progress or "2" in progress, progress
        # dense grid: gloss renders inline, vote keeps domain colors
        first = page.inner_text("#arbiter-verdict-tbody tr")
        assert "move fast" in first, first
        assert "پیوند" in first, first
        votes = page.evaluate(
            "[...document.querySelectorAll('#arbiter-verdict-tbody .vote-tag')]"
            ".map(e=>e.className)")
        assert any("vote-link" in c for c in votes), votes
        assert any("vote-review" in c for c in votes), votes
        page.click("#btn-arbiter-jump")
        page.wait_for_function(
            "document.querySelector('#view-linking .cockpit-tabs "
            ".tab-link.active').getAttribute('data-tab-index') === '3'",
            timeout=5000)
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _bc06_shots_dir(), "shot-p4-arbiter-desktop.png"))
    finally:
        page.close()


def test_p5_linking_five_panels_live_browser(live_console):
    """P5/R2: five tabs switch five real panels, unified history (shot).

    History endpoint is route-mocked (one row per kind); nothing real
    runs, no model is called. Tab memory is asserted via reload.
    """
    browser, base = live_console["browser"], live_console["base"]
    page, errors, crashes = _t07_new_page(browser)

    def history_route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"runs": [
                          {"kind": "linking", "run_id": "r1",
                           "out_name": "t.tsv", "status": "done",
                           "created": "2026-01-01", "detail": "linking"},
                          {"kind": "arbiter", "run_id": "a1",
                           "out_name": "m", "status": "done",
                           "created": "2026-01-02", "detail": "done 2/2"},
                          {"kind": "batch", "run_id": "b1",
                           "out_name": "batch", "status": "exported",
                           "created": "2026-01-03",
                           "detail": "size 10"}]}))

    try:
        page.route("**/api/linking/history", history_route)
        _bc06_open_linking(page, base)
        for idx in ("0", "1", "2", "3", "4"):
            page.click('#view-linking .cockpit-tabs '
                       '.tab-link[data-tab-index="%s"]' % idx)
            page.wait_for_function(
                "document.querySelector("
                "'#linking-tabpanel-%s:not([hidden])') !== null" % idx,
                timeout=5000)
            visible = page.evaluate(
                "[...document.querySelectorAll("
                "'#view-linking .linking-tabpanel:not([hidden])')]"
                ".map(p=>p.id)")
            assert visible == ["linking-tabpanel-" + idx], visible
        page.click('#view-linking .cockpit-tabs '
                   '.tab-link[data-tab-index="4"]')
        page.wait_for_function(
            "document.querySelectorAll("
            "'#gallery-history-tbody tr').length === 3",
            timeout=10000)
        kinds = page.evaluate(
            "[...document.querySelectorAll("
            "'#gallery-history-tbody tr td:nth-child(2)')]"
            ".map(td=>td.innerText)")
        assert kinds == ['پیوندزنی', 'داوری', 'بسته'], kinds
        page.reload()
        page.wait_for_selector("#view-linking", timeout=15000)
        page.wait_for_function(
            "document.querySelector('#view-linking .cockpit-tabs "
            ".tab-link.active').getAttribute('data-tab-index') === '4'",
            timeout=10000)
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _bc06_shots_dir(), "shot-p5-panels-desktop.png"))
    finally:
        page.close()


def test_p6_ai_preset_ui_flow_live_browser(live_console):
    """P6 Req-3: real UI flow — create AI preset, tab-2 lists it live,
    delete cleans up (shot). No mocks: proves the renamed chain works."""
    browser, base = live_console["browser"], live_console["base"]
    tag = "p6-live-%d" % os.getpid()
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.goto(base + "/")
        page.wait_for_selector(
            'button.nav-btn[data-view-target="view-providers"]',
            timeout=15000)
        page.click('button.nav-btn[data-view-target="view-providers"]')
        # NOTE: <option> is never "visible" to Playwright — assert on DOM,
        # like the older preset test, after a settle delay.
        page.wait_for_timeout(1500)
        opts = page.evaluate(
            "[...document.getElementById('preset-provider').options]"
            ".map(o=>o.value)")
        assert opts, "provider select must list real registry providers"
        provider = "avalai" if "avalai" in opts else opts[0]
        page.select_option("#preset-provider", provider)
        page.fill("#preset-label", tag)
        page.fill("#preset-model", "m-p6-live")
        page.click("#btn-save-judge-preset")
        page.wait_for_function(
            "document.getElementById('preset-save-note')"
            ".textContent.includes('ذخیره شد')",
            timeout=15000)
        page.click('button.nav-btn[data-view-target="view-linking"]')
        page.wait_for_timeout(600)
        page.click('#view-linking .cockpit-tabs '
                   '.tab-link[data-tab-index="2"]')
        page.wait_for_function(
            "[...document.getElementById('arbiter-preset').options]"
            ".some(o=>o.value === '%s')" % tag,
            timeout=15000)
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _bc06_shots_dir(), "shot-p6-ai-preset-desktop.png"))
    finally:
        page.close()
        req = urllib.request.Request(
            base + "/api/ai_presets/" + tag, method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
