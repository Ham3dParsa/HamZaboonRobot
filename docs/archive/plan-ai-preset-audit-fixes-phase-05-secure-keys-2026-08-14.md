---
name: ai-preset-audit-fixes-phase-05-secure-keys
description: Encrypt AI preset API keys at rest (Fernet) via a deep key_crypto module
created: 2026-08-14
base_commit: 45929ce
branch: feat/ai-preset-secure-keys
status: implemented
archived: 2026-08-14
---

STATE: phase 5/7 — status: implemented & merged (PR #339, commit 0d9a491) — done: key_crypto deep module (encrypt_secret/decrypt_secret/mask_key/encrypt_for_storage) + re-export; resolve_api_key now decrypt-only ($ENV removed); write-side encryption in set_preset/set_preset_api_key_batch/set_group_key; R3 _encrypt_key_columns migration; ai.py decrypts ai_api_key fallback; mask_key centralized in admin_ai.py + admin.py; requirements adds cryptography; .env.example + AGENTS.md + hamzaboon-ai.md updated. Additions during Kilo review loop: v1: version marker on stored ciphertext, MasterKeyRequiredError fail-closed writes, dropped unreachable fail_closed param; tests/conftest.py autouse TEST_MASTER_KEY. Tests: 876 passed (+153 subtests, -n 14) incl. new migration/key_crypto/group/manager/integration tests. Independent hamzaboon-reviewer: no confirmed bugs. Archived 2026-08-14.

## Scope (locked rules)

Contract locked 2026-08-14 (owner chose all recommended options A):
- R1: Fernet master key from env var `AI_MASTER_KEY`; fail-closed if missing.
- R2: Encrypt all three storage sites: `ai_presets.api_key`, `preset_groups.api_key`, `settings.ai_api_key`.
- R3: Migration resolves existing `$ENV` refs to real values and encrypts them; empty if env unset.
- R4: `resolve_preset_key` decrypts; `$ENV` resolution path removed.
- R5: One shared mask helper (`mask_key`) replacing 3 inline copies.
- R6: Unreadable key → fail-closed (return empty), warn WITHOUT literal, surface clear admin error.

## Design (codebase-design: deep module)

New deep module `services/db/key_crypto.py` — small interface hiding Fernet/master-key/fail-closed logic:
- `encrypt_secret(plaintext: str) -> str` ('' for empty input)
- `decrypt_secret(token: str) -> str` (fail-closed: '' + warning, never throws)
- `mask_key(plaintext: str) -> str` (consistent `sk-abc…wxyz` display)

Callers cross this seam: registry write paths (set_preset, set_preset_api_key_batch, set_group_key, activate_preset, clone), resolver (resolve_preset_key), schema migration, and handlers (masking). AI cost impact: none (config-layer only, no new AI calls).

## Files
- `services/db/key_crypto.py` (new deep module)
- `services/db/preset_registry.py` — encrypt on write; decrypt in resolve_preset_key
- `services/ai/ai_presets.py` — remove `$ENV` path from resolve_api_key
- `services/db/schema.py` — R3 migration (resolve $ENV + encrypt)
- `handlers/admin_ai.py`, `handlers/admin.py` — use mask_key; remove `$ENV` acceptance/help text
- `config/__init__.py` — load AI_MASTER_KEY
- `.env.example` — AI_MASTER_KEY var
- `requirements.txt` — add cryptography
- `AGENTS.md §3` — F2: encrypted-at-rest
- Tests: `tests/test_key_crypto.py` (new), `tests/test_ai_preset_api_key.py` (update R3/R3B), `tests/test_preset_groups.py` (update), `tests/test_db_migrations.py` (R3 migration), `tests/test_integration/` (set/get masked)

## WIRING (Dependency & Wiring Map)
| Dependency | Items | Disposition |
|---|---|---|
| Callback prefixes | none added/changed | keep |
| Router branches | none | keep |
| DB tables/columns | ai_presets.api_key, preset_groups.api_key, settings.ai_api_key (values encrypted, no schema change) | update |
| Handler functions | _show_ai_preset_view, _detect_key_groups, _handle_ai_text_input (batch key), _edit_ai_preset_field | update |
| Imports | db.resolve_preset_key (unchanged), ai_presets.resolve_api_key | update (drop $ENV) |
| Prompts/formatting | _FIELD_HELP api_key Persian text, _show_help_presets | update |
| Tests | test_ai_preset_api_key.py, test_preset_groups.py, test_db_migrations.py | update |

## Steps
- [ ] TDD unit tests for key_crypto (RED)
- [ ] Implement key_crypto (GREEN)
- [ ] TDD R3 migration test (RED)
- [ ] Schema migration + write-side encryption in preset_registry
- [ ] Update resolve_preset_key / drop $ENV in ai_presets
- [ ] Centralize mask_key in handlers + Persian help
- [ ] .env.example, requirements, config, AGENTS.md, docs
- [ ] Integration tests (set/get masked)
- [ ] Full validation + guards
- [ ] Independent reviewer
- [ ] PR + Kilo review loop

## Blocked Questions
- (none — contract locked, all 6 rules owner-chosen)