---
name: nudges
scope: Motivational messages, heat-event nudges, and session-start invitations (#467 dimensions 1-7)
---
## Plans & Dependency Edges
| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-dim1-message-catalog.md` | dim 1/7 | — | `LOCKED` |
| `plan-dim156-nudges-silence.md` | dims 1,5,6 | `plan-dim1-message-catalog.md` | `LOCKED` |
| `plan-dim2-metrics-halflocked.md` | dim 2/7 | `plan-dim156-nudges-silence.md` | `HALF-LOCKED` |
| `plan-dim3-ab-calibration-locked.md` | dim 3/7 | `plan-dim2-metrics-halflocked.md` | `LOCKED` |
| `plan-dim4-split-semilocked.md` | dim 4/7 | `plan-dim2-metrics-halflocked.md` | `SEMI-LOCKED` |
| dims 3-7 | 3..7 | `plan-dim2-metrics-halflocked.md` | `pending` |
