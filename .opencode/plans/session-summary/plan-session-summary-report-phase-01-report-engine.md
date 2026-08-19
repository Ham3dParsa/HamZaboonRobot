---
name: plan-session-summary-report-phase-01-report-engine
description: Pure report engine (counts, per-word rows, admin variant, pagination slicing)
created: 2026-08-19
branch: feat/session-summary
status: completed
---

STATE: phase 1 — status: completed — focus: build + unit-test services/session/summary.py

# Phase 1 — Report engine (pure)

Vertical slice: the data layer for the report, fully testable in isolation, no Telegram imports.

## Scope
- New `services/session/summary.py` (deep module, small interface):
  - `build_report(...)` → a structured `SessionReport` (dataclass) from inputs:
    - graded word ids + activity types (from session nodes / graded list)
    - per-word rows: after-stability (`saved_words.stability`), before-stability snapshot,
      prior date (`saved_words.last_review_at`), grade + activity (from `review_events`), word text
    - plan + is_owner flag → selects learner vs admin variant
  - Computes: counts (learned = first_exposure, reviewed = srs_review), per-word rows, admin rows
    (before→after stability, interval days, next-review date, difficulty, grade), and a summary line
    (average stability change).
  - `paginate(...)` → slices rows into pages (page size constant).
- No DB writes, no Telegram.

## Gates
- Rules 2 (prior date), 3 (stability before/after + grade), 5 (grouped counts + list), 6 (admin).

## Tests
- `tests/test_session_summary_module.py` (unit): counts split, per-word row fields, prior-date
  fallback when `last_review_at` missing, admin vs learner variant, pagination slicing, empty/edge
  cases (single word, many words, no first-exposure).

## Blocking edges
- none (can start immediately).

## Acceptance criteria
- `build_report` returns correct counts/rows for a fixture; admin variant includes FSRS precision;
  pagination slices correctly; unit tests pass.
