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
PRESETS_DIR = os.path.join(PROJECT_ROOT, "factory", "webui", "presets")

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
    page.evaluate("openView('view-providers')")
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
        leftover = os.path.join(PRESETS_DIR, tag + ".json")
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
