---
name: factory
scope: Factory console static-asset extraction (factory/webui CSS/JS split + /static/ route) — docs/plans only
---

## Plans & Dependency Edges

| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-webui-static-phase1.md` | 01-css-extract (R1-R4) | — | `implemented-uncommitted` |
| `plan-webui-data-root.md` | 02-shared-data-root (R1-R6: T1 data-root, T2 telemetry-race \|\| T1, T3 files-roots after T1) | `plan-webui-static-phase1.md` | `implemented-uncommitted` |
| `plan-supervised-arbitration.md` | 01-batch-export (R1/R2/R4) \|\| 02-gallery (R6) \|\| 03-local-form (R7) → 04-import-repair (R1/R3) \|\| 05-supervised-ui (R4/R5) → 06-wiring-tests-guide (R4/R6) | — | `in-progress` (W1: P01/P02/P03) |

Ticket list: `TICKETS.md` (when created). Phase 2 (JS extraction) starts only
after owner eyeballs desktop parity on Phase 1 and says proceed.
