---
name: fsrs-session-completion-phase-02-timestamp-schema
description: Add rollback-compatible UTC review timestamps before enabling same-day FSRS behavior.
created: 2026-08-09
base_commit: e45a2a9
branch: feat/fsrs-timestamp-schema
status: complete
---

STATE: phase 2/6 — status: complete — merged as PR #318 (aea834e)

# Ticket 02 — Timestamp Schema Expansion

## Blocking Edges

| Dependency | Required evidence |
|---|---|
| Phase 1 | Cleanup PR merged, CI green, live DB verified |
| Branch base | Fresh `feat/fsrs-timestamp-schema` from updated `origin/main` |

## Contract Rules

Rule 6 and the migration portion of Rule 7.

## Scope

| File | Change |
|---|---|
| `services/db/schema.py` | Add nullable `saved_words.last_review_at TEXT` |
| `services/db/schema.py` | Add nullable `saved_words.next_review_at TEXT` |
| `services/db/schema.py` | Add idempotent ALTER migrations for prior databases |
| `services/db/schema.py` | Reset invalid exposed rows lacking `last_review_at` to first-exposure state |
| `tests/test_migration_guards.py` | Require both columns in fresh and upgraded schemas |
| Migration-focused tests | Cover current unexposed rows, anomaly reset, and repeated startup |

## Timestamp Contract

- Timestamp values are timezone-aware UTC ISO strings.
- `last_review_at` records the exact successful grade time.
- `next_review_at` records the exact due instant.
- Existing `next_review` remains a local application-date compatibility field.
- This phase adds the shape only; it does not switch readers or writers.

## Existing-Row Migration

Current read-only evidence on 2026-08-09:

```text
saved_words total: 532
first_exposure_done=1: 0
first_exposure_done=0: 532
```

Expected migration:

```text
all valid unexposed rows:
    last_review_at = NULL
    next_review_at = NULL

unexpected first_exposure_done=1 and last_review_at IS NULL:
    first_exposure_done = 0
    stability = 0.0
    difficulty = 5.0
    last_review_at = NULL
    next_review_at = NULL
    next_review = current APP_TIMEZONE date
    transient review state cleared
```

The anomaly reset is intentionally honest: it does not invent a historical
review timestamp.

## Wiring Map

| Dependency | Disposition |
|---|---|
| Existing grade functions | keep stubs until behavior PR |
| `due_words_for_user` | keep date reader until behavior PR |
| Legacy `next_review` | keep |
| Handler callbacks/keyboards | no changes |
| Module structure | no changes |

## TDD/Test Plan

| Test | Required assertion |
|---|---|
| Fresh DB | both timestamp columns exist and are nullable |
| Prior schema | ALTER adds both columns without data loss |
| Current unexposed row | both timestamps remain NULL |
| Invalid exposed row | deterministic first-exposure reset |
| Valid future row | existing non-null timestamp remains unchanged |
| Idempotency | second `init_db()` changes nothing |
| Rollback compatibility | legacy `next_review` still exists/readable |

## Steps

| Step | Action | Status | Evidence |
|---|---|---|---|
| 1 | Create branch from Phase 1 merge | complete | `feat/fsrs-timestamp-schema` from `origin/main` e45a2a9 |
| 2 | Add failing fresh/upgrade/anomaly tests | complete | `TimestampSchemaMigrationTests` in `tests/test_migration_guards.py` |
| 3 | Add columns and migration logic | complete | `services/db/schema.py` (CREATE + idempotent ALTER + anomaly reset) |
| 4 | Run focused schema/migration tests | complete | `python -m pytest tests/test_migration_guards.py tests/test_db_migrations.py -q` → 27 passed |
| 5 | Run full validation and independent review | complete | Full suite 681 passed + 149 subtests; compile_all; ruff F821/F811 clean; reviewer APPROVED (no MUST-FIX) |
| 6 | PR, CI, merge, and read-only live schema verification | complete | PR #318 merged (squash aea834e); CI green; live DB verification remains an owner-coordinated step |

## Acceptance Criteria

- Schema expansion deploys independently without changing session behavior.
- No existing educational content or review history changes.
- Invalid scheduling state is reset without fabricated history.
- Fresh/upgrade/idempotency tests, full validation, reviewer, and CI pass.

## Blocked Questions

None.
