---
name: plan-session-summary-report-phase-02-snapshot
description: Capture before-stability in SessionState + serialization (restart-safe)
created: 2026-08-19
branch: feat/session-summary
status: completed
---

STATE: phase 2 — status: completed — focus: add before_stability snapshot to SessionState

# Phase 2 — Session before-stability snapshot

Vertical slice: the "before" input the report engine reads at runtime, restart-safe.

## Scope
- `handlers/study_handler.py`:
  - Add `before_stability: dict[int, float]` to `SessionState`.
  - Capture before-stability for a node the first time it is rendered (covers build-time and
    tier3-appended nodes) — reads `saved_words.stability` before grading.
  - Serialize/restore in `_state_to_json` / `_state_from_json` so it survives restarts.

## Gates
- Rule 3 (before-stability source, seam-safe — Study seam only).

## Tests
- Unit/integration: snapshot captured on first render; survives `_state_to_json`→`_state_from_json`
  round-trip; missing word → graceful (no crash).

## Blocking edges
- none (independent of phase 1).

## Acceptance criteria
- `SessionState.before_stability` populated and round-trip serialization works; no behavior change
  to grading/scheduling.
