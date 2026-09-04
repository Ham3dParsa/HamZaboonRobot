---
name: plan-preset-save-preview-phase-05-render-seam
phase: 5
gates: [D2, D4]
blocking: [phase-04]
status: pending
---
STATE: phase 5 — status: pending — focus: shared render seam + interface shrink

## Rule D2 (locked — owner "انجام بده" 2026-09-04, deepening #1)

Internal seam `render_diffs(diffs, *, numbered=False) -> lines` behind the
existing `confirm_summary` interface. `build_confirm_message` and `_edit_ai_preset`
both cross it; caller-side numbering (`admin_ai.py` label rewrite) moves behind
as `numbered: bool`. Menu keeps own chrome (title/picker/counter).
Alternatives rejected: keep mirror loop (fix-twice forever).
Owner Confirmation: "انجام بده".
GATE STATUS: LOCKED

## Rule D4 (locked — deepening #4)

Delete dead `FieldDiff.secret` (written nowhere, read nowhere). 4→3 fields.
Alternative (render-hint 🔑) rejected: styling branch for one caller, §3 drift risk.
Owner Confirmation: "انجام بده".
GATE STATUS: LOCKED
<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE> — satisfied.

## Acceptance

- [ ] one block shape, two callers; numbered on/off pinned by tests
- [ ] `\.secret` grep clean (except docs/changelog)
- [ ] full suite green; `hamzaban-reviewer` 0 confirmed findings
