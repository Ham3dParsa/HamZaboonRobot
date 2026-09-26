---
name: console
scope: Factory operations console (factory/webui) defect fixes, real-run candidates, view memory, lifecycle — docs/plans only
---

## Plans & Dependency Edges

| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-console.md` | 01-bind (T1) | — | `planned` |
| `plan-console.md` | 02-queue-slim (T3) | — | `planned` |
| `plan-console.md` | 03-ctl-output (T2) | `phase-01-bind` | `planned` |
| `plan-console.md` | 04-view-memory (T6) | — | `planned` |
| `plan-console.md` | 05-noshrink (T4) | `phase-02-queue-slim` | `planned` |
| `plan-console.md` | 06-token-env (T8) | — | `planned` |
| `plan-console.md` | 07-candidates-join (T5) | `phase-02-queue-slim`, `phase-05-noshrink` | `planned` |
| `plan-console.md` | 08-wake-sleep (T7) | `phase-01-bind`, `phase-07-candidates-join` | `planned` |
| `plan-console.md` | 09-ship (T9) | all phases 01–08 | `planned` |

Ticket list: `TICKETS.md`. Wave order: `plan-console.md` §4.
