---
name: pr287-kilo-followups-phase-03-rollback-proof
description: Prove priority reindex rollback preserves state before later writes.
created: 2026-08-09
base_commit: a871300
branch: fix/admin-ai-presets-audit
status: ready
---

STATE: phase 3/3 - status: ready - focus: priority-reindex rollback proof

## Parent

Parent specification issue: #288.
Ticket issue: #291.

## Blocked By

None - can start immediately. This ticket is implemented third only to keep commits small and easy to review.

## What To Build

The priority-reindex regression test proves an invalid requested rank leaves the fallback order unchanged and a later valid reindex succeeds. This verifies the intended transaction behavior without treating connection closure alone as proof.

## Rules

- Contract Rule 4.
- Keep explicit rollback behavior; do not change persistence schema or public behavior.

## Testing

- Extend the existing reindex test to observe unchanged order after the invalid request and a valid later operation.
- Keep tests independent of a production database.

## Acceptance Criteria

- [ ] An invalid rank raises without altering fallback priority order.
- [ ] A subsequent valid reindex succeeds with the expected order.
- [ ] Focused DB tests and full validation pass before commit.

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | None | keep |
| Router branches | None | keep |
| Keyboard builders / constants | None | keep |
| DB tables / columns / functions | Existing priority transaction | keep |
| Handler functions | None | keep |
| Imports / re-exports | None | keep |
| Prompts / formatting helpers | None | keep |
| Tests | Priority-reindex regression test | update |
| Docs / issues | Parent / ticket status | update |
