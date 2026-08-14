---
name: fsrs-session-completion-phase-06-release
description: Validate, independently review, document, release, and archive the completed FSRS session chain.
created: 2026-08-09
base_commit: multiple-phase-merges
branch: multiple-see-main-plan
status: blocked
---

STATE: phase 6/6 — status: blocked — focus: wait for all implementation phases and their focused tests

# Ticket 06 — Review, Validation, Documentation, and Release

## Blocking Edges

| Dependency | Required evidence |
|---|---|
| Phase 1 | Cleanup PR complete, independently reviewed, CI green |
| Phase 2 | Timestamp schema PR complete, independently reviewed, CI green |
| Phases 3-5 | Single coherent behavior PR complete with focused tests |

## Contract Rules

All Rules 1-13.

## Validation Gate

Load `hamzaban-validation`, `pre-commit-gate`, and `git-protocol` before any
commit/PR operation. Required local validation:

```powershell
python -m pytest tests/ -n 14
python scripts/compile_all.py
python -m ruff check --select F821,F811
python scripts/generate_dashboard.py
git diff --check
git diff --staged --check
```

Also verify:

- No secrets or raw API keys in diffs/staging.
- Branch names match repository convention.
- Only intended files are explicitly staged.
- Fresh and upgrade schema tests both pass.
- Re-run the Phase 2b preservation test as a whole-database snapshot: every
  retained table's rows, schema attributes, and indexes survive; an aborted
  destructive migration leaves the database unchanged.
- Wiring and dead-reference guards pass.
- No leftover removed symbols/tables/columns.

## Independent Review Gate

For each behavioral/schema PR:

1. Launch `hamzaboon-reviewer` with the locked contract and current diff.
2. Fix every confirmed finding without widening scope.
3. Re-run focused tests and full validation.
4. Re-run reviewer until no confirmed findings remain.
5. Halt for owner decision if reviewer exposes a genuine product ambiguity.

## Documentation Matrix

| Information changed | Canonical document/action |
|---|---|
| Active execution state | update `.opencode/plans/fsrs/index.md` and ticket `STATE` after every step |
| FSRS architecture/status | reconcile `docs/plans/fsrs/plan_fsrs_migration_v2.md` |
| Daily-card migration status | reconcile `docs/plans/fsrs/plan_daily_cards_migration.md` |
| Cleanup phase status | reconcile `docs/plans/fsrs/plan_fsrs_session_cleanup.md` |
| Phase progress/decisions | update `project_status.json`; regenerate dashboard |
| Product roadmap narrative | update `ROADMAP.md` only where completed/remaining scope changes |
| Issue state/evidence | update relevant GitHub issues with tests/PR evidence and review date |
| Callback map | update callback-wiring docs for removed legacy actions; runtime prefixes unchanged |
| Legacy runtime references | audit `README.md`, `ROADMAP.md`, `project_status.json`, callback-wiring, and tool documentation; reconcile stale `daily_cards` claims |
| Module responsibilities | no module-table change expected because no new module is added |
| Historical audits | keep unchanged; cite them from plans rather than rewriting evidence |

The documentation must explicitly record:

- Phase 2a and 3a are complete.
- Phase 2b dropped daily persistence and `interval_idx` safely.
- `last_review_at`/`next_review_at` are canonical exact scheduling timestamps.
- Legacy `next_review` remains temporarily for rollback compatibility.
- Short-term mode is now enabled globally.
- First-exposure grade 1 is no longer forced to one day.
- Same-day due means a later session and never bypasses plan quotas.

## Release Runbook

### Phase 1 destructive cleanup

1. Confirm maintenance window.
2. Stop bot.
3. Snapshot DB and record checksum/path.
4. Confirm migration flag and expected row/table counts.
5. Deploy cleanup release and initialize DB.
6. Run read-only integrity queries.
7. Start bot and smoke-test start/query/TTS/SRS routes.

### Phase 2 additive schema

1. Deploy timestamp expansion.
2. Verify columns and anomaly-reset query read-only.
3. Confirm behavior remains unchanged.

### Phase 3-5 behavior

1. Deploy coherent behavior release only after all three phases pass.
2. Smoke-test first exposure, later same-day due, regular review, and quota denial.
3. Verify persisted timestamps/state/event rows read-only.
4. Monitor errors for DB locks, invalid timestamp parsing, and callback failures.

## Plan Completion and Archive

Only after all PRs are merged, CI is green, and post-deploy checks pass:

- Mark all ticket states complete with concrete evidence.
- Add a final verdict to the main plan.
- Move completed main/ticket plans to `docs/archive/` with date suffixes.
- Leave `.opencode/plans/fsrs/index.md` with no active plan and archive links.

Required final verdict fields:

```text
Done:
Deliberately Not Done:
Deferred:
Uncertain:
```

## Steps

| Step | Action | Status | Evidence |
|---|---|---|---|
| 1 | Run focused subsystem tests after each implementation phase | blocked | — |
| 2 | Run full validation before every commit/PR | pending | — |
| 3 | Complete independent review/fix cycles | pending | — |
| 4 | Update canonical docs/issues/dashboard | pending | — |
| 5 | Monitor PR CI and recover failures | pending | — |
| 6 | Execute release runbooks and smoke tests | pending | — |
| 7 | Archive plans with final verdict | pending | — |

## Acceptance Criteria

- Every locked rule has implementation and test evidence.
- Full validation, reviewer, and CI are clean for each PR.
- Canonical docs match merged code and deployed state.
- Legacy `next_review` removal remains explicitly deferred.
- Plans are archived only after post-deploy verification.

## Blocked Questions

None.
