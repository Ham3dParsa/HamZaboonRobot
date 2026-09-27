---
name: factory
scope: Factory console static-asset extraction (factory/webui CSS/JS split + /static/ route) — docs/plans only
---

## Plans & Dependency Edges

| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-webui-static-phase1.md` | 01-css-extract (R1-R4) | — | `implemented-uncommitted` |
| `plan-webui-data-root.md` | 02-shared-data-root (R1-R6: T1 data-root, T2 telemetry-race \|\| T1, T3 files-roots after T1) | `plan-webui-static-phase1.md` | `implemented-uncommitted` |

Ticket list: `TICKETS.md` (when created). Phase 2 (JS extraction) starts only
after owner eyeballs desktop parity on Phase 1 and says proceed.
