---
name: plan-console-phase-05-noshrink
description: T4 row no-shrink rule plus browser regression test (P1)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: planned
---

STATE: phase 5 — status: done (uncommitted) — 2 pinned tests green (real browser, 1280+768); console suites 73 passed; diff --check clean; screenshots C:\Users\HAMEDP~1\AppData\Local\Temp\opencode\queue-noshrink-t4-desktop.png + queue-noshrink-t4-tablet.png (1280/768, PASS: 12 real-shaped rows, natural height, list scrolls, no collision); browser closed cleanly, no server started; no commits/pushes; sibling T8 scope untouched

## Blocking edges

- Blocked by: phase-02-queue-slim (needs final queue markup — serial).
- Blocks: phase-07-candidates-join. Wave 3 with T8 (region guard: CSS rows
  only; T8 owns providers-panel HTML + `server.py` token region).

## Scope (exact files)

- `factory/webui/index.html`: no-shrink rule on queue-row children
  (`.queue-item` subtree: `flex-shrink: 0` on status/identifier slots,
  `min-width: 0` + ellipsis on gloss slice — precedent: existing
  `flex-shrink: 0` rules at lines ~297/328/351).
- New `tests/factory/test_console_queue_noshrink.py`: regression test with
  REAL-SHAPED rows (long gloss, RTL+LTR mix, all statuses). Harness: parked
  ambiguity — recommended Playwright against served `index.html`; fallback
  static computed-shape assertions documented in-file if Playwright unavailable.

## Test-first tests (names)

- `test_queue_rows_do_not_shrink` (real-shaped fixture rows: widths stable,
  status slot visible at 1024px and 360px-equivalent)
- `test_gloss_ellipsis_not_wrap_push` (long gloss truncates, never displaces siblings)

## Acceptance (verifiable artifacts)

- New test file green; artifact: fixture HTML with real-shaped rows cited in-file.
- Screenshot/dump on failure shows row geometry (harness-dependent; recorded).

## Wiring

- Rule: locked no-shrink rule. No callback/router change.
