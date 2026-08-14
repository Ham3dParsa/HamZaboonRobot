---
name: ux
scope: User-facing UX tickets (feedback, toasts, modals) tracked separately from engine work.
---

## Plans & Dependency Edges
| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-grade-feedback-toast.md` | 1 | PR #300 | `in-progress` |
| `plan-word-query-card-consistency.md` | 1..2 | — (phase 2 on Persistence seam) | `locked-spec` |

## Note
grade-feedback-toast is a separate owner-locked ticket (issue #308), while its feedback UX contract is consumed by the FSRS T05 Handler/UX Integration plan (`.opencode/plans/fsrs/`, epic #309). Feedback uses the shared `notify_callback` module (#311). See `.opencode/plans/TICKETS.md`.
