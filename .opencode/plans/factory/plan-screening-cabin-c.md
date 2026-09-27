---
name: plan-screening-cabin-c
description: Scenario C screening cabin — 12 tickets / 7 phases / 3 waves (backend, cabin, wiring)
created: 2026-09-27
base_commit: 03c6af6f30696b176d04c53fbaca70a2a8e92840
branch: refactor/webui-static-phase1
status: in-progress
---

STATE: phase 0/7 — status: locked — focus: waves/phases ticketed, no implementation started

## Scope

Rebuild `#view-screening` as Scenario C cabin (lock doc `plan-screening-cabin-c-locked.md`): backend gaps first, then cabin UI, then wiring + polish. Same branch, same held `factory/webui` claim — no new claims. No code in this mission; phase files are the build orders.

## Waves & blocking edges

```
Wave 1 backend-only (no UI changes)
  P01 (T01 manifest drop_reasons) ──┐
  P02 (T02 duration helper)         ├──► Wave 2
  P03 (T03 ledger + preview)        │
  P04 (T04 run-status ┬► T05 history │  T06 pins ──► Wave 2 (dialog)
         └────────────┘  SERIAL T04→T05; T06 PARALLEL-safe vs T04/T05
Wave 2 frontend cabin (needs Wave 1 shapes)
  P05 (T07 controls + live tab) ──► Wave 3; T07 needs T01–T04 shapes
  P06 (T08 history tab ∥ T09 dialog+accordion; SERIAL after T05/T06/T07)
Wave 3 wiring + polish (needs Wave 2 DOM)
  P07 (T10 paths+format ∥ T11 validation+collision; T12 SERIAL after T10+T11)
```

## Parallel / serial matrix

| Wave | PARALLEL-safe (disjoint files) | SERIAL (same file / shape dependency) |
|---|---|---|
| 1 | T01 ∥ T02 (writer vs snapshot formatter); T06 ∥ T04/T05 (pins module vs run-status store) | T04→T05 (same store); P01–P04 all → Wave 2 |
| 2 | T08 ∥ T09 (history tab vs dialog module) | T07 before T08/T09 (column DOM + status shape); T05→T08, T06→T09 |
| 3 | T10 ∥ T11 (paths table vs intake/collision) | T12 after T10+T11 (consistency sweep over final DOM) |

## Phase index

| Phase file | Tickets | Depends on | Status |
|---|---|---|---|
| `plan-screening-cabin-c-phase-01-manifest-drop-reasons.md` | T01 | — | `locked` |
| `plan-screening-cabin-c-phase-02-elapsed-duration.md` | T02 | — | `locked` |
| `plan-screening-cabin-c-phase-03-ledger-preview.md` | T03 | — | `locked` |
| `plan-screening-cabin-c-phase-04-runstatus-history-pins.md` | T04, T05, T06 | — (T05 after T04) | `locked` |
| `plan-screening-cabin-c-phase-05-cabin-controls-live.md` | T07 | P01–P04 | `locked` |
| `plan-screening-cabin-c-phase-06-history-dialog-accordion.md` | T08, T09 | P04, P05 | `locked` |
| `plan-screening-cabin-c-phase-07-wiring-polish.md` | T10, T11, T12 | P05, P06 | `locked` |

## Global gates (every implementation PR)

- Contract lock per phase file before code; `<SYSTEM_GATE>` lines per AGENTS.md.
- `python -m pytest tests/factory/ -n 8` + `python scripts/compile_all.py` + `ruff check` F821/F811 + `git diff --check`.
- Desktop + tablet screenshot per ticket (names in phase files); Playwright live-console run, never `file://`.
- Persian text via `persian-formatting` + central escaping; no AI-cost increase (zero new LLM calls — all local read/format).
