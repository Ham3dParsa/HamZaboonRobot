---
name: plan-console-phase-02-queue-slim
description: T3 queue rows exactly three fields, detail section owns rest (P0)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: planned
---

STATE: phase 2 — status: done (uncommitted) — 3 pinned tests green; console suites 63 passed; diff --check clean; screenshot C:\Users\HAMEDP~1\AppData\Local\Temp\opencode\queue-slim-t3-desktop.png (1600px, PASS: slim 3-slot rows + named «جزئیات سنس» detail); server stopped via PID-only; no commits/pushes; sibling T1 scope untouched

## Blocking edges

- Blocks: phase-05-noshrink, phase-07-candidates-join.
- Blocked by: — (foundation; Wave 1 with T1).

## Scope (exact files)

- `factory/webui/index.html` ONLY (queue render JS + `«جزئیات سنس»` section):
  - Queue row renders exactly: kaikki identifier, gloss slice, status. Nothing else.
  - Named detail section alone renders: candidates, examples, full text.
  - Never mix: no candidates/examples/full-text in rows; no
    identifier/gloss/status duplication beyond the row's three.
- `tests/factory/test_sense_linking_judge_webui_interface.py`: extend
  (static HTML-string style, matching existing tests).

## Test-first tests (names)

- `test_queue_row_three_fields_only` (row template: identifier + gloss slice + status)
- `test_detail_section_owns_candidates_examples_fulltext`
- `test_queue_never_renders_candidates` (negative: no candidates markup in row path)

## Acceptance (verifiable artifacts)

- Named tests green; existing interface tests unbroken.
- Manual screenshot-equivalent: row DOM contains 3 slots; detail section
  contains candidates/examples/full text for the selected sense.
- Persian copy correct; dynamic values keep existing escaping path.

## Wiring

- Rule: locked queue/detail separation. No callback/router change.
