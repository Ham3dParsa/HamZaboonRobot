---
name: srs-delete-card-fe-pronounce-phase-02-keyboards
description: Phase 2 — delete button on revealed cards + confirm keyboard (Rules 2, 3)
created: 2026-08-19
base_commit: 6305c18
branch: feat/srs-delete-card
status: in-progress
---
STATE: phase 2/5 — status: in-progress — focus: add delete row + confirm keyboard in config/keyboards.py

## Blocking edges
- Phase 1 (DB) not required for keyboard-only code, but the confirm keyboard emits `srs:delete:yes:`/`srs:delete:no:` prefixes; keyboard builders must match the prefixes Phase 3 registers.

## Scope
- `config/keyboards.py`:
  - Add `get_srs_delete_confirm_keyboard(user_id, word_id)` — rows: `✅ بله حذف شود` → `srs:delete:yes:{user_id}:{word_id}`, `❌ انصراف` → `srs:delete:no:{user_id}:{word_id}`.
  - Add a `🗑 حذف کارت از جعبه مرور` row (→ `srs:delete:{user_id}:{word_id}`) to the **revealed (back-stage)** keyboards: `get_review_keyboard` and `get_first_exposure_keyboard` (Rule 2 — revealed stage, owner override).
- New button-label constants alongside existing `IBTN_*` constants.

## Tests
- `tests/test_srs_staged_reveal.py`: assert the revealed review + FE keyboards contain the `srs:delete:` prefix; confirm keyboard emits `srs:delete:yes:`/`srs:delete:no:`.

## Gates
- Satisfies Rule 2 (revealed-stage placement) and Rule 3 (confirm flow).

## Wiring rows
| Dependency type | Items affected | Disposition |
|---|---|---|
| Keyboard builders / constants | `config/keyboards.py`: `get_srs_delete_confirm_keyboard`, delete row on revealed review + FE keyboards, `IBTN_*` constants | add |

## Acceptance criteria
- Revealed review and FE keyboards each expose a `🗑 حذف کارت از جعبه مرور` button; the confirm keyboard shows بله/انصراف with the right prefixes.