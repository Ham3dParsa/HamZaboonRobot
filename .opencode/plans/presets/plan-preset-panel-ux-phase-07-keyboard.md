---
name: plan-preset-panel-ux-phase-07-keyboard
phase: 7
gates: [U1, U2]
blocking: []
status: pending
---
STATE: phase 7 — status: pending — focus: 2-col keyboard + name icon

## Scope

`config/keyboards/admin.py::ai_preset_edit_keyboard` — pair related field buttons
2-per-row (pairs in plan U1; API Key solo; detach solo conditional; full-edit solo;
[save|discard], [cancel|close]). `config/keyboards/constants.py` — IBTN_FIELD_NAME =
"🆔 نام پریست" (dirty guard startswith-"✏️" keeps working). TEXT-only change:
every `callback_data` byte-identical (verify by diff). Keep labels short enough
for half-width buttons (shorten only if a label demonstrably overflows; pin texts).

## Tests

- Update `tests/test_ai_preset_edit_keyboard.py`: row-pairing assertions (which keys
share a row), 🆔 present on name row clean+dirty, single ✏️ on dirty name,
callback_data shape unchanged. Test-sync in place.
- `tests/test_wiring.py` green (no new prefixes).

## Acceptance

- [ ] 19 field buttons in specified pairs; actions paired; callback_data identical
- [ ] full suite green; `hamzaban-reviewer` 0 confirmed findings
