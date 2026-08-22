---
name: plan-freeze-prompt-reveal-phase-04-rename
description: Rename study button label to short form
created: 2026-08-22
base_commit: 51690d0bf305772ed05d01e7fa5ef4edd1a49c4f
branch: fix/freeze-prompt-reveal
status: pending
---

STATE: phase 4/4 — status: pending — focus: label rename

## Blocking Edges
- Depends On: phase 02, phase 03 (UI change last to avoid test churn mid-phases)

## Scope
- `config/keyboards.py:5` `BTN_STUDY_SESSION = "📚 شروع مطالعه"`
- Scan for any hardcoded string "📚 شروع مطالعه امروز" (grep) — handlers/menu texts, bot.py if any reply keyboard fallback, tests assertions
- Update `study_start_keyboard()` docstring
-Update tests: `tests/test_study_handler.py`, `tests/test_wiring.py` (if label asserted), any integration tests checking menu
- No callback_data change (`study:start` stays), so wiring guard unaffected except label

## Contract Rules
- R4

## Tests
- `grep -rn "شروع مطالعه امروز" tests/ config/ handlers/ bot.py` must return 0
- `pytest tests/test_keyboards.py` + `test_study_handler.py` pass with new label

## Gates
- Lightweight: `git diff --check`, ruff

## Wiring Rows
| Dependency type | Items | Disposition |
|---|---|---|
| Keyboard constant | BTN_STUDY_SESSION | update |
| Tests referencing label | multiple test files | update |

## Acceptance Criteria
- Main menu and inline study button show "📚 شروع مطالعه"
- No occurrence of old label in code/tests
- Existing callback `study:start` still routes

## Evidence
- TBD
