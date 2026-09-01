---
name: plan-27-per-user-lock-phase-02-handler-integration
description: Phase 02 integrate guard into handlers before quota/AI
created: 2026-09-01
base_commit: 9e5184a
branch: fix/per-user-lock
status: pending
---

STATE: phase 02/03 — status: pending — focus: handler integration

## Scope
- `handlers/study_handler.py:handle_study_start` — guard before `consume_session_slot`
- `handlers/srs_handler.py:_handle_srs_review` + `_handle_first_exposure_grade` — guard before FSRS update
- `bot.py:_process_ask_word` + `handlers/user.py:send_grammar_tip` — guard before quota reserve / AI call
- On throttle: `services/utils/callback_notifications.py:notify_callback` with Persian "⏳ کمی صبر کنید..." and return without side effects.

## Blocking edges
- 01 core guard

## Tests
- `tests/test_integration/test_per_user_lock.py`: rapid 6 clicks -> 5 pass, 1 throttled, no quota burn, no AI call

## Gates
- Rules #1, #4

## Wiring rows
| type | item | disposition |
|---|---|---|
| handlers | study/srs/user/bot | update |
