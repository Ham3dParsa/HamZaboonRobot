---
name: plan-console-phase-04-view-memory
description: T6 view memory restores last cabin and tab (P2)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: planned
---

STATE: phase 4 — status: done — view memory live (hz-view-memory: cabin+tab persist/restore; first run keeps view-linking+tab-3 default; 60/60 interface tests green incl. 2 pinned; Playwright reload proof PASS, screenshot view-memory-proof.png shows linking cabin + restored tab 0; server stopped via PID-only)

## Blocking edges

- Blocked by: — (independent; Wave 2 with T2).
- Blocks: —.

## Scope (exact files)

- `factory/webui/index.html` ONLY (cabin/tab JS region; existing precedent:
  `hz-theme` localStorage at lines ~746–755):
  - Persist last cabin (`view-*`) + linking tab on change (localStorage only).
  - Restore on load; first run (no stored value) keeps current default unchanged.
- `tests/factory/test_sense_linking_judge_webui_interface.py`: extend.

## Test-first tests (names)

- `test_view_memory_restores_cabin_and_tab` (stored ids → `openView` + tab select on load)
- `test_view_memory_first_run_default` (no stored value → default view/tab, no crash)

## Acceptance (verifiable artifacts)

- Named tests green; reload restores cabin+tab; fresh profile shows default.
- No server change; no secret/operator data in localStorage (view ids only).

## Wiring

- Rule: locked view-memory rule. No callback/router change.
