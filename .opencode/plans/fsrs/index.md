---
name: fsrs
scope: FSRS persistence migration tickets and dependency-ordered cleanup.
---

## Active Plans

| Plan | Depends On | Status |
|---|---|---|
| `plan-saved-word-origin-backfill.md` | `origin/main`; merge before PR #300 | `in-progress` |

## Dependency Edge

The saved-word origin backfill must merge and run against the live database
before PR #300 drops `daily_cards`. After that, PR #300 must remove the
temporary backfill block.
