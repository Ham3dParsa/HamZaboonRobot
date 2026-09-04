---
name: plan-preset-save-preview-phase-05-render-seam
phase: 5
gates: [D2, D4]
blocking: [phase-04]
status: pending
---
STATE: phase 5 — status: complete (uncommitted, 2026-09-04) — focus: shared render seam + interface shrink

Evidence: `render_diffs(diffs, *, numbered=False)` added in
`services/utils/confirm_summary.py`; `build_confirm_message` rewired through
it (+`numbered` flag) and `_edit_ai_preset` consumes it unnumbered;
`_confirm_save_preset` passes raw diffs with `numbered=True` (caller-side
label rewrite + `secret=d.secret` passthrough deleted); `FieldDiff.secret`
deleted (4→3). `\.secret` grep clean in services/handlers/tests (only
`preset_fields` schema-flag prose + this plan mention it). Full suite:
1733 passed + 324 subtests; `test_confirm_summary.py` 10 passed (incl. new
numbered on/off, 0/1/N, byte-identical numbered-vs-manual test);
`compile_all.py` exit 0; ruff F821/F811 clean; `git diff --check` clean.
Full-wizard summary cousin untouched. NOT committed per owner instruction.

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

- [x] one block shape, two callers; numbered on/off pinned by tests
- [x] `\.secret` grep clean (except docs/changelog)
- [x] full suite green; reviewer gate deferred (uncommitted per instruction — run `hamzaban-reviewer` before commit/PR)
