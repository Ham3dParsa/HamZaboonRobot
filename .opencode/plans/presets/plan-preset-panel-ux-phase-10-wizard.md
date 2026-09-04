---
name: plan-preset-panel-ux-phase-10-wizard
phase: 10
gates: [U5]
blocking: [phase-07]
status: complete
---
STATE: phase 10 — status: complete — focus: wizard summary alignment (implemented 2026-09-04, uncommitted in feat/preset-panel-ux worktree)

## Evidence

- `handlers/admin_ai.py::_show_wizard_summary` routes through
  `_preset_edit_diffs` (WIZARD_FIELDS order, display_value-masked) +
  `build_confirm_message(..., numbered=False)` with title
  "📋 خلاصه تغییرات برای «{name}»"; keyboard untouched (wizard
  save-all/cancel pair); backend HTML → RICH (Table spans raise under
  HTML, verified in `services/send_pretty.py::_render_html`).
- Route-deleted same change: `• {label}: {old} → {new}` bullet loop,
  `تعداد تغییرات: N` line, `هیچ تغییری اعمال نشد.` line, locals
  `changed/old_val/new_val/label`. Surviving old-copy occurrences are
  plans-wizard only (`handlers/admin_plans.py:205-206`) — out of scope.
- Tests: new `AiPresetWizardSummaryTest` (5 tests) in
  `tests/test_integration/test_ai_preset_handlers_ux.py` incl.
  renderer-equivalence (`wizard rendered ≡ build_confirm_message(...,
  numbered=False)`). No pre-existing bullet asserts existed to migrate
  (only `assertNotIn` guards added).
- Validation: full `pytest tests/ -n 14` → 1786 passed + 324 subtests;
  `compile_all.py` pass; `ruff F821/F811/F401` clean on touched files;
  `git diff --check` clean. `test_dead_code_guard` green (no module
  symbols added/removed). NOT committed per instruction.

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
