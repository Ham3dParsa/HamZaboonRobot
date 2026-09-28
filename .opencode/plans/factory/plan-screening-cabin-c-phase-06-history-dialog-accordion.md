---
name: plan-screening-cabin-c-phase-06-history-dialog-accordion
description: T08 history/lineage tab + T09 slide-over data dialog + tablet accordion
created: 2026-09-27
base_commit: 03c6af6f30696b176d04c53fbaca70a2a8e92840
branch: refactor/webui-static-phase1
status: locked
---

STATE: phase 6/7 — status: locked — focus: T08 done (19/19 pytest green, 2 shots), T09 done in worktree (10 hermetic + 5 live green, 2 shots; uncommitted, no push/PR/merge)

## Ticket T08 — history/lineage tab (ADD-11 consume, UX-31) [Wave 2 · SERIAL after T05+T07 · PARALLEL-safe vs T09]

- **Blocking edges:** T05 (endpoint), T07 (workspace tab shell + handoff contract). Downstream: T12 (handoff pattern reuse).
- **Scope (files):** `index.html` (tab-2 pane), new GENERIC `factory/webui/static/js/shell/cabin_history_controller.js` (class instantiated per cabin — this ticket instantiates for screening; `FilterableListController` reuse), `cabins.css` (history table), live-browser test extend.
- **Rule (locked):** table from `GET /api/runs/history?cabin=screening` (newest last); live search/filter client-side (lemma/run-name/status substring, no server calls); per-record `تحویل به کابین بعدی` → same `loadScreened`-style arm + `openView('view-linking')` as T07 handoff; honest empty when zero runs. Next cabins instantiate the same class with their cabin id — no copies.
- **Tests:** seed 3 runs → filter narrows; per-record handoff arms linking banner with that run's path; empty → titled empty.
- **Wiring rows:** `/api/runs/history?cabin=screening → history table → per-record handoff → view-linking`.

### Acceptance criteria

- **Interaction tests (named):** IT-T08-01 open history tab → 3 seeded runs newest-last; IT-T08-02 type in search → rows narrow instantly, counter updates; IT-T08-03 click record handoff → linking cabin banner shows that run's path; IT-T08-04 zero runs → titled honest empty (no bare dashes).
- **Screenshots:** `shot-t08-history-desktop.png` + `shot-t08-history-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_screening_history.py tests/factory/test_webui_live_browser.py -n 8`

## Ticket T09 — slide-over data dialog + tablet accordion (UX-12/13/14/16, UX-15-consume, OQ-1/3) [Wave 2 · SERIAL after T06+T07 · PARALLEL-safe vs T08]

- **Blocking edges:** T06 (pins API), T07 (caller fields A1/A2). Downstream: T11 (upload/validation entry), T12.
- **Scope (files):** new `factory/webui/static/js/shell/data_dialog_controller.js` (single global dialog owner — both cabins call it, no per-cabin copies); `index.html` (dialog root); `cabins.css` (slide-over dock + tablet full-sheet + accordion); `server.py` `_list_dir` surface (add `mtime_iso` + `lines`/`lines_label` via existing `_file_facts`, capped `۵۰۰۰۰+`); live-browser test extend.
- **Rules (locked):** dialog is the ONLY file/dir picker (no typed paths); opens on data-root, dead roots absent; per-file size + capped lines + mtime (T02 `format_moment`), folders show NO aggregate size; per-row «انتخاب به‌عنوان ورودی/مقصد» fills caller field and closes; pins section (T06) with name+add/remove; ops allowed: mkdir + rename only — delete HARD-BLOCKED (OQ-1), upload restricted to allowlisted dirs (OQ-3); dialog NEVER covers control column (docks opposite, tablet full-sheet with explicit close returning focus to caller). Tablet: A1→A4 accordion above workspace, order preserved, one section open at a time.
- **Tests:** pick-as-input fills A1 + count updates; pick-as-dest fills A2; mkdir/rename ok, delete control absent/disabled; pins add/remove persist.
- **Wiring rows:** `A1/A2 pick buttons → data_dialog.open(mode) → field fill`; `/api/files/{roots,list,pins} → dialog`; `_list_dir → +mtime/lines facts`.

### Acceptance criteria

- **Interaction tests (named):** IT-T09-01 A1 «انتخاب فایل» → dialog → pick file → A1 filled, count == file words; IT-T09-02 A2 «انتخاب مقصد» → pick dir → A2 filled, run lands there; IT-T09-03 pin dir with name → reopen console → still pinned; IT-T09-04 attempt delete → no such control/path, mkdir+rename work; IT-T09-05 tablet width → accordion order A1-A4, dialog full-sheet, controls never covered.
- **Screenshots:** `shot-t09-dialog-desktop.png` (slide-over beside column) + `shot-t09-dialog-tablet.png` (full-sheet + accordion).
- **pytest:** `python -m pytest tests/factory/test_webui_pins.py tests/factory/test_webui_live_browser.py -n 8`
