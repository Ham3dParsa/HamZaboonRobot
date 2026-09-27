"""T4: queue-row no-shrink rule + browser regression with real-shaped rows.

Scope: row CSS in factory/webui/static/*.css (link order) + this test only.
Fixture rows are real-shaped: long LTR gloss, RTL+LTR mix, all statuses.
Harness: Playwright (chromium) against a real console server subprocess on
a free alternate port (same pattern as test_webui_live_browser.py) — the
extracted stylesheets hang off absolute /static/* links, which file://
cannot resolve. Fallback: if the browser/server cannot come up in this
environment, the browser test skips and the static CSS assertions below
still guard the locked rule (reason recorded in the skip message).
"""

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
HTML_PATH = os.path.join(PROJECT_ROOT, "factory", "webui", "index.html")
STATIC_DIR = os.path.join(PROJECT_ROOT, "factory", "webui", "static")
# Stylesheet link order in index.html (R3).
LINK_ORDER = ("tokens.css", "layout.css", "components.css", "cabins.css")
SERVER_PATH = os.path.join(
    PROJECT_ROOT, "factory", "webui", "server.py")

# Real-shaped fixture rows: (sense_id, gloss, status).
# Long LTR gloss forces ellipsis; RTL+LTR mix guards BiDi; both statuses covered.
FIXTURE_ROWS = [
    ("run__v__3",
     "to move fast on foot so that both feet leave the ground with every single "
     "step taken forward across a considerable distance without pause",
     "داوری جاری"),
    ("کتاب__n__1",
     "a written or printed work consisting of pages glued or sewn together "
     "along one side — کتاب printed bound pages",
     "در انتظار"),
    ("آب__n__2",
     "the clear colorless liquid — آب that falls as rain and fills rivers, lakes "
     "and seas across the whole earth surface",
     "در انتظار"),
    ("go__v__7", "to move", "در انتظار"),
]


def _html():
    with open(HTML_PATH, encoding="utf-8") as handle:
        return handle.read()


def _css():
    """Concatenated console stylesheets in <link> order (R3).

    Phase 1 moved the <style> block verbatim into static/*.css
    (queue rules are cabin-domain: cabins.css; layout.css included
    in the same read) — same pattern as the interface suite's _css().
    """
    parts = []
    for name in LINK_ORDER:
        with open(os.path.join(STATIC_DIR, name),
                  encoding="utf-8") as handle:
            parts.append(handle.read())
    return "\n".join(parts)


def _rule_block(css, selector):
    """Return the declaration block for an exact selector match."""
    pattern = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}", re.S)
    match = pattern.search(css)
    assert match, "missing CSS rule: %s" % selector
    return match.group(1)


def _inject_script(rows):
    """JS that rebuilds #queue-list with real-shaped .queue-item rows."""
    import json

    payload = json.dumps(
        [{"sense_id": s, "gloss": g, "status": t} for s, g, t in rows])
    return (
        "const rows = %s;"
        "const box = document.getElementById('queue-list');"
        "box.replaceChildren();"
        "for (const row of rows) {"
        "  const item = document.createElement('div');"
        "  item.className = 'queue-item';"
        "  const wrap = document.createElement('div');"
        "  const b = document.createElement('b');"
        "  b.className = 'code-token queue-id';"
        "  b.textContent = row.sense_id;"
        "  const sub = document.createElement('div');"
        "  sub.className = 'queue-gloss ltr-text';"
        "  sub.setAttribute('dir', 'ltr');"
        "  sub.textContent = row.gloss;"
        "  sub.title = row.gloss;"
        "  wrap.append(b, sub);"
        "  const tag = document.createElement('span');"
        "  tag.className = 'status-tag';"
        "  tag.textContent = row.status;"
        "  item.append(wrap, tag);"
        "  box.append(item);"
        "}"
        "document.getElementById('view-linking').classList.add('active');"
    ) % payload


def _geometry(page):
    return page.evaluate(
        "() => {"
        "  const box = document.getElementById('queue-list');"
        "  const rows = [...box.querySelectorAll('.queue-item')].map((el) => {"
        "    const r = el.getBoundingClientRect();"
        "    const tag = el.querySelector('.status-tag');"
        "    const tr = tag ? tag.getBoundingClientRect() : null;"
        "    const gloss = el.querySelector('.queue-gloss');"
        "    const gr = gloss ? gloss.getBoundingClientRect() : null;"
        "    const cs = gloss ? getComputedStyle(gloss) : null;"
        "    return {top: r.top, bottom: r.bottom, height: r.height,"
        "      width: r.width,"
        "      tagW: tr ? tr.width : 0, tagRight: tr ? tr.right : 0,"
        "      rowRight: r.right,"
        "      glossH: gr ? gr.height : 0,"
        "      glossScrollW: gloss ? gloss.scrollWidth : 0,"
        "      glossClientW: gloss ? gloss.clientWidth : 0,"
        "      whiteSpace: cs ? cs.whiteSpace : '',"
        "      textOverflow: cs ? cs.textOverflow : '',"
        "      overflow: cs ? cs.overflow : ''};"
        "  });"
        "  const br = box.getBoundingClientRect();"
        "  return {rows,"
        "    listScrollH: box.scrollHeight, listClientH: box.clientHeight,"
        "    listTop: br.top, listBottom: br.bottom};"
        "}")


