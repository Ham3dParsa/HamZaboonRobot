---
name: saved-word-origin-backfill
description: Persist legacy daily-card origin before daily_cards is removed.
created: 2026-08-10
base_commit: 6ab4d40eb3eb5754387c31c4ce5cad32a3ea445b
branch: feat/saved-word-origin
status: complete
---

STATE: complete — origin backfill deployed (PR #304) and verified live; daily tables subsequently purged by PR #300. Archived with the completed FSRS chain.

# Saved-Word Origin Backfill

## Purpose

Tag `saved_words` rows imported from the obsolete daily-card engine as
`entry_source='legacy_daily'` before PR #300 removes `daily_cards`.

## Locked Contract

Owner confirmation: "ok then proceed and do that."

| Rule | Locked behavior |
|---|---|
| 1 | Run the one-time backfill from `init_db()`, not a manual CLI. |
| 2 | Use `settings.entry_source_backfilled='1'` for idempotency. If `daily_cards` is absent, log a warning and skip without crashing. |
| 3 | Match `saved_words` to `daily_cards` by user and normalized card word; update matches to `legacy_daily`; leave unmatched rows `manual`. |
| 4 | Merge this branch and run the backfill before PR #300. Update PR #300 to remove the temporary backfill block before its daily-table cleanup ships. |
| 5 | Keep future Tier-3 writes out of scope; they will write `entry_source='auto'` in the Phase 3b+ ticket. |
| 6 | An empty `daily_cards` table completes the harmless no-op and records `entry_source_backfilled='1'`. A pre-existing application database without a usable legacy source logs a warning and also records the flag, so the backfill cannot re-arm and relabel later manual saves. |

## Live DB Evidence (2026-08-10, Read Only)

| Query | Result |
|---|---|
| `settings.fsrs_migration_done` | present; the old migration already ran |
| `daily_cards` rows | 562; source table remains available |
| `saved_words` rows | 532; all currently `entry_source='manual'` |
| Daily-card matches | about 510 distinct saved words; 548 join pairs due to duplicate cards |
| Unmatched saved words | 22; retain `manual` |

## Deployment Evidence (2026-08-10)

The bot was stopped and a SQLite snapshot was created before deployment:
`hamzaban.pre_origin_backfill_20260810_204601.db`, SHA-256
`7e2c209a69a496b2c8dca5dd530bf29e483abccc9f938e3c2bc304b76ea6131f`.
Running PR #304's `init_db()` against the live database produced
`entry_source_backfilled='1'`, 510 `legacy_daily` rows, 22 `manual` rows, and
left all 562 `daily_cards` rows available for Phase 2b. A second run produced
the same counts and `PRAGMA quick_check` returned `ok`.

## Dependency and Wiring Map

| Dependency | Disposition | Verification |
|---|---|---|
| `saved_words.entry_source` | keep; backfill values only | fresh/upgrade tests |
| `settings` | add `entry_source_backfilled` value | idempotency test |
| `daily_cards` | read-only join source | match/unmatched tests |
| `services/db/schema.py:init_db` | add temporary guarded backfill | focused migration tests |
| PR #300 | remove backfill after live execution | post-merge update/review |
| callbacks/keyboards | keep unchanged | wiring guard |

## Test Plan

1. Fresh DB: an empty `daily_cards` table completes the no-op and records the flag.
2. Legacy DB: matching `daily_cards` rows become `legacy_daily`; unmatched rows remain `manual`.
3. Idempotency: a completed flag prevents a second update.
4. Missing table: the pre-`executescript` `should_run` guard skips the backfill without querying `daily_cards`.
5. Existing FSRS migration flag does not suppress this independent origin backfill.

## Steps

| Step | Action | Status | Evidence |
|---|---|---|---|
| 1 | Create isolated branch/worktree and capture live DB evidence | complete | `.worktrees/saved-word-origin`; live read-only query recorded above; baseline `python -m pytest tests/ -n 14`: 594 passed |
| 2 | Write failing focused migration tests | complete | `tests/test_migration_guards.py`: 2 expected failures before implementation |
| 3 | Add guarded backfill to `init_db()` | complete | Canonical raw-word normalization on both sides; exact flag value `'1'`; fresh/partial pre-init distinction; `tests/test_migration_guards.py`: 8 passed |
| 4 | Run focused tests and full validation | complete | Full `python -m pytest tests/ -n 14`: 598 passed; compile, F821/F811 lint, dashboard generation, and whitespace checks passed |
| 5 | Independent review and fix cycle | complete | Final `hamzaboon-reviewer` report: no confirmed findings |
| 6 | Commit, push, and open PR before #300 | complete | PR #304 merged as `bd58566` |
| 7 | Update #300 to remove the temporary backfill block after backfill deployment | complete | Live evidence recorded above; conflict resolution removes temporary code and tests |

## Deliberately Not Done

- No new column: `entry_source` already exists.
- No Tier-3 `auto` write path: Tier-3 remains a Phase 3b+ concern.
- No regrading or preservation of the obsolete engine's progress state.

## Blocked Questions

None.
