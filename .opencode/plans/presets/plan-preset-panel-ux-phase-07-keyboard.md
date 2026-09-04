---
name: plan-preset-panel-ux-phase-07-keyboard
phase: 7
gates: [U1, U2]
blocking: []
status: complete
---
STATE: phase 7 — status: complete — focus: 2-col keyboard + name icon

Evidence (2026-09-04, uncommitted in feat/preset-panel-ux):
- `config/keyboards/admin.py::ai_preset_edit_keyboard`: 10 U1 pairs
  ([base_url|model], [api_key] solo, [batch|concurrency], [rpm|timeout],
  [temperature|max_tokens], [max_tpm|max_daily_req],
  [input_cost|output_cost], [priority|in_fallback], [emergency|reasoning],
  [name|group_label]); detach solo conditional; full-edit solo;
  [save|discard]; [cancel|close]. `git diff` shows every `callback_data`
  f-string byte-identical (only row grouping changed) + new
  `test_callback_data_set_unchanged` asserts the 25-string set equal.
- `config/keyboards/constants.py`: IBTN_FIELD_NAME = "🆔 نام پریست";
  6 half-width renames (pre-T7 20–26 chars → ≤16): MAX_TPM "🔢 TPM",
  DAILY_REQ "📊 سقف روزانه", INPUT "💵 ورودی ($/1M)",
  OUTPUT "💵 خروجی ($/1M)", PRIORITY "🔢 اولویت فال‌بک",
  IN_FALLBACK "⛓️ عضو فال‌بک".
- Tests: `tests/test_ai_preset_edit_keyboard.py` rewritten for paired rows
  (11 new T7 tests); full suite `pytest tests/ -n 14`: 1776 passed,
  324 subtests passed; `test_wiring.py` green; `scripts/compile_all.py`
  clean; `ruff --select F821,F811` on touched files clean;
  `git diff --check` clean. NOT committed (per instruction).

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

- [x] 19 field buttons in specified pairs; actions paired; callback_data identical
- [ ] full suite green; `hamzaban-reviewer` 0 confirmed findings (suite green;
  reviewer not run — no Task/subagent tool in this session; due before commit per §6.3)
