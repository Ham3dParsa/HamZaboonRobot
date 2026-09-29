"""Phase 06 console polish — shared paged list (p50) + titled empties.

PUX-B11: one shared paging module next to FilterableListController
(default page 50, prev/next pager, exact counter, filter kept across
pages); queue + per-lemma + history + files lists adopt it with zero
per-cabin paging copies; a 500-row list never mounts more than one
page in DOM. PUX-B12: six empty states, every one fa text + title
cause from the shared glossary; zero bare … / bare — in list paths.

Hermetic: source-level assertions, no browser, no network. Live DOM
proof (IT-BC06-01..04 + shots) lives in test_webui_live_browser.py.
"""

import os
import re

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SHELL = os.path.join(
    PROJECT_ROOT, "factory", "webui", "static", "js", "shell")
SENSE_LINKING = os.path.join(
    PROJECT_ROOT, "factory", "webui", "static", "js", "sense_linking")
SCREENING = os.path.join(
    PROJECT_ROOT, "factory", "webui", "static", "js", "screening")
HTML_PATH = os.path.join(PROJECT_ROOT, "factory", "webui", "index.html")

SHARED = "paginated_list_controller.js"
ADOPTERS = {
    "queue": os.path.join(SENSE_LINKING, "human_review_controller.js"),
    "per-lemma": os.path.join(
        SCREENING, "screening_cabin_controller.js"),
    "history": os.path.join(SHELL, "cabin_history_controller.js"),
    "files": os.path.join(SHELL, "data_dialog_controller.js"),
}
PAGER_MOUNTS = ("queue-pager", "screening-per-lemma-pager",
                "screening-history-pager", "data-dialog-pager")
EMPTY_KEYS = ("noRoots", "noRows", "noFilterMatch", "noHistory",
              "popoverGroupEmpty", "missingFact")


def _js(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _shared():
    return _js(os.path.join(SHELL, SHARED))


def test_shared_module_page_size_50():
    src = _shared()
    assert re.search(
        r"export\s+const\s+PAGED_LIST_SIZE\s*=\s*50\b", src), src


def test_single_paging_owner_no_per_cabin_copies():
    shared = _shared()
    assert "export class PagedListController" in shared
    assert "export function moveAcrossPages" in shared
    for name, path in ADOPTERS.items():
        src = _js(path)
        assert "paginated_list_controller.js" in src, name
        assert "PagedListController" in src, name
        assert ".pageItems(" in src, name
        assert "class PagedListController" not in src, name
        assert not re.search(
            r"\b(PAGE_SIZE|PAGED_LIST_SIZE|pageSize|per_page|PER_PAGE)\s*=",
            src), name


def test_six_empty_states_defined_with_text_and_title():
    shared = _shared()
    for key in EMPTY_KEYS:
        match = re.search(
            key + r":\s*\{text:\s*'([^']+)'\s*,\s*title:\s*'([^']+)'",
            shared)
        assert match, key
        if key != "missingFact":
            assert len(match.group(1)) > 3, key
        assert len(match.group(2)) > 3, key


def test_empties_wired_with_titles_in_all_lists():
    queue = _js(ADOPTERS["queue"])
    assert "emptyDiv('noRows')" in queue
    assert "emptyDiv('noFilterMatch')" in queue
    per_lemma = _js(ADOPTERS["per-lemma"])
    assert "EMPTY_FA.noRows.title" in per_lemma
    assert "EMPTY_FA.noFilterMatch" in per_lemma
    history = _js(ADOPTERS["history"])
    assert "EMPTY_FA.noHistory.text" in history
    assert "EMPTY_FA.noHistory.title" in history
    assert "EMPTY_FA.noFilterMatch.text" in history
    assert "EMPTY_FA.noFilterMatch.title" in history
    assert "EMPTY_FA.missingFact.title" in history
    files = _js(ADOPTERS["files"])
    assert "EMPTY_FA.noRoots.text" in files
    assert "EMPTY_FA.noRoots.title" in files
    assert "EMPTY_FA.noRows.title" in files
    assert "EMPTY_FA.missingFact.title" in files
    # popover group empty (P05, untouched): titled empty rows stay
    assert "cmdRenderEmpty" in files
    empty_block = files.split("function cmdRenderEmpty")[1].split("}")[0]
    assert "title" in empty_block, empty_block


def test_no_bare_ellipsis_or_dash_in_list_paths():
    history = _js(ADOPTERS["history"])
    assert "EMPTY_FA.noHistory.title" in history.split(
        "node.textContent = '…'")[1].split("return;")[0]
    per_lemma = _js(ADOPTERS["per-lemma"])
    assert "EMPTY_FA.noRows.title" in per_lemma.split(
        "counter.textContent = '…'")[1].split("}")[0]
    # per-lemma cell dashes carry the server-missing cause
    assert per_lemma.count("سرور این لم را ثبت نکرد") >= 1
    assert per_lemma.count("سرور این سنج را ثبت نکرد") >= 3
    # history run-name dash carries the missing-fact cause
    assert "tdRun.title = EMPTY_FA.missingFact.title" in history
    # files cells fall back to the missing-fact cause, never bare
    files = _js(ADOPTERS["files"])
    assert files.count("EMPTY_FA.missingFact.title") >= 4
    assert "faCell('—', null)" not in files


def test_pager_mounts_present_in_html():
    with open(HTML_PATH, encoding="utf-8") as handle:
        html = handle.read()
    for mount in PAGER_MOUNTS:
        assert 'id="%s"' % mount in html, mount


def test_filter_change_resets_to_first_page():
    for name in ("queue", "per-lemma", "history"):
        src = _js(ADOPTERS[name])
        assert ".reset()" in src, name


def test_pager_shape_prev_next_exact_counter():
    shared = _shared()
    assert "'data-pager', 'prev'" in shared
    assert "'data-pager', 'next'" in shared
    assert "'data-pager', 'label'" in shared
    assert "صفحه " in shared
    history = _js(ADOPTERS["history"])
    assert "نمایان از" in history
    per_lemma = _js(ADOPTERS["per-lemma"])
    assert "نمایان از" in per_lemma
