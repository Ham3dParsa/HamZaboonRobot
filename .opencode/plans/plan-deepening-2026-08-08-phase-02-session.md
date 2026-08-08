# Phase 02 — Session assembly + dormant registry (Finding #4)

Blocking edges: none (independent of phase 01).
Contract rule: #4. Gate: module boundary.
Wiring rows: `services/session/__init__.py` exports; `assembly.py` build_session; `grade_policy.py` registry.

## Status: COMPLETE (2026-08-08)

Committed as `refactor(session): remove dormant registry and duplicate assembler`.
Implementation: removed `build_session` generator + `Generator` import from
`assembly.py`; removed `ACTIVITY_REGISTRY`/`get_interaction_ui`/`ActivityHandler`
+ lazy `config.keyboards` import from `grade_policy.py` (kept `GRADE_POLICIES` +
`resolve_grade`); pruned `__init__.py` `__all__` to the 6 surviving exports.
Tests: `TestACTIVITYRegistry`/`TestAssemblyBuildSession` removed, `TestPublicAPI`
added with exact-equality export pin; `tests/test_dead_code_guard.py` gained 4
`BANNED_SYMBOLS` entries. Independent reviewer approved (no confirmed findings).
Validation: 454 passed, 10 subtests; compile, ruff F821/F811, whitespace clean.

## Scope
- `services/session/assembly.py`: keep `build_session_list` (87-150) as the one seam; remove `build_session` (26-84) (or alias then delete).
- `services/session/grade_policy.py`: remove `ACTIVITY_REGISTRY`, `get_interaction_ui`, `ActivityHandler`; keep `GRADE_POLICIES`, `resolve_grade` (used by srs_handler).
- `services/session/__init__.py`: prune `__all__`.
- Fix the "frontend-agnostic" violation: `grade_policy.py` lazy `config.keyboards` import removed.

## Tests
- Update `tests/test_session_engine.py:91-108` (registry assertions) and :276-291 (`build_session` → `build_session_list`).
- Add: single assembler test — same entry through public API returns isomorphic nodes.
- `study_handler` keeps owning UI rendering (no change to its dispatch).

## Acceptance
- `ACTIVITY_REGISTRY`, `get_interaction_ui`, `ActivityHandler`, `build_session` have zero references (dead-reference guard passes).
- `tests/test_session_engine.py` green after update.
- No learner-facing behavior change.

## Verify
`tests/test_wiring.py`, `tests/test_dead_code_guard.py`, `tests/test_session_engine.py`, `pytest tests/`.
