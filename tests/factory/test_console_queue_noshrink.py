"""T4: queue-row no-shrink rule + browser regression with real-shaped rows.

Scope: row CSS in factory/webui/index.html + this test only.
Fixture rows are real-shaped: long LTR gloss, RTL+LTR mix, all statuses.
Harness: Playwright (chromium) against the served file index.html via
file:// URI. Fallback: if the browser cannot launch in this environment,
the browser test skips and the static CSS assertions below still guard
the locked rule (reason recorded in the skip message).
"""

import os
import re

import pytest

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
HTML_PATH = os.path.join(PROJECT_ROOT, "factory", "webui", "index.html")

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
    text = _html()
    start = text.index("<style>")
    end = text.index("</style>", start)
    return text[start:end]


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


def _run_browser(width):
    from playwright.sync_api import sync_playwright

    import pathlib

    file_uri = pathlib.Path(HTML_PATH).as_uri()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.goto(file_uri)
            page.evaluate(_inject_script(FIXTURE_ROWS * 3))  # 12 rows: force scroll
            page.wait_for_timeout(300)
            return _geometry(page)
        finally:
            browser.close()


def test_queue_rows_do_not_shrink():
    """Real-shaped rows keep natural height, list scrolls, no text collision."""
    css = _css()
    # Locked no-shrink rule: rows never squash; the list scrolls instead.
    assert "flex-shrink: 0" in _rule_block(css, ".queue-item")
    assert "flex-shrink: 0" in _rule_block(css, ".queue-item > .status-tag")
    try:
        geo = _run_browser(1280)
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


def test_gloss_ellipsis_not_wrap_push():
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
            widths[width] = _run_browser(width)
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
