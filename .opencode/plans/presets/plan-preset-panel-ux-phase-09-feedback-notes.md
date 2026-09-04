---
name: plan-preset-panel-ux-phase-09-feedback-notes
phase: 9
gates: [U4]
blocking: [phase-07]
status: pending
---
STATE: phase 9 — status: pending — focus: feedback wording + impact notes

## Scope

- Delete dead `notify_callback` toast in `_handle_ai_preset_field_input`
(proven no-op on text path); update `test_field_input_toasts_and_rerenders_menu_once`
to assert NOT called + rename.
- Reword `just_staged` line: `✅ پیش‌نویس «{label}» نگه داشته شد` + pending-count
line (compose without duplicating the count — pending_header already carries it;
pin count==1). Spans only (persian-formatting).
- Confirm notes: keep 🎯/⛓️ conditions; add 🚨 note when is_emergency dirty
(`🚨 پرچم اضطراری عوض می‌شود — ...`) and 🔑 note when api_key dirty; fixed order
🎯→🔑→⛓️→🚨, confirm dialog only.
- Emoji stem docs note: append contract note to phase-03 plan file (docs-only).

## Tests

- Update staged-line test to new wording + count==1; new tests for 🚨/🔑
conditionals (present/absent); toast-removed test.

## Acceptance

- [ ] no "ثبت شد" for staged state anywhere in flow; notes matrix pinned
- [ ] full suite green; `hamzaban-reviewer` 0 confirmed findings
