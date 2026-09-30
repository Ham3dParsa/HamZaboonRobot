---
name: plan-arbiter-line
description: LLM arbiter execution capability (engine+CLI+console) then R2 A2 console rebuild
created: 2026-09-28
base_commit: 364d690
branch: feat/arbiter-line
status: in-progress
---

STATE: phase 6/6 — status: complete — focus: PR for feat/arbiter-line (reviewer PASS, 242+ focused tests green, live P4/P5/P6 shots inspected)

## Order (owner-corrected)

Engine capability FIRST (P0–P3), R2 console rebuild AFTER (P4–P5). Rationale:
rebuilding the cabin around a hollow tab-2 repeats the bolt-on failure.

## Gates per phase

- D1–D4 (spec) bind every phase; R5/R8 conventions carry over (separate
  branch, additive, zero live interference, explicit staging, reviewer
  gate before commits, full validation).
- TUI and WUI share one runner module (no duplicated prompt/parse logic).
- Builder never runs live models: stub transports in tests; owner runs
  local/Google models via presets.

## Phases

- `plan-arbiter-line-phase-01-rename.md` (P0: D2 rename + callers)
- `plan-arbiter-line-phase-02-runner.md` (P1: arbiter-runner engine)
- `plan-arbiter-line-phase-03-tui.md` (P2: `judge` CLI — name TBD in phase)
- `plan-arbiter-line-phase-04-endpoint.md` (P3: console endpoint + progress)
- `plan-arbiter-line-phase-05-tab2.md` (P4: real tab-2 UI on the endpoint)
- `plan-arbiter-line-phase-06-r2.md` (P5: R2 A2 overhaul on working tabs)
- `plan-arbiter-line-phase-07-preset-migration.md` (P6: judge→AI-preset migration, D5/D6, independent)

## Blocked Questions

- [2026-09-28] Scope correction: owner clarified "you don't run" ≠ "console can't". Recorded in spec D4 + order above.
