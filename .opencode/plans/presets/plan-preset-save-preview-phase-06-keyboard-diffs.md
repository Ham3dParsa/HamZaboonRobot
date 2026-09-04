---
name: plan-preset-save-preview-phase-06-keyboard-diffs
phase: 6
gates: [D3]
blocking: [phase-04, phase-05]
status: pending
---
STATE: phase 6 — status: pending — focus: keyboard as thin adapter

## Rule D3 (locked — owner "انجام بده" 2026-09-04, deepening #3)

`ai_preset_edit_keyboard` consumes `diffs + has_group: bool` instead of
`(preset, edits)`: thin adapter, no dict logic (repairs §3 logic-in-config smell).
Dirty-state button text (`save/discard` labels + pending header) owned by the
diff-owning module via canonical `to_persian_digits`; `constants.py` keeps static
stems only. `callback_data` strings byte-identical (no wiring change).
Alternatives rejected: keep dual derivation (drift surface).
Owner Confirmation: "انجام بده".
GATE STATUS: LOCKED
<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE> — satisfied.

## Acceptance

- [ ] keyboard unit-testable with synthetic diffs, no DB dicts
- [ ] `tests/test_wiring.py` green (signature change covered)
- [ ] full suite green; `hamzaban-reviewer` 0 confirmed findings
