---
name: phase-2b-drop-daily-tables
description: Drop daily DB tables and remove the now-dead startup migration after Phase 2a cleanup
created: 2026-08-05
base_commit: (set after Phase 2a merges)
branch: (to be created) feat/phase-2-drop-daily-tables
status: planned
---

# Phase 2b — Drop Daily Tables + Remove Dead Migration (follow-up PR)

Second PR of Phase 2 (Rule 2 = B). Runs AFTER Phase 2a merges. By this point the
stale flows are gone and the `fsrs_migration_done` flag is confirmed set
(validated against `hamzaban.db`: `'1'`), so `migrate_saved_words_to_fsrs()` is
**provably dead** (returns `False` at `words.py:323` forever).

## Locked Contract Rules in scope

| Rule | Decision |
|------|----------|
| 3 | Drop `daily_cards`, `daily_progress`, `daily_card_sessions` + update guards |
| 4 | Rewrite `SchemaMigrationTest` so it does not depend on daily tables |
| 2 (partial) | Remove the now-dead `migrate_saved_words_to_fsrs()` + its startup call |

## Scope of this PR

### A. Schema (`services/db/schema.py`)
- Drop `daily_cards` (CREATE at `133-140`), `daily_progress` (`141-146`), `daily_card_sessions` (`147-155`).
- Remove the `daily_cards` `provenance` ALTER row at `schema.py:349` inside the loop at `348-357`. **KEEP** the `grammar_tips` `provenance` ALTER row at `:350`.

### B. DB functions (`services/db/words.py`)
- Remove daily-table functions: `get_daily_cards` (12), `get_recent_daily_words` (22), `get_recent_daily_card_dates` (57), `count_daily_cards` (67), `add_daily_card` (75), `update_daily_card_fields` (86), `get_daily_progress` (122), `set_daily_progress` (131), `get_daily_card_session` (142), `ensure_daily_card_session` (150).
- Remove `migrate_saved_words_to_fsrs` (312-371) — its SELECT reads `daily_cards`/`daily_card_sessions`.
- Remove their exports from `services/db/__init__.py` (e.g. lines 71, 74, 77-78).

### C. Startup (`bot.py`)
- Remove `db.migrate_saved_words_to_fsrs()` call at `main()` line 1323.

### D. Guards & tests
- `tests/test_migration_guards.py` — remove `daily_cards` (67), `daily_progress` (68), `daily_card_sessions` (69) from `EXPECTED_TABLES`; add a `BANNED_TABLES` set with the three tables.
- `tests/test_dead_code_guard.py` — add BANNED symbols: `migrate_saved_words_to_fsrs`, `get_daily_cards`, `add_daily_card`, `ensure_daily_card_session`, etc., and the three table names.
- `tests/test_integration/test_srs_callback_routing.py` — **rewrite** `SchemaMigrationTest` (lines ~110-253): drop `add_daily_card` setups; assert (a) migration idempotency via the flag (returns `False` on 2nd call) is no longer needed since migration is removed, and (b) first-exposure/due state on `saved_words` works WITHOUT any daily tables.
- `tests/test_wiring.py` — verify no scan-target references the removed daily modules/functions.
- Any remaining test that calls removed daily functions must be updated to construct `saved_words` directly.

## Callback Routing Map changes
- None — Phase 2a already removed the daily/review/srs-prepare/srs-reveal routes. This PR touches no callbacks.

## Steps

| Step | Description | Status |
|------|-------------|--------|
| 1 | Create branch `feat/phase-2-drop-daily-tables` from latest `origin/main` (after 2a merges) | planned |
| 2 | Schema: drop 3 tables + remove daily_cards.provenance ALTER (keep grammar_tips) | planned |
| 3 | Remove daily-table DB functions + `migrate_saved_words_to_fsrs` + exports | planned |
| 4 | Remove startup call in `bot.py main()` | planned |
| 5 | Update guards + rewrite SchemaMigrationTest + fix remaining test refs | planned |
| 6 | Full validation suite (`hamzaban-validation`) | planned |
| 7 | Independent review subagent (`hamzaboon-reviewer`) | planned |
| 8 | Commit, push, PR; update AGENTS.md §3, ROADMAP.md, project_status.json + dashboard, issue #245 | planned |

## Update Log
- 2026-08-05: Plan persisted; contract locked (Rules 2-partial, 3, 4). Awaiting Phase 2a merge.
