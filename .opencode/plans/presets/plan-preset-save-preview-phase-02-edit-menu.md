---
name: plan-preset-save-preview-phase-02-edit-menu
phase: 2
gates: [R2, R5, R6]
blocking: [phase-01]
status: pending
---
STATE: phase 2 — status: pending — focus: edit-menu vertical tables

## Scope

`handlers/admin_ai.py` single-field edit path only (`preset_edits` flow):

- `_edit_ai_preset`: render dirty fields via helper (one vertical قبلی/جدید table per dirty field, WIZARD_FIELDS order); clean fields unchanged; header counter line `N تغییر در انتظار — هنوز ذخیره نشده`.
- `_handle_ai_preset_field_input`: replace `✅ ثبت شد` message with `notify_callback` toast + edit the single menu message in place.
- `config/keyboards/admin.py::ai_preset_edit_keyboard`: `✏️` prefix on dirty rows only; `💾 ذخیره (N)` / `🗑️ دور ریختن همه (N)` counters; no value suffixes on buttons (values live in tables now).
- Masking: api_key rows via `mask_key`; never plaintext.

## Tests

- Extend `tests/test_integration/test_ai_preset_handlers_ux.py`: stage 2 fields → menu shows 2 vertical tables with old+new; counter correct; clean field has no table; api_key masked.
- Full suite green.

## Acceptance

- [ ] Model+Base URL scenario renders like approved demo B on mobile width
- [ ] 1 message lifetime per edit session (edited in place), toast on stage
- [ ] integration tests pass; full validation passes
- [ ] `hamzaban-reviewer`: 0 confirmed findings
