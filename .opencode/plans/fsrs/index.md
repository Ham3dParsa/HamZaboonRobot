---
name: fsrs
scope: Complete the FSRS session engine after daily-card migration, including persistence cleanup, timestamp scheduling, grading, and due priority.
---

## Plans & Dependency Edges

| Plan | Phase | Depends On | Status |
|------|-------|------------|--------|
| `plan-srs-staged-reveal-phase-01-implementation.md` | 1..3 | FSRS phases 1-6 (merged), AI-preset seams released, spec LOCKED (#338) | Phase 1 `complete` (PR #353 merged 2026-08-15); Phases 2-3 pending |

The FSRS session-completion chain (phases 1-6) is complete and merged; all implementation plans are archived to
`docs/archive/plans/fsrs-2026-08-14/` (see links below). The only remaining FSRS
work is Phase 3b+ (AI Tier-3 `generate_tier3_node()` stub), tracked as a todo in
`project_status.json`; the separate staged-reveal/display-toggle spec remains
active at `.opencode/plans/session/plan-srs-staged-reveal-spec.md` (issue #338).

## Archived Plans (docs/archive/plans/fsrs-2026-08-14/)

| Plan | Phase | Final status |
|---|---|---|
| `plan-fsrs-session-completion.md` | 0..6 | complete — Phases 1-5 merged; T09 done; archived |
| `plan-saved-word-origin-backfill.md` | prerequisite | complete (PR #304, deployed 2026-08-10) |
| `plan-fsrs-session-completion-phase-01-daily-schema-purge.md` | 1 | complete (PR #300 merged) |
| `plan-fsrs-session-completion-phase-02-timestamp-schema.md` | 2 | complete (PR #318 merged) |
| `plan-fsrs-session-completion-phase-03-grade-transitions.md` | 3 | complete (PR #336 merged) |
| `plan-fsrs-session-completion-phase-04-due-priority.md` | 4 | complete (PR #336 merged) |
| `plan-fsrs-session-completion-phase-05-handler-integration.md` | 5 | complete (PR #336 merged) |
| `plan-fsrs-session-completion-phase-06-release.md` | 6 | complete — T09 release gate; live smoke test owner-informally handled (5 sessions worked) |

## Release Boundaries

Phases 1-5 landed as: Phase 2b cleanup (PR #300), origin backfill (PR #304),
timestamp schema (PR #318), and the coherent FSRS behavior Phases 3-5 (PR #336).
The T09 release/docs reconciliation and this archive are the final step.

## Deferred Contract

The legacy `saved_words.next_review` date column remains dual-written for
rollback compatibility; a future contract may remove it after deployed evidence
shows all rows and readers use `next_review_at`.
