---
name: nudges
scope: Motivational messages, heat-event nudges, and session-start invitations (#467 dimensions 1-7)
---
## Plans & Dependency Edges
| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-dim1-message-catalog.md` | dim 1/7 | — | `LOCKED` |
| `plan-dim156-nudges-silence.md` | dims 1,5,6 | `plan-dim1-message-catalog.md` | `LOCKED` |
| `plan-dim2-metrics-halflocked.md` | dim 2/7 | `plan-dim156-nudges-silence.md` | `HALF-LOCKED` (MTR-04/BF-1 resolved 2026-09-17; checks 1-2 open) |
| `plan-dim3-ab-calibration-locked.md` | dim 3/7 | `plan-dim2-metrics-halflocked.md` | `LOCKED` (scheduler flag resolved 2026-09-17) |
| `plan-dim4-split-semilocked.md` | dim 4/7 | `plan-dim2-metrics-halflocked.md` | `LOCKED` 2026-09-17 (SPLIT-03 leech drill open) |
| dims 3-7 | 3..7 | `plan-dim2-metrics-halflocked.md` | `pending` |
