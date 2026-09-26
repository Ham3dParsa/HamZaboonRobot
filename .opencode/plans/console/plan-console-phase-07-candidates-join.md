---
name: plan-console-phase-07-candidates-join
description: T5 candidates from REAL runs plus human-review join fix (P0)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: planned
---

STATE: phase 7 — status: done — live feed joins: run#5→en-run-en-verb-tL7-sssU, 3 real run:top3 cards, cause=joined (shot t5-candidates-queue.png PASS, 138 console tests green, server stopped via PID)

## Blocking edges

- Blocked by: phase-02-queue-slim, phase-05-noshrink (serial; needs final
  row/detail markup — solo Wave 4, exclusive: touches `server.py` candidates
  region AND `index.html` render).
- Blocks: phase-08-wake-sleep.

## Scope (exact files)

- `factory/webui/server.py` (candidates region ONLY: `candidates_for_sense`,
  `/api/candidates`, run-row readers, human-review join over
  `factory/linking/human_queue.py` read-only + witness labels + REAL run
  outputs under `runs/`): diagnose WHY the feed shows none (join key mismatch?
  wrong table path? review list never loaded?) — fix the join, never fake data.
- `factory/webui/index.html` (`renderCandidates` + `candidates-status`): render
  REAL candidates; empty state must say WHY (no join vs no data).
- Tests: extend `tests/factory/test_sense_linking_judge_webui.py` (or interface
  file — one place, no duplicates).

## Test-first tests (names)

- `test_candidates_from_real_run_with_reviews` (fixture REAL run + review list → rows render)
- `test_candidates_empty_state_names_cause` (no-join vs no-data distinguished)
- `test_candidates_never_invented` (empty real list returns `[]`, never fabricated)

## Acceptance (verifiable artifacts)

- Named tests green with fixture run + review files cited in-test.
- Diagnosis written in-test (the exact join break + fix), live panel shows
  candidates for a real run carrying human-review lists.
- Human-queue module read-only; no engine logic in adapter.

## Wiring

- Rule: locked real-candidates rule. No callback/router change.
