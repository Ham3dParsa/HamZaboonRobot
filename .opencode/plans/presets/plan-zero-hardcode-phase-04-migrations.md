---
name: plan-zero-hardcode-phase-04-migrations
description: Retire dead migrations (candidate C)
created: 2026-09-04
base_commit: 6ad2fb6ca704bd8c624339c62130c7e59522a87c
branch: fix/preset-zero-hardcode
status: pending
---
STATE: phase 4/4 — status: complete — focus: implemented, validated, committed (T4)

Evidence:
- services/db/schema.py: reconcile block deleted; is_custom rebuild deleted;
  HpOF $ fix deleted; grep services/ for is_custom|HpOF|_migration_preset_synced → zero hits.
- tests/test_admin_awaiting.py mock gains candidate_preset (test-obsolete-fixed).
- tests/test_ai_preset_api_key.py → zero-preset + muse-revert regression only.
- tests/test_db_migrations.py → additive-only migration + preset-only encryption.
- Full suite: 1673 passed, 324 subtests passed; compile_all.py clean;
  ruff F821/F811 clean; git diff --check clean.

## Blocking edges
- Phase 3 reviewed (no stale readers left to justify the sync).

## Scope (delete only)
- `services/db/schema.py:839-880` → entire reconcile block (URL + api_key arms, `_migration_preset_synced` write).
- `services/db/schema.py:989-1003` → `is_custom` rebuild.
- `services/db/schema.py:1004-1014` → HpOF `$` fix.
- Keep: pointer seeds `801-818`, additive DDL `932-981`, `_encrypt_key_columns`, `preset_groups` orphan cleanup, fsrs guards.

## Tests (same PR, test-sync rule)
- Rewrite `tests/test_ai_preset_api_key.py:52-159` → zero-preset + encryption only.
- Rewrite `tests/test_db_migrations.py:158-280` (drop is_custom/HpOF paths, keep fresh-schema guards) + `332-442` (keep encryption, drop `settings.ai_api_key` arm).
- Keep `test_ai_preset_manager.py:79,94`, `test_ai_preset_handlers_ux.py:135`, `test_admin_ai_module.py:154-156` as fresh-schema guards.
- No test asserts S5 copy (evidence it is dead) — deletion must break no test; if one does, classify bug-vs-obsolete per test-sync rule (ask owner if uncertain).

## Gates
- Satisfies R4, R5. `hamzaban-reviewer` after implement. Full suite + wiring + dead-reference guard.

## Acceptance
- Fresh DB boots with zero presets; saved muse preset survives restart (regression test for the reported revert).
- `grep -rn "is_custom\|HpOF\|_migration_preset_synced" services/` → zero hits (tests excluded).
- Reviewer: 0 confirmed findings → single PR → kilo-ci-loop until mergeable.
