---
name: plan-27-per-user-lock-phase-01-core-guard
description: Phase 01 core sliding-window guard in scheduling
created: 2026-09-01
base_commit: 9e5184a
branch: fix/per-user-lock
status: pending
---

STATE: phase 01/03 — status: pending — focus: scheduling guard

## Scope
- Add `services/scheduling.py:check_per_user_rate(user_id, action, now) -> bool` + `record_per_user_action`
- In-memory `deque` per user+action, window 10s, limit 5 (costly actions: study_start, query_ask, srs_grade, grammar_tip). Configurable via `settings` optional.
- Pure function, no DB transaction across await, thread-safe via `asyncio.Lock` per user bucket.

## Blocking edges
- None

## Tests
- `tests/test_per_user_lock_unit.py`: window expiry, limit hit, different actions isolated, different users isolated

## Gates
- Rules #3, #4

## Wiring rows
| type | item | disposition |
|---|---|---|
| scheduling | check_per_user_rate | add |
