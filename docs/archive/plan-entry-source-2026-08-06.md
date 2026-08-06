---
name: entry-source
description: Add additive `entry_source` column to saved_words (manual/auto origin tag); manual write path now, auto deferred to Tier-3
created: 2026-08-06
base_commit: 130941a
merged_commit: 302ad0d
PR: #266
status: implemented
---

> **ARCHIVED 2026-08-06** — Plan completed and fully evaluated. Merged to `main` via PR #266.
> Contract record: `docs/audit/architecture_alignment_2026-08-06.md` (Owner Section 2).
> Issue: #267 (closed resolved).

# entry_source column (Contract Lock B6) — independent half

Adds an additive `entry_source` origin tag to `saved_words`. This is the **independent scope
only** — Rule #2 (backfill `migrate_saved_words_to_fsrs`) is **deferred** and excluded here,
because the v3/FSRS unit phase 2b deletes that function and drops `daily_cards`. Source of
truth: `docs/audit/architecture_alignment_2026-08-06.md` (Owner Section 2, scope revision).

## Locked Contract Rules in scope
| Rule | Decision |
|------|----------|
| #1 | Add `entry_source TEXT DEFAULT 'manual'` to `saved_words` (fresh + ALTER guard) |
| #3 | `add_saved_word(..., entry_source='manual')` kwarg + `_handle_query_add` passes `'manual'` |
| #2 | **DEFERRED** — backfill inside `migrate_saved_words_to_fsrs`; do NOT implement (phase 2b removes it) |

## Scope of this PR

### 1. services/db/schema.py
- `saved_words` CREATE block (~`:109-124`): add `entry_source TEXT DEFAULT 'manual'` to the
  column list (fresh DB path).
- PRAGMA/ALTER guard block (~`:277-302`): add
  `if "entry_source" not in saved_word_columns: ALTER TABLE saved_words ADD COLUMN
  entry_source TEXT DEFAULT 'manual'` — mirrors the `first_exposure_done` pattern.

### 2. services/db/words.py
- `add_saved_word(...)` (~`:180-203`): add optional kwarg `entry_source: str = 'manual'`,
  threaded into the INSERT column list and VALUES.

### 3. handlers/srs_handler.py
- `_handle_query_add` (~`:46`): pass `entry_source='manual'` explicitly in the
  `add_saved_word(...)` call (self-documenting; the sole production caller).

### 4. Tests (AGENTS.md §6 + integration-test-proto)
- `tests/test_migration_guards.py`: add `"entry_source"` to `EXPECTED_COLUMNS["saved_words"]`
  (fresh + upgrade inherit via the shared template); add default-value assertion.
- `tests/test_db_migrations.py` (or words unit test): prior-schema `saved_words` without the
  column + a pre-existing row → `init_db()` adds the column, row gets `'manual'`, no data loss
  (mirror `test_upgrade_preserves_existing_rows`).
- New unit test: `add_saved_word(..., entry_source='auto')` writes `'auto'`; default writes
  `'manual'`.
- Integration (`tests/test_integration/`): `_handle_query_add` flow → row with
  `entry_source='manual'` (extend existing `test_srs_callback_routing.py` style).

## Explicitly out of scope — do not touch
- `migrate_saved_words_to_fsrs` backfill (Rule #2) — deferred to phase 2b.
- `daily_cards` / `daily_progress` / `daily_card_sessions` tables & the phase 2b removal.
- Tier-1/Tier-2 queries (`due_words_for_user`, `get_pre_first_exposure_words`) — tiers remain
  derived; do NOT add entry_source filtering.
- `config/keyboards.py`, `callback_router` — no `callback_data` change.
- Pool / semantic-cache / embedding code (Rules R0-R3, A1-A6, B1-B5).

## Steps
| Step | Description | Status |
|------|-------------|--------|
| 1 | Create branch `feat/entry-source-column` from latest `origin/main` | complete |
| 2 | schema.py: CREATE + ALTER guard columns | complete |
| 3 | words.py: `add_saved_word` entry_source kwarg | complete |
| 4 | srs_handler.py: `_handle_query_add` passes `'manual'` | complete |
| 5 | Tests: migration_guards EXPECTED + default, upgrade row-preserve, unit kwarg, integration flow | complete |
| 6 | Full validation suite (`hamzaban-validation`) | complete |
| 7 | Independent review subagent (`hamzaboon-reviewer`) — READY FOR COMMIT | complete |
| 8 | Commit, push, PR #266; issue #267 created+closed (resolved) | complete |

## Update Log
- 2026-08-06: Plan persisted; scope trimmed to independent rules #1/#3; Rule #2 deferred to
  phase 2b per subagent findings + architecture_alignment Owner Section 2 revision.
- 2026-08-06: Implemented, validated, independently reviewed, PR #266 merged (`302ad0d`),
  issue #267 closed resolved. Archived to docs/archive/ per AGENTS.md §10.4.