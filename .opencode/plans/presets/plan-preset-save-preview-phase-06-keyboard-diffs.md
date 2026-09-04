---
name: plan-preset-save-preview-phase-06-keyboard-diffs
phase: 6
gates: [D3]
blocking: [phase-04, phase-05]
status: pending
---
STATE: phase 6 — status: complete (uncommitted, 2026-09-04) — focus: keyboard as thin adapter — evidence: ai_preset_edit_keyboard(preset_name, diffs=(), has_group=False) + FieldDiff.field identity (dots on field keys, not labels); save_label/discard_label/pending_header in confirm_summary (stems in constants.py, byte-identical strings); single caller _edit_ai_preset passes _preset_edit_diffs output + has_group; table + to_persian_digits imports removed from admin_ai; full suite 1744 passed + 324 subtests (-n 14), compile_all clean, FULL ruff clean (incl. F401), git diff --check clean; test-sync updated in place (render_flow ×4, callback_codec, bytes_escaping ×2, admin_close) + 7 new keyboard diff unit tests + 4 builder tests. NOT committed.

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
