---
name: fsrs-session-completion-phase-03-grade-transitions
description: Implement timestamp-aware first-exposure and regular-review FSRS state transitions with GradeResult.
created: 2026-08-09
base_commit: pending-phase-02-merge
branch: feat/phase-3b-fsrs-scheduling
status: blocked
---

STATE: phase 3/6 — status: blocked — focus: wait for timestamp schema merge; do not merge this phase without Phases 4-5

# Ticket 03 — FSRS Grade Transitions

## Blocking Edges

| Dependency | Required evidence |
|---|---|
| Phase 2 | Timestamp schema PR merged and verified |
| Behavior branch | Fresh `feat/phase-3b-fsrs-scheduling` from updated `origin/main` |
| Release guard | Branch is not mergeable until Phases 4 and 5 complete |

## Contract Rules

Rules 5, 7-10, and 13.

## Scope

| File | Change |
|---|---|
| `services/fsrs_core.py` | Set default `enable_short_term=True` and preserve pure public interface |
| `services/db/words.py` | Add frozen `GradeResult` |
| `services/db/words.py` | Replace `grade_first_exposure` stub with real transaction |
| `services/db/words.py` | Replace `grade_word_review` stub with real transaction |
| `services/db/__init__.py` | Re-export `GradeResult` while preserving both grade function names |
| Focused tests | Replace vacuous return-True tests with state-transition tests |

## Public Interface

```text
GradeResult:
    ok: bool
    reason: "" | "not_found" | "wrong_state"
    next_review_at: aware UTC datetime | None
    interval_seconds: int | None

grade_first_exposure(word_id: int, grade: int, user_id: int) -> GradeResult
grade_word_review(word_id: int, grade: int, user_id: int) -> GradeResult
```

Invalid grades raise `ValueError`. SQLite failures propagate. Both functions
enforce `(word_id, user_id)` ownership inside the same immediate transaction
that reads and updates scheduling state.

## First-Exposure Transition

```text
precondition: first_exposure_done = 0
S = initial_stability_first_exposure(grade)
D = initial_difficulty(grade)
last_review_at = now UTC

if compute_interval(S) < 1 day:
    preserve exact fractional duration
else:
    interval_days = max(1, round(compute_interval(S)))

next_review_at = now + interval
next_review = local date of next_review_at
first_exposure_done = 1
clear transient review state
```

Grade 1 uses stability `0.212`, which yields approximately 5 hours 5 minutes
instead of the superseded forced-one-day rule.

## Regular-Review Transition

```text
precondition: first_exposure_done = 1 and last_review_at present
elapsed_days = exact UTC duration / 86400
D_new = update_difficulty(D_old, grade)

if elapsed_days < 1:
    S_new = short_term_stability(S_old, grade)
else:
    R = compute_retrievability(elapsed_days, S_old)
    S_new = update_stability(D_old, S_old, R, grade)

schedule exact fractional duration below one day
schedule max(1, round(interval)) days at/above one day
update last_review_at/next_review_at/next_review
clear all transient review state
```

The long-term transition deliberately passes the old difficulty into
`update_stability`, matching the locked FSRS recipe; `D_new` is persisted for
the next review.

## Transaction Contract

```text
BEGIN IMMEDIATE
SELECT owned saved_words row
validate grade and exposure state
compute transition without await
UPDATE scheduling and transient fields
COMMIT
return GradeResult
```

Successful updates set:

```text
review_status = 'idle'
review_requested_at = NULL
retry_at = NULL
srs_retry_attempts = 0
```

`record_review_event` is not called from these functions.

## TDD/Test Plan

| Behavior | Required test |
|---|---|
| Grade domain | grades 1-4 accepted; invalid values raise; row unchanged |
| Ownership | missing/foreign row returns `not_found`; no mutation |
| Wrong state | first-exposure-on-done and review-on-undone return `wrong_state` |
| FE grade 1 | exact due timestamp near 5h5m |
| FE grades 2-4 | stability/difficulty and rounded-day schedules match fsrs_core |
| Same-day review | `short_term_stability` output persisted |
| Later review | exact elapsed feeds normal retrievability/update chain |
| Short-term flag | default config is enabled and formula guards remain correct |
| Transient state | all four pending/retry fields cleared on success |
| Dual write | UTC timestamp and APP_TIMEZONE date represent the same due instant |
| Telemetry separation | grade transaction does not write `review_events` |

## Steps

| Step | Action | Status | Evidence |
|---|---|---|---|
| 1 | Create behavior branch from Phase 2 merge | blocked | — |
| 2 | Delete/replace vacuous grading expectations with failing state tests | pending | — |
| 3 | Enable short-term config and implement `GradeResult` | pending | — |
| 4 | Implement first-exposure transaction | pending | — |
| 5 | Implement regular-review transaction | pending | — |
| 6 | Run focused core/DB grading tests | pending | — |
| 7 | Continue directly to Phase 4 without merging | pending | — |

## Acceptance Criteria

- Both grade functions are deep, atomic interfaces with no activity-type flag.
- Same-day and later transitions match the project FSRS-6 reference.
- Expected failures never partially mutate the row.
- Focused tests pass, but the branch remains unmergeable until Phases 4-5.

## Blocked Questions

None.
