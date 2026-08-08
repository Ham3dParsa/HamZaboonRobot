# Phase 03 — Dead wizard keyboard (Finding #2)

Blocking edges: none.
Contract rule: #2. Gate: keyboards.
Wiring rows: `config/keyboards.py:806` `ai_custom_test_wizard_keyboard`; `handlers/admin.py:40` import.

## Status: COMPLETE (2026-08-08)

## Scope
- Delete `ai_custom_test_wizard_keyboard` (config/keyboards.py:806-827) — provably dead (zero call sites), removes latent `from catalog import` ImportError.
- Remove import at `handlers/admin.py:40`.
- Keep live inline keyboard at `_custom_test_step_lang` (admin.py:2291) as canonical.
- Emits same `admin:ai_custom_test:...` prefixes inline — callback_data unchanged.

## Tests
- `tests/test_wiring.py` green unchanged (prefixes identical).
- Wizard `config_tests` integration test still passes.
- Dead-reference guard: zero refs to removed symbol.

## Acceptance
- `ai_custom_test_wizard_keyboard` absent; `catalog` bad-import gone; no emitted callback change.

## Verify
`tests/test_wiring.py`, `tests/test_dead_code_guard.py`, admin integration tests.
