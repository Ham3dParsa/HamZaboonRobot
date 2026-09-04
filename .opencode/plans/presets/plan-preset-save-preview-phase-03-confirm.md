---
name: plan-preset-save-preview-phase-03-confirm
phase: 3
gates: [R3, R5, R6]
blocking: [phase-01, phase-02]
status: complete
---
STATE: phase 3 — status: complete (2026-09-04, uncommitted) — confirm old+new gate done:
_confirm_save_preset rebuilt via build_confirm_message (numbered WIZARD_FIELDS tables,
🎯/⛓️ conditional notes, 3-button keyboard on existing routes); IBTN_SAVE_PRESET/
IBTN_DISCARD_ALL removed (+BANNED_SYMBOLS), IBTN_SAVE_CANCEL→❌, IBTN_BACK_TO_EDIT added.
Evidence: pytest 1717 passed + 324 subtests, compile_all OK, ruff F821/F811 clean,
git diff --check clean. Acceptance: numbered old→new vertical tables ✓, third button
returns to edit with drafts intact ✓, integration tests ✓. Reviewer gate outstanding
(hamzaban-reviewer not run — no subagent tool in this session).

## Scope

`handlers/admin_ai.py::_confirm_save_preset` (currently name-only):

- Build confirm via helper: `⚠️ تأیید ذخیره — «{name}»` + numbered per-field vertical old/new tables (WIZARD_FIELDS order) + dirty count + conditional notes (🎯 active-preset warning; priority/fallback note only when those fields dirty).
- Keyboard: `[✅ بله، ذخیره کن] [❌ لغو ذخیره]` + `[↩️ بازگشت به ویرایش]` (reuses existing edit route, no new handler/prefix).
- Empty-edits guard stays (`تغییری برای ذخیره وجود ندارد`).
- Route-delete: remove old name-only confirm text in same change.

## Tests

- Extend `tests/test_integration/test_ai_preset_handlers_ux.py`: confirm shows numbered old+new tables for staged fields; notes conditional (active vs inactive preset); empty → guard text.
- Full suite green.

## Acceptance

- [ ] confirm lists every staged field old → new, numbered, vertical (no wide table)
- [ ] third button returns to edit without losing drafts
- [ ] integration tests pass; full validation passes
- [ ] `hamzaban-reviewer`: 0 confirmed findings

## Contract note (T9/U4)

- `IBTN_SAVE_CANCEL` stem is ❌ (changed 🚫→❌ in T3); 🚫 remains canonical
  for standalone cancel buttons elsewhere.
