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
            base + "/api/judge_presets/" + tag, method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass
        leftover = os.path.join(_shared_presets_dir(), tag + ".json")
        if os.path.isfile(leftover):
            os.remove(leftover)


def test_candidate_card_no_clipping_live_browser(live_console):
    """run#25 candidate cards show full text; select button sits balanced."""
    browser, base = live_console["browser"], live_console["base"]
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        page.goto(base + "/")
        page.wait_for_selector("#queue-list .queue-item", timeout=15000)
        page.wait_for_timeout(800)
        total = page.evaluate(
            "document.querySelectorAll('#queue-list .queue-item').length")
        assert total == 30, total
        page.evaluate(
            "[...document.querySelectorAll('#queue-list .queue-item')]"
            ".filter(el=>el.textContent.includes('run#25'))[0].click()")
        page.wait_for_selector(
            "#candidates-stack .candidate-row-card", timeout=15000)
        page.wait_for_timeout(500)
        geo = page.evaluate(
            "() => {"
            "  const cards = [...document.querySelectorAll("
            "    '#candidates-stack .candidate-row-card')];"
            "  return cards.map((card) => {"
            "    const one = (sel) => card.querySelector(sel);"
            "    const rect = (el) => {"
            "      if (!el) return null;"
            "      const r = el.getBoundingClientRect();"
            "      return {top: r.top, bottom: r.bottom,"
            "        height: r.height,"
            "        scrollH: el.scrollHeight, clientH: el.clientHeight};"
            "    };"
            "    const hdr = one('.c-top-row');"
            "    const btn = one('.btn-select-candidate');"
            "    const cs = getComputedStyle(card);"
            "    const hs = hdr ? getComputedStyle(hdr) : null;"
            "    const key = one('.c-sensekey');"
            "    return {card: rect(card), header: rect(hdr),"
            "      button: rect(btn), gloss: rect(one('.c-gloss-text')),"
            "      syn: rect(one('.c-synonyms-line')),"
            "      quote: rect(one('.c-example')),"
            "      cardOverflow: cs ? cs.overflow : '',"
            "      headerJustify: hs ? hs.justifyContent : '',"
            "      keyDir: key ? key.getAttribute('dir') : '',"
            "      synText: one('.c-synonyms-line') ?"
            "        one('.c-synonyms-line').textContent : '',"
            "      nCards: cards.length};"
            "  });"
            "}")
        assert len(geo) == 2, geo
        assert any("moveveryquicklywithoutpausingforbreath" in (
            card["synText"] or "") for card in geo), geo
        for card in geo:
            assert card["cardOverflow"] != "hidden", card
            for part in ("gloss", "syn", "quote"):
                box = card[part]
                assert box is not None, (part, card)
                # free-flowing text: nothing cut by a height cap
                assert box["scrollH"] - box["clientH"] <= 2, (part, card)
            # header: space-between with the button balanced inside it
            assert card["headerJustify"] == "space-between", card
            hdr, btn = card["header"], card["button"]
            assert btn["top"] >= hdr["top"] - 1, card
            assert btn["bottom"] <= hdr["bottom"] + 1, card
            # Latin identifier stays isolated (BiDi-safe)
            assert card["keyDir"] == "ltr", card
        page.screenshot(path=os.path.join(
            live_console["tmpdir"], "candidate-cards.png"))
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
            base + "/api/judge_presets/" + tag, method="DELETE")
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
    def _route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(
                          {"roots": [{"path": tmpdir,
                                      "label": "t09 fixtures"}],
                           "files": {}}))
    return _route


def _t09_open_dialog(page, base, pick_id):
    _t07_open_screening(page, base)
    page.click("#" + pick_id)
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
        page.click("#screening-pick-input")
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


def _t10_files(screened_exists=True, over_cap=True):
    screened = {
        "path": "/tmp/t10-screened.jsonl",
        "exists": bool(screened_exists),
        "size": 12345,
        "lines": 50000 if over_cap else 7,
        "lines_label": "50000+" if over_cap else "7",
        "truncated": bool(over_cap),
        "mtime_iso": "2026-09-27T00:00:00+00:00",
        "mtime_relative": "۵ دقیقه پیش",
        "mtime_detail": "شمسی ۱۴۰۵/۰۷/۰۵ (Asia/Tehran) • میلادی 2026-09-27 (UTC)",
    }
    if not screened_exists:
        screened = {"path": "/tmp/t10-screened.jsonl", "exists": False,
                    "size": 0, "lines": 0, "lines_label": "0",
                    "truncated": False, "mtime_iso": None,
                    "mtime_relative": "—", "mtime_detail": "—"}
    kaikki = {"path": "", "exists": False, "size": 0, "lines": 0,
              "lines_label": "0", "truncated": False, "mtime_iso": None,
              "mtime_relative": "—", "mtime_detail": "—"}
    return {"kaikki_raw": kaikki, "screened": screened}


def _t10_roots_route(roots, files):
    def _route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"roots": roots, "files": files}))
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
    """IT-T10-01: paths row shows exists/size/۵۰۰۰۰+/mtime from live facts."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    roots = [{"path": tmpdir, "label": "t10 fixtures"}]
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
        assert "۱۲۳۴۵" in body, body  # fa size from live facts
        assert "۵ دقیقه پیش" in body, body  # fa mtime from live facts
        # Group A glossary: source dataset renders Persian.
        assert "غربال‌شده" in body, body  # source dataset named
        assert "(screened)" not in body, body
        _t07_assert_clean(errors, crashes)
        page.screenshot(path=os.path.join(
            _t10_shots_dir(live_console), "shot-t10-paths-desktop.png"))
    finally:
        page.close()


def test_t10_02_dead_root_drops_badge_matches_live_browser(live_console):
    """IT-T10-02: remove a root dir → row gone, badge count matches."""
    browser, base = live_console["browser"], live_console["base"]
    tmpdir = live_console["tmpdir"]
    two = [{"path": tmpdir, "label": "t10-a"},
           {"path": os.path.join(tmpdir, "t10-b"), "label": "t10-b"}]
    os.makedirs(os.path.join(tmpdir, "t10-b"), exist_ok=True)
    one = [{"path": tmpdir, "label": "t10-a"}]
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
    roots = [{"path": tmpdir, "label": "t10 fixtures"}]
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
    roots = [{"path": tmpdir, "label": "t10 fixtures"}]
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
            "!!document.getElementById(\"linking-err\")") is True
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
    # Linking: forced 500 → linking-err box; retry after unroute clears it.
    page, errors, crashes = _t07_new_page(browser)
    try:
        page.route("**/api/screened*",
                   lambda route: route.fulfill(
                       status=500, content_type="application/json",
                       body=json.dumps({"error": "t12 forced"})))
        page.goto(base + "/")
        page.wait_for_selector("#linking-err .form-error", timeout=15000)
        page.unroute("**/api/screened*")
        page.click(
            "#linking-err .form-error-actions "
            "button:has-text(\"تلاش دوباره\")")
        page.wait_for_function(
            "document.getElementById(\"linking-err\")"
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
