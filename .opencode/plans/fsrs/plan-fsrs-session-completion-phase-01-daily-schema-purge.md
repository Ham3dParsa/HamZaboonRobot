---
name: fsrs-session-completion-phase-01-daily-schema-purge
description: Complete Phase 2b by safely removing daily persistence, the dead migration, legacy TTS daily reads, and interval_idx.
created: 2026-08-09
base_commit: 6ab4d40eb3eb5754387c31c4ce5cad32a3ea445b
branch: feat/phase-2b-drop-daily-tables
status: in-progress
---

STATE: phase 1/6 — status: in-progress — focus: restore-safety pre-commit gate

# Ticket 01 — Phase 2b Daily Schema Purge

## Blocking Edges

| Dependency | Required evidence |
|---|---|
| Admin-AI work | PR merged; working tree no longer carries its uncommitted changes |
| Branch base | Fresh `feat/phase-2b-drop-daily-tables` from latest `origin/main` |
| Maintenance | Bot process stopped; backup path recorded |
| Migration state | Live DB query proves `settings.fsrs_migration_done='1'` |

## Contract Rules

Rules 1-4 from `plan-fsrs-session-completion.md`.

## Scope

| File | Change |
|---|---|
| `services/db/schema.py` | Remove CREATE blocks for `daily_cards`, `daily_progress`, `daily_card_sessions` |
| `services/db/schema.py` | Remove `daily_card_sessions` PRAGMA/ALTER migration block |
| `services/db/schema.py` | Remove `daily_cards.provenance` ALTER row; keep `grammar_tips.provenance` |
| `services/db/schema.py` | Remove `saved_words.interval_idx` from fresh schema and upgrade existing DBs |
| `services/db/schema.py` | Before destructive cleanup, abort if daily tables exist without migration flag |
| `services/db/words.py` | Remove all daily-table functions and `migrate_saved_words_to_fsrs` |
| `services/db/words.py` | Stop writing `interval_idx` in `add_saved_word` |
| `services/db/__init__.py` | Remove deleted re-exports |
| `bot.py` | Remove startup migration call |
| `bot.py` | Remove `_handle_tts_pronounce` source `d`; preserve sources `q` and `s` |

## Explicit Keep/Remove Map

| Item | Disposition |
|---|---|
| `daily_cards`, `daily_progress`, `daily_card_sessions` | remove |
| `get_daily_cards`, `get_recent_daily_words`, `get_recent_daily_card_dates` | remove |
| `count_daily_cards`, `add_daily_card`, `update_daily_card_fields` | remove |
| `get_daily_progress`, `set_daily_progress` | remove |
| `get_daily_card_session`, `ensure_daily_card_session` | remove |
| `migrate_saved_words_to_fsrs` and startup call | remove |
| `saved_words.interval_idx` | remove |
| `review_status`, `review_requested_at`, `retry_at`, `srs_retry_attempts` | keep through Phase 3b |
| `daily_batch_system_prompt` | keep (admin custom-test consumer) |
| one-off scripts and inspect-DB notebook | keep unchanged; document stale |

## Destructive Migration Procedure

1. Stop the bot process.
2. Snapshot `hamzaban.db` and record file path/checksum.
3. Query the migration flag and daily-table existence.
4. If any daily table exists without `fsrs_migration_done=1`, raise a clear startup error before any DROP.
5. Drop daily tables and `interval_idx` only after the guard passes.
6. Start the new version only after focused schema tests and read-only live verification pass.

Fresh databases have no daily tables and no migration flag; the safety gate
must not reject that valid case. The guard applies only when one or more old
daily tables exist.

## Callback/Wiring Rows

| Wiring item | Disposition | Verification |
|---|---|---|
| `tts:pronounce:` top-level route | keep | existing router branch resolves |
| `tts:pronounce:q:*` | keep | keyboard + integration test |
| `tts:pronounce:s:*` | keep | keyboard + integration test |
| legacy `tts:pronounce:d:*` | remove/reject | focused subaction test returns invalid-button alert, no DB read |
| `srs:fe:*`, `srs:1..4:*`, `study:start` | keep | wiring survivor assertions |
| Daily/review callback namespaces removed in Phase 2a | keep removed | dead-reference/wiring guards |

## TDD/Test Plan

| Test area | Required behavior |
|---|---|
| Fresh schema | daily tables and `interval_idx` absent |
| Prior schema upgrade | cards, users, `card_data`, review history, FSRS fields preserved |
| Safety gate | old daily tables + missing flag abort without schema mutation |
| Safe upgrade | old daily tables + flag set cleanly drop |
| Idempotency | repeated `init_db()` remains valid |
| Migration guard | add `BANNED_TABLES`; move `interval_idx` to `BANNED_COLUMNS` |
| Dead-code guard | deleted function symbols absent |
| Integration migration tests | construct `saved_words` directly; no daily helpers |
| Reliability/custom-query tests | replace/remove daily-table fixtures without losing unrelated assertions |
| TTS | `q`/`s` work and `d` is rejected |

