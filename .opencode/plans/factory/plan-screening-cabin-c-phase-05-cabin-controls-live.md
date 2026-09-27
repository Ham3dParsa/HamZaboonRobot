---
name: plan-screening-cabin-c-phase-05-cabin-controls-live
description: T07 — sticky control column A1-A4 + live run/results tab
created: 2026-09-27
base_commit: 03c6af6f30696b176d04c53fbaca70a2a8e92840
branch: refactor/webui-static-phase1
status: locked
---

STATE: phase 5/7 — status: locked — focus: T07 cabin controls + live tab, no code yet

## Ticket T07 — control column + live tab (UX-1/2/5/6/7/8/9, UX-18/19/21, UX-27, UX-20-consume) [Wave 2 · SERIAL after P01–P04]

- **Blocking edges:** T01 (card values), T02 (`elapsed_human`), T03 (A3 preview payload), T04 (reconnect shape). Downstream: T08/T09 (column DOM host), T10/T11/T12.
- **Scope (files):** `factory/webui/index.html` `#view-screening` (`:395-457` — restructure into right sticky column + left tab-1 pane; tab-2 shell only, filled by T08); `factory/webui/static/js/screening/screening_cabin_controller.js` (rewrite intake/run/poll/render around new shapes; keep `withBusy`, 3-part error, handoff→`loadScreened` contract); `factory/webui/static/cabins.css` (column + tabs + accordion breakpoints); `tests/factory/test_webui_live_browser.py` (extend: new IDs + tab switch).
- **Rules (locked):** A1 textarea LTR multiline (comma-or-line split, client-side count == sent count, smoke-words shortcut kept); A2 name+dest fields with VISIBLE defaults (`proof-linker/screened` + auto `screening-<ts>`) and sanitize preview (`-` replacement per OQ-6); A3 ledger preview `X تازه، Y تکراری` + fresh-only default + reprocess toggle; A4 start/abort `withBusy`, 409→honest message. Live tab: badge + `elapsed_human`, 3-state log box (idle/live/final + titled cause when empty), metric cards (T01 splits + titled empties), per-lemma table via `FilterableListController` + `N نمایان از M سطر` + click→detail (OQ-7 counts + dropped sense_ids + reason, NO gloss text), reconnect banner on T04 state. No `window.*` leaks (module scope, existing convention).
- **Tests:** live-browser: tab-1 default visible; 500-line paste → preview `۵۰۰`; start→busy→poll→metrics→handoff enabled; row click → detail of same lemma; refresh mid-run → resumed (T04 shape).
- **Wiring rows:** `A1 → /api/screening/run{words,out_name?,out_dir?,reprocess_duplicates}`; `status{elapsed_human,manifest{drop_reasons},run_id} → live tab`; `completed → handoff banner → loadScreened() → view-linking`.
- **Changed / not changed / uncertain:** restructures `#view-screening` DOM + controller. NOT changed: `/api/screened`, linking cabin, telemetry. IDs `screening-start/abort/handoff/log/state` KEPT (existing tests); new IDs additive. Uncertain: none.

### Acceptance criteria

- **Interaction tests (named):** IT-T07-01 paste 500-word list → preview `۵۰۰`, start → button busy `در حال شروع…` → poll ticks → metrics + per-lemma rows → handoff enabled; IT-T07-02 filter box narrows rows with zero server calls, counter `N نمایان از M سطر`; IT-T07-03 click row → detail shows that lemma's counts + dropped sense_ids + reasons, row stays marked; IT-T07-04 refresh mid-run → `در حال اجرا` resumed with log tail (not empty); IT-T07-05 complete → banner with out path → «تحویل» opens linking cabin.
- **Screenshots:** `shot-t07-cabin-desktop.png` (column + live tab full) + `shot-t07-cabin-tablet.png` (accordion above workspace).
- **pytest:** `python -m pytest tests/factory/test_webui_live_browser.py -n 8`
