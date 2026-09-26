---
name: plan-console-phase-06-token-env
description: T8 one-time token paste plus factory env resolution (P1)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: planned
---

STATE: phase 6 — status: implemented (uncommitted) — one-time supervisor paste (POST /api/supervisor/token via _store_operator_key/key_crypto, names-only status + delete; input cleared on submit) + resolution order process-env → factory file (_factory_env_value PRIMARY) → tempfile → egress loader → lease-policy → encrypted operator store; evidence: 4/4 pinned tests green in tests/factory/test_factory_webui_operator_keys.py, console suites 75 passed (interface+host_port+ctl_output), adapter suites 58 passed, git diff --check clean; placement confirmed: providers panel (#supervisor-card after #master-card); no token generated, no env file written

## Blocking edges

- Blocked by: — (independent; Wave 3 with T4 under region guard).
- Blocks: —.

## Scope (exact files)

- `factory/webui/server.py` (token/env region ONLY): paste endpoint stores via
  `services/db/key_crypto.py` (Fernet, fail-closed — existing seam, read-only
  reuse); value shown ONE time then never returned/logged; operator-key
  surfaces stay names + booleans; factory env file remains PRIMARY resolution
  (`_factory_env_value` / `_load_factory_master_into_process` order: process
  env → factory file → operator store).
- `factory/webui/index.html`: providers-panel paste UI (placement confirm in
  phase; presumed providers panel) with one-time-display handling.
- `tests/factory/test_sense_linking_judge_webui_interface.py` or new
  `tests/factory/test_factory_webui_operator_keys.py` (implementer picks one;
  no duplicate coverage).

## Test-first tests (names)

- `test_token_paste_one_time_only` (second read returns names-only, never value)
- `test_token_encrypted_at_rest` (stored blob decrypts only via `key_crypto`)
- `test_factory_env_primary_resolution` (env/file beats operator store)
- `test_surfaces_names_only` (keys/status endpoints carry no values)

## Acceptance (verifiable artifacts)

- Named tests green; pasted VALUE absent from pages, logs, streams, registry
  file (grep for pasted canary in test).
- Fail-closed: missing master key → no key resolves, never plaintext.

## Wiring

- Rule: locked token/env rules. Secrets names-only. Forbidden zone otherwise
  untouched (no new crypto, no cloud registry writes).
