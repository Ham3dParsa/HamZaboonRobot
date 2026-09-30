---
name: plan-arbiter-line
description: LLM arbiter execution capability (engine+CLI+console) then R2 A2 console rebuild
created: 2026-09-28
base_commit: 364d690
branch: feat/arbiter-line
status: in-progress
---

STATE: mechanical sprint (R1–R7, owner-proceed 2026-09-30) — status: implemented + validated, uncommitted — focus: owner review gate → commit → PR (NOT committed by builder per sprint order)

## Mechanical sprint (2026-09-30, locked R1–R7 as recommended)

- New: `factory/linking/mechanical_runner.py` (R1–R4 pure mapping),
  `factory/webui/run_log.py` (R5 one owner), `factory/webui/mechanical_jobs.py`
  (R7 deferred_ids, single-flight, RunLog), `mechanical` CLI, `/api/mechanical/*`
  + arbiter `from_run` + enriched verdicts (gloss/candidates/duration) + run logs.
- UI: tab-1 renamed «گزینش نامزدها», manual form deleted (route-delete),
  dense verdict grid tab-2, `<pre>` log + current/elapsed tabs 1–2, tab-3
  active-batch guard («یک بسته فعال در انتظار است», 400 stays backstop).
- History: 4th kind `mechanical` (server join + client action).
- Tests: 8 new/updated suites green (unit 12+4, endpoints 8, interface 102,
  polish 11, noshrink 2, P4/P5/P6 + T07–T12/bc/shell live chunks green,
  new mechanical live e2e green ×4); shots
  `shots/shot-mech-tab2-desktop.png` + `shot-mech-tab3-handoff.png` inspected.
- Pre-existing (base-verified, NOT this sprint): `screening_wake` 3 fail,
  `screening_runstatus` teardown hangs, `t04_02`/`t04_03` isolated-spawn hangs;
  full local suite stays env-flaky (CI arbitrates). Live runs rewrite committed
  `shots/*` binaries — restored before handoff; owner check `git status` at commit.

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
