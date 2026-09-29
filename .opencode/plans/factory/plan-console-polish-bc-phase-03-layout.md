---
name: plan-console-polish-bc-phase-03-layout
description: PUX-B5 sticky control column + PUX-B6 inner workspace scroll with caps
created: 2026-09-28
base_commit: 0c8c57c
branch: docs/polish-bc-spec
status: locked
---

STATE: phase 3/6 — status: implemented-verified — focus: P03 green 4/4 targeted live-browser (2026-09-29), shots refreshed, no commit per ticket

# Phase 03 — Sticky control + inner scroll (PUX-B5 + B6) — REBASE-SENSITIVE

- **Blocking edges:** Wave 0 only. Parallel-safe vs 01, 02.
- **Scope (files):** `factory/webui/static/layout.css` (`:78-82` shell grid, `:122-130` workspace, `:160-166` linking grid, `:172-176` inspector sticky); `factory/webui/static/cabins.css` (`:251-261` screening layout + `:258-260` sticky, `:237-246` log box); `factory/webui/index.html` (cabin section shells — class hooks only, no tab/route renames); `factory/webui/static/components.css` (`:34` `.bounded` caps). Caps from DESIGN §1.5: compact 260 / standard 320 / report 380.
- **Locked rules:** desktop control column (screening A1–A4 + precard/pilot counterparts) never scrolls away; start/stop/deliver always clickable without page scroll; workspace scrolls internally; at ≥1024px no page-level scroll is created by cabin content.
- **Tests:** extend `tests/factory/test_webui_live_browser.py`: tall-content load → control column rect unchanged after workspace scroll; all three action buttons clickable without page scroll; page `scrollHeight <= viewport` for cabin content at 1280px.
- **Wiring rows:** `layout/cabins caps (260/320/380) → cabin control column (sticky) + workspace (inner scroll)`; `view_navigator.js` untouched (no route/tab change — verify after rebase).

## Acceptance criteria

- **Interaction tests (named):** IT-BC03-01 scroll workspace to bottom → control column + شروع/توقف/تحویل still visible and clickable (button-level); IT-BC03-02 keyboard-only: `Tab` reaches all three action buttons without page scroll; IT-BC03-03 switch cabin tabs → each cabin keeps its own sticky control + inner scroll (tab-level).
- **Screenshots:** `shot-bc-p03-layout-desktop.png` + `shot-bc-p03-layout-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_live_browser.py -n 8`
- Rebase risk: **REBASE-SENSITIVE** — touches `index.html` cabin shells the supervised-arbitration branch likely touched; re-verify `view_navigator.js` scoping after Wave-0 rebase.
