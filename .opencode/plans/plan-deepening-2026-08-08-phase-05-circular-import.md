# Phase 05 — bot.py↔admin.py circular import (Finding #5)

Blocking edges: phase 04 (db split) optional but recommended first.
Contract rule: #5. Gate: module boundary.
Wiring rows: `handlers/admin.py:462` `from bot import _apply_log_level`; `bot.py` top-level import of handlers.admin.

## Status: COMPLETE (2026-08-08)

## Scope
- Move `_apply_log_level` (runtime-config helper) into a shared home (e.g. `config/` helper or `services/utils/helpers.py`).
- `bot.py` and `handlers/admin.py` both import it from there — removes the backward edge and latent cycle.
- Strengthen `tests/test_wiring.py` reverse guard (`_resolve_import` :52, used :225) to flag any future handler→bot import (currently treats `bot` as external/trusted).

## Tests
- New/updated wiring test: handler→`from bot import` is flagged.
- Import graph test: each submodule imports independently (no cycle).

## Acceptance
- No `from bot import` in handlers.
- Reverse guard catches handler→bot regressions.
- No callback/keyboard/behavior change.

## Verify
`tests/test_wiring.py`, `tests/test_dead_code_guard.py`, full suite.
