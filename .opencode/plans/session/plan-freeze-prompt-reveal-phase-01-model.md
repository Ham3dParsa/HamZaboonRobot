---
name: plan-freeze-prompt-reveal-phase-01-model
description: SessionState model + JSON serialization for frozen prompt/revealed
created: 2026-08-22
base_commit: 51690d0bf305772ed05d01e7fa5ef4edd1a49c4f
branch: fix/freeze-prompt-reveal
status: pending
---

STATE: phase 1/4 — status: pending — focus: extend SessionState

## Blocking Edges
- Depends On: none (root)
- Blocks: phase 02, phase 03

## Scope
- File: `handlers/study_handler.py`
  - `SessionState` dataclass: add `revealed: bool = False`, `active_prompt_type: str | None = None`, `active_prompt_word_id: int | None = None` (ties prompt+reveal to word_id to avoid stale reuse if nodes reordered)
  - `_state_to_json`: serialize new fields
  - `_state_from_json`: deserialize with backward compat defaults (missing -> False/None), coerce int for word_id
- No DB DDL, no other modules

## Contract Rules
- R1,R2,R5,R6

## Tests
- Unit: `tests/test_study_handler.py` — add `TestStateSerializationBackwardCompat` (old JSON loads, new JSON round-trips)
- No handler behavior yet

## Gates
- ruff F821/F811, compile_all
- pytest -k state serialization

## Wiring Rows
| Dependency type | Items | Disposition |
|---|---|---|
| Handler dataclass | SessionState | update |
| Persistence helpers | _state_to_json/_state_from_json | update |

## Acceptance Criteria
- `SessionState(revealed=True, active_prompt_type="meaning", active_prompt_word_id=123)` round-trips via JSON
- Old JSON (without keys) loads as revealed=False, prompt=None (no crash)
- `pytest tests/test_study_handler.py -k serialization` pass

## Evidence
- TBD
