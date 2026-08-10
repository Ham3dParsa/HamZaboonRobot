---
name: fsrs-session-completion-phase-05-handler-integration
description: Integrate GradeResult into Telegram grading, relative Persian time, telemetry separation, and later-session behavior.
created: 2026-08-09
base_commit: same-behavior-branch-after-phase-04
branch: feat/phase-3b-fsrs-scheduling
status: blocked
---

STATE: phase 5/6 — status: blocked — focus: wait for grading and due-priority phases on behavior branch

# Ticket 05 — Handler, UX, and Integration

## Blocking Edges

| Dependency | Required evidence |
|---|---|
| Phase 3 | GradeResult and both transitions pass focused DB tests |
| Phase 4 | Timestamp due selection and DSR priority pass focused tests |

## Contract Rules

Rules 8-13.

## Scope

| File | Change |
|---|---|
| `handlers/srs_handler.py` | Consume `GradeResult` in both grade paths |
| `handlers/srs_handler.py` | Record event/touch streak/advance only after successful schedule update |
| `services/utils/formatting.py` | Add plain Persian relative-time formatter |
| `tests/test_srs_staged_reveal.py` | Replace invalid unexposed review fixtures and assert persisted schedule |
| `tests/test_integration/test_srs_callback_routing.py` | Assert callback-to-grade-to-state flow |
| Integration tests | Same-day later-session, quota, telemetry-failure behavior |

## Handler Contract

```text
parse callback and verify callback target user
resolve grade through existing GradePolicy
call grade_first_exposure or grade_word_review

if GradeResult is falsy:
    answer expected Persian error
    do not record event
    do not touch streak
    do not advance session

if successful:
    record review event in separate transaction
    touch streak
    show relative next-review alert
    advance session
```

The grade function owns the database existence/ownership/state read inside its
transaction, so the handler should not make a redundant pre-grade row fetch.

## Persian Time Contract

The exact timestamp stays in the DB. Display uses rounded time:

```text
interval < 24 hours:
    ثبت شد؛ مرور بعدی: حدود N ساعت دیگر.

rounded interval = 1 day:
    ثبت شد؛ مرور بعدی: فردا.

rounded interval > 1 day:
    ثبت شد؛ مرور بعدی: N روز دیگر.
```

`callback_query.answer` uses plain text and no Markdown parse mode. The helper
still belongs in centralized formatting code for natural Persian and testable
copy consistency.

## Session and Quota Contract

- A newly due same-day card is never reinserted into the current session.
- It becomes eligible when a later session starts after `next_review_at`.
- `consume_session_slot` and DB plan limits are unchanged.
- No bonus session is granted.
- If all slots are used, the card remains due for the next allowed session.

Current live plan evidence (2026-08-09):

```text
free=2, bronze=3, silver=3, gold=4, emerald=5 sessions/day
```

## Telemetry Failure Contract

Scheduling commits before `record_review_event`. If telemetry fails:

- The saved-word schedule remains advanced.
- The handler follows the existing error path.
- A missing event is logged/reviewable, but the card is not shown repeatedly
  merely because analytics persistence failed.

## Callback/Wiring Rows

| Callback | Disposition | Required test |
|---|---|---|
| `srs:fe:{grade}:{uid}:{wid}` | keep | routes all grades to first-exposure handler |
| `srs:{grade}:{uid}:{wid}` | keep | routes grades 1-4 to regular-review handler |
| `study:start` | keep | later session rebuilds due queue |
| Keyboard builders | keep | callback strings unchanged |

No callback-data string or top-level router branch changes in this phase, but
integration wiring tests must prove the unchanged routes reach the new state
transitions.

## TDD/Integration Plan

| Flow | Required assertion |
|---|---|
| First exposure | callback persists timestamps/state/event and shows relative alert |
| Regular review | callback persists FSRS transition/event and advances session |
| Wrong state | no event, streak, or advance |
| FE double tap | second tap is harmless `wrong_state` |
| Regular double tap | remains accepted risk; no new identity guard |
| Same-day timing | card absent before due; present in later session after due |
| Current session | graded card is not requeued |
| Quota | no extra session; exhausted user waits |
| Telemetry failure | scheduling remains committed |
| Response time | regular review continues recording `response_time_ms` |
| Raw signal | button value and activity type remain accurate |
| Persian copy | hour/day variants render exactly and naturally |

## Steps

| Step | Action | Status | Evidence |
|---|---|---|---|
| 1 | Rewrite invalid fixtures and add failing integration tests | blocked | — |
| 2 | Add relative-time formatter tests and implementation | pending | — |
| 3 | Integrate GradeResult into first-exposure handler | pending | — |
| 4 | Integrate GradeResult into regular-review handler | pending | — |
| 5 | Add later-session/quota/telemetry-failure integration coverage | pending | — |
| 6 | Run focused handler/wiring/formatting tests | pending | — |
| 7 | Mark behavior branch mergeable only after all Phase 3-5 tests pass | pending | — |

## Acceptance Criteria

- User feedback truthfully reflects the persisted due interval.
- Expected failures cannot create telemetry or skip session nodes.
- Same-day review respects exact due time and existing plan quotas.
- Callback strings remain unchanged and fully wired.
- Phase 3-5 behavior branch passes focused tests as one coherent unit.

## Blocked Questions

None.
