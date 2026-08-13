---
name: fsrs
scope: Complete the FSRS session engine after daily-card migration, including persistence cleanup, timestamp scheduling, grading, and due priority.
---

## Plans & Dependency Edges

| Plan | Phase | Depends On | Status |
|---|---|---|---|
| `plan-fsrs-session-completion.md` | 0..6 | Admin-AI audit PR merged | `in-progress` |
| `plan-saved-word-origin-backfill.md` | prerequisite | Deployed before Phase 1 cleanup | `complete` |
| `plan-fsrs-session-completion-phase-01-daily-schema-purge.md` | 1 | Origin backfill deployed and verified | `in-progress` |
| `plan-fsrs-session-completion-phase-02-timestamp-schema.md` | 2 | Phase 1 merged and verified | `complete` (PR #318 merged) |
| `plan-fsrs-session-completion-phase-03-grade-transitions.md` | 3 | Phase 2 merged and verified | `in-progress` (committed 8c2eb3f) |
| `plan-fsrs-session-completion-phase-04-due-priority.md` | 4 | Phase 3 complete on behavior branch | `blocked` |
| `plan-fsrs-session-completion-phase-05-handler-integration.md` | 5 | Phases 3-4 complete | `blocked` |
| `plan-fsrs-session-completion-phase-06-release.md` | 6 | Phases 1-5 complete | `blocked` |

## Release Boundaries

| PR | Included phases | Merge condition |
|---|---|---|
| Phase 2b cleanup | 1 | Origin backfill verified live; offline migration checks, focused tests, full validation, independent review |
| Timestamp expansion | 2 | Fresh/upgrade schema tests and anomaly-reset evidence |
| FSRS behavior | 3-5 | All three complete together; never merge partial behavior |
| Documentation/release | 6 | Documentation accompanies relevant PRs; final status reconciliation follows verified merge |

## Deferred Contract

The legacy `saved_words.next_review` date column remains in this plan and is
dual-written for rollback compatibility. A future contract may remove it only
after deployed evidence shows all rows and readers use `next_review_at`.

## Completed Dependency Edge

The saved-word origin backfill merged as PR #304 and ran against the live
database on 2026-08-10. Verification recorded
`entry_source_backfilled='1'`, 510 `legacy_daily` rows, 22 `manual` rows, and
562 source `daily_cards` rows before cleanup. Phase 2b therefore removes the
temporary backfill block while dropping the obsolete daily tables.
