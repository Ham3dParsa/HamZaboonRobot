---
name: plan-console-polish-bc-phase-05-popover
description: PUX-B1..B4 anchored picking-only command popover on top of unified manager
created: 2026-09-28
base_commit: 0c8c57c
branch: docs/polish-bc-spec
status: locked
---

STATE: phase 5/6 — status: implemented-verified — focus: done, no commit (live IT-BC05-01..05 + T08/T09/T10/T11/BC04 regression green 64/64 in one run 2026-09-29; shots shot-bc-p05-popover-desktop/tablet.png)

# Phase 05 — Anchored picking-only popover (PUX-B1–B4) — REBASE-SENSITIVE

- **Blocking edges:** Phase 04 + Wave 0. Parallel-safe vs 06.
- **Scope (files):** `factory/webui/index.html` (`:659-697` dialog host, `:702-727` collision host — popover anchored at invoke point, first rollout screening A1/A2 per spec Q4, then generalize); `factory/webui/static/js/shell/data_dialog_controller.js` (`:53-88` open/close — replace fixed side-dock with anchored transient layer); `factory/webui/static/cabins.css` (`:320-327, :335-338, :356-363` — dock column → anchored layer styles); `factory/webui/static/js/shell/view_navigator.js` (scope check only — popover must not leak across `#view-linking` tabs).
- **Locked rules:** L3 PICKING-ONLY — popover never triggers actions, only fills the invoking input; transient layer (no layout column added); `Escape`/outside-click closes with focus back on the invoking button; command input filters pins/recents/paths client-side with titled groups (empty group shows titled empty, never vanishes silently); two-line rows: line 1 name + usefulness sentence, line 2 same-root facts (fa) + effect line (what lands in which input); single tab-stop for the layer; Up/Down cycles, `Enter` picks, `Escape` cancels.
- **Tests:** extend `tests/factory/test_webui_live_browser.py`: open adds no layout column; close returns focus to invoker; empty-input shows 3 titled groups; typing filters all groups client-side (zero server calls); every row has usefulness + effect lines; facts match the row's own root.
- **Wiring rows:** `انتخاب فایل…/انتخاب مقصد… button → anchored popover (pins/recents/paths via Phase-04 manager) → pick → fills invoking input`; `view_navigator tabscope → popover closes on tab switch`.

## Acceptance criteria

- **Interaction tests (named):** IT-BC05-01 click «انتخاب فایل…» → layer anchors at button, page grid unchanged; IT-BC05-02 keyboard-only: `Tab` once into layer → Up/Down reaches every row (cycling) → `Enter` picks → focus back on invoker (no mouse); IT-BC05-03 `Escape`/outside-click → closes with no selection, focus returns; IT-BC05-04 type filter → all three groups filter with titled empties, no fetch in network log; IT-BC05-05 attempt action from popover → impossible (no action buttons inside).
- **Screenshots:** `shot-bc-p05-popover-desktop.png` + `shot-bc-p05-popover-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_live_browser.py -n 8`
- Rebase risk: **REBASE-SENSITIVE** — touches `index.html` cabins + `data_dialog_controller.js` + `view_navigator.js` scoping the other branch likely touched.
