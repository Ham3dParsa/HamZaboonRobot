---
name: plan-27-per-user-lock-phase-03-tests-wiring
description: Phase 03 wiring + docs update
created: 2026-09-01
base_commit: 9e5184a
branch: fix/per-user-lock
status: pending
---

STATE: phase 03/03 — status: pending — focus: tests + wiring + index

## Scope
- Ensure `tests/test_wiring.py` still passes (no new callback prefix, so no new route needed)
- Update `TICKETS.md` + `index.md` STATE for #27
- Run `compile_all.py`, `ruff F821/F811`, `git diff --check`, `pytest -n 14`

## Blocking edges
- 01,02

## Tests
- `pytest tests/test_wiring.py tests/test_single_source_of_truth.py -q`

## Gates
- Completion

## Wiring rows
| type | item | disposition |
|---|---|---|
| docs | TICKETS.md/index.md | update |
