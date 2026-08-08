# Phase 04 — services/db split (Finding #3)

Blocking edges: none (mechanical, wide blast radius — run before #5/#6/#7 that touch import edges).
Contract rule: #3. Gate: module boundary (structural, zero behavior → fast-track-eligible).
Wiring rows: `services/db/__init__.py` (919 lines) → thin re-export; cost analytics (340-515) + preset registry (517-893) → own modules.

## Status: COMPLETE (2026-08-08)

## Scope
- New module(s), e.g. `services/db/cost_tracking.py` (`record_usage`, `summarize`, `breakdown`) and `services/db/preset_registry.py` (fallback chain, priority reindex, emergency groups).
- `services/db/__init__.py` keeps re-export names **byte-identical** so `from services import db` call sites break nowhere.

## Tests
- Existing db tests green (re-export names unchanged).
- New focused tests: cost aggregation through seam; preset priority reindexing through seam.

## Acceptance
- `services/db/__init__.py` reduced to thin façade; both domains have seams.
- No behavior, quota, scheduling, callback change. No new AI calls.
- `from services import db` call sites (test_db_guard, test_custom_word_query, scheduling, etc.) resolve unchanged.

## Verify
`tests/test_dead_code_guard.py`, db-focused tests, full suite.
