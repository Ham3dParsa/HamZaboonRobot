"""Wave 1 console polish — hermetic static audits (PUX-B7/B8/B9).

P01 (font self-hosted): no outbound font URL in head/CSS, bundled woff2
exist, @font-face with font-display:swap, body --sans stays
Vazirmatn-first. P02 (mono scope + BiDi single-owner): sole owner
faNum/ltrCode/faCell in shell/api_client.js, no local copies, zero
physical text-align, mono only on machine identifiers.

Hermetic: source-level assertions, no browser, no network.
"""

import os
import re
import sys

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

HTML_PATH = os.path.join(PROJECT_ROOT, "factory", "webui", "index.html")
STATIC_DIR = os.path.join(PROJECT_ROOT, "factory", "webui", "static")
FONTS_DIR = os.path.join(STATIC_DIR, "fonts")
JS_SHELL = os.path.join(STATIC_DIR, "js", "shell")
CSS_FILES = ("tokens.css", "fonts.css", "layout.css",
             "components.css", "cabins.css")


def _html():
    with open(HTML_PATH, encoding="utf-8") as handle:
        return handle.read()


def _css(name):
    with open(os.path.join(STATIC_DIR, name), encoding="utf-8") as handle:
        return handle.read()


def _all_css():
    return "\n".join(_css(n) for n in CSS_FILES)


def _js(name):
    with open(os.path.join(JS_SHELL, name), encoding="utf-8") as handle:
        return handle.read()


# ─── P01: Vazirmatn self-hosted ───

def test_no_remote_font_url_in_head_or_css():
    head = _html().split("</head>")[0]
    assert re.search(r"https?://", head) is None or \
        "fonts.googleapis" not in head and "fonts.gstatic" not in head, head
    assert "fonts.googleapis" not in head
    assert "fonts.gstatic" not in head
    for name in CSS_FILES:
        css = _css(name)
        assert "fonts.googleapis" not in css, name
        assert "fonts.gstatic" not in css, name
        for match in re.finditer(r"url\(([^)]+)\)", css):
            url = match.group(1).strip().strip("\"'")
            assert not re.match(r"https?://", url), (name, url)


def test_bundled_woff2_exist():
    for name in ("Vazirmatn-Regular.woff2", "Vazirmatn-Bold.woff2"):
        path = os.path.join(FONTS_DIR, name)
        assert os.path.isfile(path), path
        assert os.path.getsize(path) > 10000, path


def test_font_face_swap_and_local_only():
    css = _css("fonts.css")
    assert css.count("@font-face") >= 2, css
    assert "font-display: swap" in css or "font-display:swap" in css, css
    assert "Vazirmatn-Regular.woff2" in css
    assert "Vazirmatn-Bold.woff2" in css
    html = _html()
    assert "/static/fonts.css" in html


def test_body_sans_stays_vazirmatn_first():
    css = _css("tokens.css")
    match = re.search(r"--sans:\s*([^;]+);", css)
    assert match, css
    first = match.group(1).split(",")[0].strip().strip("\"'")
    assert first == "Vazirmatn", match.group(1)
    assert "font-family: var(--sans)" in css or \
        "font-family:var(--sans)" in css


# ─── P02: BiDi single-owner + mono scope ───

def test_single_bidi_owner():
    owner = _js("api_client.js")
    assert "export function faNum" in owner
    assert "export function ltrCode" in owner
    assert "export function faCell" in owner
    for name in os.listdir(JS_SHELL):
        if not name.endswith(".js") or name == "api_client.js":
            continue
        with open(os.path.join(JS_SHELL, name), encoding="utf-8") as handle:
            src = handle.read()
        assert not re.search(r"function\s+ltr\s*\(", src), name
        assert not re.search(r"function\s+faCell\s*\(", src), name


def test_data_dialog_consumes_owner():
    src = _js("data_dialog_controller.js")
    assert "ltrCode" in src
    assert "faCell" in src
    assert re.search(r"from\s+['\"]\./api_client\.js['\"]", src)


def test_zero_physical_text_align():
    for name in ("tokens.css", "layout.css",
                 "components.css", "cabins.css"):
        css = _css(name)
        assert not re.search(r"text-align:\s*left\b", css), name
        assert not re.search(r"text-align:\s*right\b", css), name


def test_mono_only_on_machine_identifiers():
    allowed = {"tokens.css": (".code-token",),
               "cabins.css": (".model-id",),
               "components.css": (".error-code",)}
    for name, selectors in allowed.items():
        css = _css(name)
        assert "var(--mono)" in css, name
        for selector in selectors:
            assert selector in css, (name, selector)
    css_all = _all_css()
    assert ".mini-val" in css_all
    assert re.search(r"\.mini-val\s*\{[^}]*var\(--sans\)", css_all), \
        ".mini-val must use body font"
    assert re.search(r"#screening-log\s*\{[^}]*var\(--sans\)", css_all), \
        "#screening-log must use body font"
    assert re.search(r"#screening-words\s*\{[^}]*var\(--sans\)", css_all), \
        "#screening-words must use body font"
    assert re.search(
        r"\.form-error-detail\s*\{[^}]*var\(--sans\)", css_all), \
        ".form-error-detail must use body font"