def _free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


@pytest.fixture(scope="module")
def live_console(tmp_path_factory):
    """Real console server on a free alternate port (never the default).

    Mirrors test_webui_live_browser.py: absolute /static/* links only
    resolve over HTTP. Static guards above still hold on their own.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        pytest.skip("playwright not installed: %s" % exc)
    tmpdir = str(tmp_path_factory.mktemp("noshrink"))
    port = _free_port()
    assert port != 5561, "must run on an alternate port, never the default"
    log_path = os.path.join(tmpdir, "server.log")
    log_handle = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, SERVER_PATH,
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=PROJECT_ROOT,
        stdout=log_handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, close_fds=True)
    base = "http://127.0.0.1:%d" % port
    try:
        deadline = time.time() + 30
        ready = False
        last = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        base + "/api/engine_info", timeout=2) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception as exc:
                last = exc
            time.sleep(0.5)
        if not ready:
            pytest.skip(
                "live console never became ready at %s (%r)" % (base, last))
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as exc:
                pytest.skip("chromium cannot launch here: %s" % exc)
            try:
                yield {"base": base, "browser": browser}
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


def _run_browser(live, width):
    page = live["browser"].new_page(viewport={"width": width, "height": 900})
    try:
        page.goto(live["base"] + "/")
        # Boot fetch (loadScreened) rebuilds #queue-list once; inject only
        # after it settles (#queue-remaining leaves its "…" placeholder),
        # else the boot render wipes the fixture rows mid-test.
        page.wait_for_function(
            "document.getElementById('queue-remaining').textContent !== '…'",
            timeout=15000)
        page.evaluate(_inject_script(FIXTURE_ROWS * 3))  # 12 rows: force scroll
        page.wait_for_timeout(300)
        return _geometry(page)
    finally:
        page.close()


def test_queue_rows_do_not_shrink(live_console):
    """Real-shaped rows keep natural height, list scrolls, no text collision."""
    css = _css()
    # Locked no-shrink rule: rows never squash; the list scrolls instead.
    assert "flex-shrink: 0" in _rule_block(css, ".queue-item")
    assert "flex-shrink: 0" in _rule_block(css, ".queue-item > .status-tag")
    try:
        geo = _run_browser(live_console, 1280)
    except Exception as exc:  # fallback: static guard above still holds
        pytest.skip("playwright unavailable, static no-shrink guard holds: %s" % exc)
    rows = geo["rows"]
    assert len(rows) == 12
    for row in rows:
        assert row["height"] >= 20, row  # natural height, never squashed
        assert row["tagW"] > 0, row  # status slot stays visible
        assert row["tagRight"] <= row["rowRight"] + 1, row
    for prev, nxt in zip(rows, rows[1:]):
        assert nxt["top"] >= prev["bottom"] - 1, (prev, nxt)  # no vertical collision
    assert geo["listScrollH"] > geo["listClientH"]  # list scrolls


def test_gloss_ellipsis_not_wrap_push(live_console):
    """Long gloss truncates with ellipsis, never displaces siblings."""
    css = _css()
    gloss = _rule_block(css, ".queue-gloss")
    assert "white-space: nowrap" in gloss
    assert "text-overflow: ellipsis" in gloss
    assert "overflow: hidden" in gloss
    assert "min-width: 0" in _rule_block(css, ".queue-item > div:first-child")
    try:
        widths = {}
        for width in (1280, 768):
            widths[width] = _run_browser(live_console, width)
    except Exception as exc:  # fallback: static guard above still holds
        pytest.skip("playwright unavailable, static ellipsis guard holds: %s" % exc)
    for width, geo in widths.items():
        rows = geo["rows"]
        long_row = max(rows, key=lambda r: r["glossScrollW"])
        # long gloss truncates (scrolls internally) instead of wrapping/pushing
        assert long_row["glossScrollW"] >= long_row["glossClientW"], (width, long_row)
        assert long_row["whiteSpace"] == "nowrap", (width, long_row)
        assert long_row["textOverflow"] == "ellipsis", (width, long_row)
        assert long_row["tagW"] > 0, (width, long_row)  # status not pushed out
        for prev, nxt in zip(rows, rows[1:]):
            assert nxt["top"] >= prev["bottom"] - 1, (width, prev, nxt)
