# Phase 01 — DB transaction hardening (R1)

## Blocking edges
- None (independent of other phases).

## Scope
- `services/db/preset_registry.py` — multi-statement writers only:
  `rename_group_label`, `clear_group_label`, `set_fallback_active`,
  `reindex_preset_priority`.
- Wrap each in explicit try/except + `conn.rollback()` + re-raise on error.
  Single-statement writers (set_preset_priority, set_preset_enabled, etc.) stay as-is
  (self-healing via `get_conn` close).

## Tests
- `tests/test_preset_registry.py` — add a test asserting that a mid-transaction
  failure (e.g. `reindex_preset_priority` raising ValueError with out-of-range rank)
  leaves the DB consistent and the next write succeeds.

## Gates
- R1 (scope-limited preset_registry tx hardening).

## Wiring rows
| Dependency type | Items | Disposition |
|---|---|---|
| DB functions | `rename_group_label`, `clear_group_label`, `set_fallback_active`, `reindex_preset_priority` | update (add rollback) |
| Tests | `tests/test_preset_registry.py` | update/add |

## Acceptance criteria
- All four writers roll back on exception; ValueError in `reindex_preset_priority`
  does not leave a half-applied reindex; focused tests pass.