## Steps

| Step | Action | Status | Evidence |
|---|---|---|---|
| 1 | Create clean branch and capture preflight DB evidence | complete | branch `feat/phase-2b-drop-daily-tables`; worktree `.worktrees/phase-2b-drop-daily-tables`; base `6ab4d40`; 594 baseline tests passed |
| 2 | Write failing fresh/upgrade/safety tests | complete | `python -m pytest tests/test_migration_guards.py -q`: 3 expected failures (banned tables remain; missing migration abort) |
| 3 | Implement schema guard and destructive cleanup | complete | `python -m pytest tests/test_migration_guards.py -q`: 6 passed; fresh/upgrade/safety and interval_idx removal covered |
| 4 | Remove DB functions, re-exports, startup call, and TTS `d` | complete | `python -m pytest tests/test_dead_code_guard.py tests/test_integration/test_tts_daily_action_removed.py tests/test_migration_guards.py -q`: 19 passed |
| 5 | Update all affected tests and guards | complete | affected focused suites: 93 passed; post-review full `python -m pytest tests/ -n 14`: 596 passed |
| 6 | Run focused and full validation | complete | `tests/test_migration_guards.py`: 7 passed; TTS/custom-query/wiring suite: 33 passed; full `python -m pytest tests/ -n 14`: 596 passed; compile, F821/F811 lint, dashboard generation, and whitespace checks passed |
| 7 | Independent review and fix cycle | complete | Final `hamzaboon-reviewer` report: no confirmed findings; verified the early TTS `d` rejection, migration guard ordering, stale runtime-symbol removal, and focused coverage |
| 8 | PR, CI, maintenance deployment, read-only verification | pending | — |
| 9 | Reject invalid backup before overwriting live DB | complete | Candidate startup + required schema comparison + shared DB lock before atomic replace; restore/admin/migration/wiring/dead guard suite: 38 passed; final reviewer: no confirmed findings; full `python -m pytest tests/ -n 14`: 605 passed; compile, F821/F811 lint, dashboard generation, and whitespace checks passed |

## Acceptance Criteria

- Destructive SQL cannot run on an unmigrated daily DB.
- No runtime reader/writer references removed daily storage or `interval_idx`.
- Existing saved cards and review history survive the upgrade.
- TTS query/saved-word actions remain functional.
- All focused tests, full validation, reviewer, and CI pass.

## Owner Decisions and Deferred Review Findings

- [2026-08-10] The owner confirmed that all legacy `daily_cards` databases
  have already migrated. A pre-existing database with only `interval_idx` and
  no daily tables therefore follows the locked current behavior: drop
  `interval_idx` without requiring `fsrs_migration_done='1'`.
- [2026-08-10] The reviewer requested broader retention snapshots and a
  repository-wide stale-documentation audit. The owner deferred both to Ticket
  06 so this cleanup commit remains limited to its locked scope. Ticket 06
  must verify every retained table/row/schema/index contract and reconcile
  stale daily-runtime references in canonical and tooling documentation.
- [2026-08-10] Kilo found that `import_db_bytes()` overwrites the live DB before
  the new migration guard runs. The owner chose to require exact
  `settings.fsrs_migration_done='1'` in the uploaded backup, reject with a clear
  Persian error before any overwrite, and leave the current DB byte-for-byte
  unchanged. Validation belongs in `import_db_bytes()` so every caller is
  protected. Pre-FSRS backup auto-migration remains deliberately removed.
  Tests use temporary DB files and mocked Telegram only; AI cost is zero.
- [2026-08-10] Independent review found that a marker-valid but structurally
  incompatible backup could still fail after overwrite. The owner locked full
  temporary startup validation: run `init_db()` against the uploaded copy,
  then replace the live DB only after successful initialization. Normal DB
  callers keep their existing default path; callbacks and keyboards remain
  unchanged. Owner confirmation: "Proceed, locked."
- [2026-08-10] A second independent review found two remaining restore gaps.
  The owner locked (1) comparing every required table/column against a freshly
  initialized current-schema reference while allowing extra legacy schema,
  and (2) a shared re-entrant DB lock covering every normal connection lifetime
  and final restore replacement. Tests must cover an incomplete schema that
  startup otherwise accepts and restore while a live connection is open.
  Owner confirmation: "Proceed, locked."

## Blocked Questions

None.
