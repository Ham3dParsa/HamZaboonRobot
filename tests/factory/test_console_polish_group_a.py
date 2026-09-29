"""Group A console polish (spec-console-polish-ux.md §5): strings/titles/
receipts (PUX-10..14, PUX-24) + native theme inputs (PUX-5/PUX-6) +
queue keyboard (PUX-22) + secret masking (PUX-23).

Locked OQ: Persian prose in Vazirmatn; English/machine IDs/paths stay
isolated LTR mono; acronyms AI/SQLite/TSV/G1/G2/R2-R4/NONE stay Latin
isolated; operator copies human Persian, machine English only in the
debug escape (title/details). String/theme-only — no layout/module
changes. Hermetic: source-level assertions, no browser, no network.
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
JS_DIR = os.path.join(STATIC_DIR, "js")


def _html():
    with open(HTML_PATH, encoding="utf-8") as handle:
        return handle.read()


def _css():
    parts = []
    for name in ("tokens.css", "layout.css", "components.css", "cabins.css"):
        with open(os.path.join(STATIC_DIR, name),
                  encoding="utf-8") as handle:
            parts.append(handle.read())
    return "\n".join(parts)


def _js(*rel):
    with open(os.path.join(JS_DIR, *rel), encoding="utf-8") as handle:
        return handle.read()


def _no_titles(html):
    no_comments = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    return re.sub(r'title="[^"]*"', '', no_comments)


def _visible_text(html):
    """Text nodes only (attributes like tabindex must not trip word checks)."""
    return re.sub(r'<[^>]*>', '', _no_titles(html))


# ─── PUX-10: boot/LAN note → friendly guide, tech in title escape ───

def test_boot_note_hides_lan_bind_behind_title():
    html = _html()
    assert 'id="boot-addr-note"' in html
    assert 'راهنمای اتصال کنسول' in html
    visible = _visible_text(html)
    assert "LAN" not in visible
    assert "bind" not in visible
    assert "آدرس LAN" not in html
    # debug escape kept: exact technical note survives in a title
    assert 'title="plain start binds all interfaces (LAN-visible)"' in html


# ─── PUX-11: vote note → friendly status, tech in title escape ───

def test_vote_note_hides_store_and_watermark():
    html = _html()
    visible = _no_titles(html)
    assert "labels.jsonl" not in visible
    assert "watermark" not in visible
    assert "دفتر رأی‌ها" in html
    assert "گزینه غیرشاهد امتیاز ندارد" in html
    assert "labels.jsonl" in html  # title debug escape kept


def test_vote_receipt_maps_store_and_watermark_to_persian():
    js = _js("sense_linking", "human_review_controller.js")
    assert "ثبت شد در دفتر رأی‌ها" in js
    assert "نشان غیرشاهد (غیرقابل امتیاز)" in js
    assert "j.store" in js and "j.watermark" in js  # raw rides titles only


# ─── PUX-12: tab titles Persian, no module paths ───

def test_tab_titles_persian_without_module_paths():
    html = _html()
    titles = re.findall(r'title="([^"]*)"', html)
    assert titles
    for title in titles:
        assert "factory/" not in title, title
    # owner filenames survive (traceability), path prefixes are gone
    for owner in ("linker.py", "arbitration.py", "human_queue.py",
                  "cli.py", "table.tsv"):
        assert owner in html, owner
    assert "factory/linking/" not in html


# ─── PUX-13: blacklisted English prose is gone ───

def test_blacklisted_english_prose_replaced():
    html = _html()
    human = _js("sense_linking", "human_review_controller.js")
    dialog = _js("shell", "data_dialog_controller.js")
    screening = _js("screening", "screening_cabin_controller.js")
    main = _js("main.js")
    bundle = "\n".join((html, human, dialog, screening, main))
    for literal in (
            "No join for this sense",
            "No candidates in the link table",
            "no browse roots",
            "no caller",
            "mkdir needs name+dir",
            "upload needs file+dir",
            "rename needs a name",
            "pin needs name+dir",
            "words is empty",
            "exit_code=",
            "extra=",
            "row=",
            "followup: backend wiring pending",
            "(Kaikki Screening)",
            "(Precard Extraction)",
            "/ NONE",
            "خالی = console-judge",
            "(stored encrypted)",
    ):
        assert literal not in bundle, literal
    # glossary replacements landed
    for fa in (
            "پیوندی برای این سنس نیست",
            "نامزدی در جدول پیوند برای این سنس نیست",
            "مورد بیشتر از سقف",
            "کد خروج",
            "پشتوانه سرور این کابین هنوز وصل نیست",
            "خالی یعنی پیش‌فرض",
    ):
        assert fa in bundle, fa


# ─── PUX-14: remaining Latin is isolated code with Persian label ───

def test_latin_remnants_isolated_with_persian_labels():
    html = _html()
    for token in (
            '<span class="code-token" dir="ltr">NONE</span>',
            '<span class="code-token" dir="ltr">G1</span>',
            '<span class="code-token" dir="ltr">G2</span>',
            '<span class="code-token" dir="ltr">R3</span>',
            '<span class="code-token" dir="ltr">R2</span>',
            '<span class="status-tag code-token" dir="ltr">AI</span>',
            '<span class="status-tag code-token" dir="ltr">SQLite</span>',
    ):
        assert token in html, token
    assert "موارد " in html and "بدون پیوند معتبر" in html


# ─── PUX-24: server English mapped, unmapped raw stays labelled ───

def test_witness_and_drop_reasons_mapped_with_labelled_fallback():
    human = _js("sense_linking", "human_review_controller.js")
    assert "شاهد: " in human
    assert "ltrCode(witness)" in human
    screening = _js("screening", "screening_cabin_controller.js")
    assert "dropReasonNodes" in screening
    assert "حذف دوقلو (" in screening and "حذف اسم خاص (" in screening
    assert "علت سرور: " in screening
    telemetry = _js("telemetry", "telemetry_dashboard_controller.js")
    # P04/L4: منبع‌نام‌ها تک‌مالک در مدیر یکپارچه‌اند؛ تله‌متری فقط مصرف می‌کند.
    manager = _js("shell", "file_history_manager.js")
    assert "غربال‌شده" in manager and "خام کایکی" in manager
    assert "srcFa(" in telemetry
    assert "(' (' + picked.name + ')'" not in telemetry


# ─── PUX-5/PUX-6: native inputs follow the theme ───

def test_color_scheme_syncs_with_data_theme():
    css = _css()
    assert "color-scheme: dark" in css
    assert "color-scheme: light" in css


def test_file_input_themed_like_form_inputs():
    html = _html()
    css = _css()
    assert 'class="file-input" id="data-dialog-upload-file"' in html
    assert ".file-input" in css
    assert "file-selector-button" in css


# ─── PUX-22: queue rows keyboard-operable ───

def test_queue_rows_keyboard_operable_like_per_lemma():
    js = _js("sense_linking", "human_review_controller.js")
    start = js.index("function renderQueue()")
    row = js[start:js.index("function selectSense(", start)]
    assert "item.tabIndex = 0" in row
    assert "keydown" in row
    assert "'Enter'" in row and "' '" in row


# ─── PUX-23: provider key masked with a show toggle ───

def test_provider_key_input_masked_with_toggle():
    js = _js("providers", "provider_registry_controller.js")
    assert "keyInp.type = 'password'" in js
    assert "پنهان‌کردن" in js
    # OQ-5: the debug-escape copy keeps machine English lines
    assert "'provider: ' + row.name" in js
    assert "'route: ' + (row.route || '')" in js
