# Phase 02 — Validation: name precedence + length caps + group_label (R6, R11)

## Blocking edges
- None.

## Scope
- `handlers/admin_ai.py`:
  - `_handle_ai_preset_new_name` (line 938) — replace `not name.isalnum() and "_" not in name`
    with `not all(c.isalnum() or c == "_" for c in name)` (R6).
  - `_validate_wizard_value` + `_handle_ai_preset_field_input` — add length caps for
    `name` (≤60) and `group_label` (≤40); add non-empty check for `group_label` (R11).

## Tests
- `tests/test_admin_awaiting.py` — add a `my_preset!` re-arm assertion (name with
  underscore + special char must be rejected and keep awaiting).
- `tests/test_admin_ai_module.py` or focused unit tests — length-cap and empty-label
  rejection cases.

## Gates
- R6 (name validation precedence fix), R11 (length caps + group_label validation).

## Wiring rows
| Dependency type | Items | Disposition |
|---|---|---|
| Handler validators | `_handle_ai_preset_new_name`, `_validate_wizard_value`, `_handle_ai_preset_field_input` | update |
| Tests | `tests/test_admin_awaiting.py`, new focused name/label tests | update/add |

## Acceptance criteria
- `my_preset!` rejected + awaiting kept; names >60 and labels >40 rejected;
  empty group_label rejected; existing valid inputs unchanged.
