---
name: plan-preset-panel-ux-phase-10-wizard
phase: 10
gates: [U5]
blocking: [phase-07]
status: pending
---
STATE: phase 10 — status: pending — focus: wizard summary alignment

## Scope

Route `_show_wizard_summary` through `_preset_edit_diffs` + shared renderer
(`build_confirm_message`, numbered=False — preserves unnumbered look; keyboard
stays wizard's own). Route-delete old bullet loop + `تعداد تغییرات` line in same
change (adopt shared EMPTY/count strings). Presets wizard ONLY (plans later).

## Tests

- Update wizard-summary integration tests to shared-renderer shape (classify old
bullet asserts as obsolete-by-design, update in place); add renderer-equivalence
assertion (wizard body ≡ confirm body modulo numbered/keyboard).

## Acceptance

- [ ] one diff-rendering shape for wizard + confirm; old loop fully gone
- [ ] full suite green; `hamzaban-reviewer` 0 confirmed findings
