---
name: plan-session-summary-report-phase-03-render
description: Completion renders the report — tier gate, learner + admin variants, paged detail callback
created: 2026-08-19
branch: feat/session-summary
status: completed
---

STATE: phase 3/3 — status: completed — focus: completion renders report; implemented + tests GREEN

# Phase 3 — Completion renders the report (UI)

Vertical slice: replace the completion message with the report, wired end-to-end.

## Scope
- `handlers/study_handler.py` `advance_session` completion path: call `build_report`, render
  summary (learner for bronze+, admin for owner), keep free plan on the minimal message.
- `config/plan_identity.py`: add `session_summary` feature, min_rank=1.
- `config/keyboards.py`: summary keyboards («جزئیات», page next/back/«بازگشت به خلاصه»).
- `services/routing.py`: register `session:summary:` prefix → summary handler.
- Ephemeral page data in `context.user_data`; stale-button graceful failure («پیام منقضی»).
- Learner-facing Persian text through `services/utils/formatting.py`.

## Gates
- Rules 1 (presentation + pagination), 4 (tier gate + owner admin), 6 (admin detail), 7 (ephemeral).

## Tests
- `tests/test_wiring.py`: `session:summary:` prefix matches the summary handler.
- `tests/test_integration/`: session completes → summary message shown (bronze+); free plan keeps
  minimal; owner sees admin detail; detail pagination advances pages; stale detail button fails
  gracefully.

## Blocking edges
- Phase 1 (report engine), Phase 2 (before-stability snapshot).

## Acceptance criteria
- After a completed session, bronze+ users see the learner summary; owner sees admin variant;
  «جزئیات» paginates; free plan unchanged; wiring + integration tests pass.
