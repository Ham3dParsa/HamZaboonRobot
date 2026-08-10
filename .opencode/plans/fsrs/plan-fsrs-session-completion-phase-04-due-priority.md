---
name: fsrs-session-completion-phase-04-due-priority
description: Select exact timestamp-due Tier-1 cards and order them deterministically by DSR priority.
created: 2026-08-09
base_commit: same-behavior-branch-after-phase-03
branch: feat/phase-3b-fsrs-scheduling
status: blocked
---

STATE: phase 4/6 — status: blocked — focus: wait for Phase 3 transition helpers on behavior branch

# Ticket 04 — Due Selection and DSR Priority

## Blocking Edges

| Dependency | Required evidence |
|---|---|
| Phase 3 | Grade/timestamp helpers implemented with focused tests |
| Release guard | Behavior branch remains unmergeable until Phase 5 |

## Contract Rules

Rules 7, 11, and 12.

## Scope

| File | Change |
|---|---|
| `services/db/words.py` | Update `due_words_for_user` timestamp eligibility and fallback |
| `services/db/words.py` | Add private pure DSR ordering helper(s) |
| Focused DB tests | Prove filters, timestamp boundary, fallback, and full sort key |
| Session-engine tests | Preserve Tier-1 before Tier-2 assembly behavior |

## Eligibility Contract

Tier-1 rows retain all existing filters:

```text
user_id matches
first_exposure_done = 1
review_status != 'pending'
retry_at IS NULL
```

Due time:

```text
next_review_at present -> compare exact UTC timestamp to now UTC
next_review_at NULL    -> fall back to legacy next_review <= APP_TIMEZONE today
```

The fallback exists only during compatibility. Phase 2 resets invalid exposed
rows, and all newly graded rows dual-write both fields.

## DSR Priority Contract

Rows are sorted in Python using pure `fsrs_core` math:

```text
1. compute_retrievability(elapsed_fractional_days, stability) ASC
2. difficulty DESC
3. effective due timestamp/date ASC
4. saved_words.id ASC
```

Difficulty is a tie-breaker only after equal retrievability, exactly as the
owner specified. The final date/ID keys make ordering restart-safe and testable.

## Performance Contract

- SQLite performs ownership/state eligibility filtering.
- Python computes R and sorts only that user's eligible due rows.
- No SQLite math UDF, cache, new index, or public ordering helper is introduced.
- `build_session_list` continues applying `max_nodes` after ordered rows return.

## TDD/Test Plan

| Behavior | Required assertion |
|---|---|
| Future timestamp | excluded before exact instant |
| Boundary timestamp | included at/after exact instant |
| Legacy date | valid fallback path |
| FE/pending/retry filters | byte-for-byte semantics preserved |
| R priority | lower retrievability first |
| D tie | higher difficulty first when R equal |
| Due tie | older due instant first |
| Final tie | lower ID first |
| Stability floor | zero stability does not crash |
| Fractional elapsed | same-day R uses hours, not zero/full-day truncation |
| Assembly | Tier 1 remains before Tier 2 and respects max_nodes |

## Steps

| Step | Action | Status | Evidence |
|---|---|---|---|
| 1 | Write failing timestamp/filter/order tests | blocked | — |
| 2 | Implement effective-due and elapsed helpers | pending | — |
| 3 | Replace overdue SQL ordering with DSR Python ordering | pending | — |
| 4 | Update session-engine mocks/expectations only where behavior changed | pending | — |
| 5 | Run focused DB/session tests | pending | — |
| 6 | Continue directly to Phase 5 without merging | pending | — |

## Acceptance Criteria

- No same-day card appears before its exact due instant.
- Every eligible due card has deterministic DSR ordering.
- Existing pending/retry/Tier ordering remains intact.
- Focused tests pass; branch still waits for handler integration.

## Blocked Questions

None.
