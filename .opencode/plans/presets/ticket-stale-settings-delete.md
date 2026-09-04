STATE: deferred — do NOT implement without a locked contract (schema/data migration).

# Ticket: one-time DELETE of stale `settings.ai_api_key / ai_base_url / ai_model` rows

Source: PR #549 reviews — opencode-agent[bot] issues/549/comments
(5532645555, 5532844113, 5533104497) `[info]`, all "defer reason: zero live
readers, inert; positive fix is a one-time DELETE follow-up".

## Problem
Old DBs keep stale `settings` rows `ai_api_key` (plaintext — the dead
`_encrypt_key_columns` arm no longer touches it), `ai_base_url`, `ai_model`
forever. Runtime ignores them per R17 (549 retired the legacy
`settings→preset` reconcile block; grep on `origin/main` confirms zero
`get_setting("ai_*")` callers outside comments/test fixtures).

## Why deferred (NOT trivially safe)
- Touches the DB migration path (`services/db/schema.py`): needs a
  version-gated, idempotent migration (`DELETE FROM settings WHERE key IN
  ('ai_api_key','ai_base_url','ai_model')`), not a bare delete.
- Backup/restore interplay: `handlers/admin_backup.py` restore flow can
  reintroduce pre-R3A rows — the migration must also run (or be re-runnable)
  after restore. The 549 review cycle explicitly fought over keeping the
  `is_custom` rebuild + R3A `$`-prefix data-fix for exactly this reason;
  a delete-migration must not weaken that repair path.
- Plaintext `settings.ai_api_key` is secret-adjacent: migration logs must
  never echo values (Secrets rule).
- Needs prior-schema upgrade coverage in `tests/test_db_migrations.py`
  (REVIEW.md schema rule: fresh-DB AND prior-schema) + a regression test
  that active presets survive the delete.

## Acceptance criteria for the future PR
1. Idempotent version-gated migration deletes exactly the three legacy keys;
   the orphan `ai_model` catalog entry (`config/catalog.py` `SETTINGS_KEYS`,
   no live `settings_key("ai_model")` reader) is removed in the same PR
   (or its retention explicitly justified in the contract).
2. `tests/test_db_migrations.py`: prior-schema DB with the three rows
   migrates to zero such rows; active presets unchanged.
3. Restore-flow coverage: restoring a pre-R3A backup then migrating leaves
   no stale rows and keeps `is_custom`/R3A repairs intact.
4. No secret values in logs; `git diff --check`, full suite green.

Deliberately out of scope: `.env.example` `AI_BASE_URL/API_KEY/MODEL`
placeholder lines (deployment docs, harmless).
