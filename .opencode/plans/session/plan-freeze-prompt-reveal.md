---
name: plan-freeze-prompt-reveal
description: Freeze staged front prompt + revealed state per active card and rename study button — exploit fix
created: 2026-08-22
base_commit: 51690d0bf305772ed05d01e7fa5ef4edd1a49c4f
branch: fix/freeze-prompt-reveal
status: in-progress
---

STATE: phase 4/4 — status: complete — focus: all phases implemented, tests green

## Locked Contract Reference

Rules locked 2026-08-22 (owner proceed/locked):
- R1 freeze prompt_type of active card (A)
- R2 persist revealed front/back (A)
- R3 resume renders same frozen card, not re-rolled (A)
- R4 rename BTN_STUDY_SESSION to "📚 شروع مطالعه" (A)
- R5 store in SessionState JSON (study_sessions) — DB-backed, restart-safe (A)
- R6 daily discard via session_date check + backward compat (revealed=False, active_prompt_type=None)

GATE: <SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE> — LOCKED

## Phases

| Phase | File | Depends On | Status | Contract Rules |
|-------|------|------------|--------|----------------|
| 1 | `plan-freeze-prompt-reveal-phase-01-model.md` | none | complete | R1,R2,R5,R6 |
| 2 | `plan-freeze-prompt-reveal-phase-02-render.md` | phase 01 | complete | R1,R2,R3 |
| 3 | `plan-freeze-prompt-reveal-phase-03-persist.md` | phase 01 | complete | R1,R2,R3,R5 |
| 4 | `plan-freeze-prompt-reveal-phase-04-rename.md` | phase 02,03 | complete | R4 |

## Acceptance (global)
- Multi resume (callback + restart) never re-rolls prompt and never flips front/back
- Next-day discard verified (yesterday session not resumed)
- Button label "📚 شروع مطالعه" everywhere
- Tests: 3 new integration/unit tests + updated existing resume tests pass
- Wiring guard passes, no DDL migration

## Blocked Questions
- [2026-08-22] R1 day-leak concern: answered — session_date check discards yesterday row, no leak
- [2026-08-22] R5 DB vs memory: answered — JSON lives in study_sessions DB table, restart-safe

## Evidence
- Phase01: SessionState + JSON (handlers/study_handler.py:72-118) — verify_freeze.py PASS, old JSON compat
- Phase02: deterministic render (handlers/study_handler.py:416-662) — t1==t2 freeze, revealed back stable
- Phase03: persist on reveal + advance reset (handlers/study_handler.py:718-930, handlers/srs_handler.py:91-193) — restart test PASS
- Phase04: BTN label (config/keyboards.py:5, handlers/help_command.py:63) — grep "شروع مطالعه امروز" ==0
- Tests: pytest 82 phase-related PASS, full suite 1453 PASS (1 pre-existing unrelated fail)
