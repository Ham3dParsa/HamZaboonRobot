---
name: srs-delete-card-fe-pronounce-phase-04-handlers
description: Phase 4 — delete handlers + session refill + FE pronounce fix (Rules 5, 7, 10)
created: 2026-08-19
base_commit: 6305c18
branch: feat/srs-delete-card
status: in-progress
---
STATE: phase — status: DONE (merged via PR #406) — was: implement _handle_srs_delete(_yes/_no) + refill + FE pronounce

## Blocking edges
- Phase 1 (DB `delete_saved_word`), Phase 2 (keyboards + confirm), Phase 3 (routing).

## Scope
- `handlers/srs_handler.py`:
  - `_handle_srs_delete(update, context, target_user_id, word_id)` — ownership guard → render confirm keyboard (`get_srs_delete_confirm_keyboard`) on the active message.
  - `_handle_srs_delete_yes(...)` — ownership guard → `db.delete_saved_word(word_id, user_id)` → toast → **refill session from tier 1/2 due cards** (Rule 10) then `advance_session`.
  - `_handle_srs_delete_no(...)` — re-render the revealed card (grade keyboard) on the same message; session untouched.
  - **FE pronounce fix (Rule 7):** in `_handle_srs_reveal`, pass `show_pronounce=db.should_show_pronounce(user_id)` to `get_first_exposure_keyboard`.
- Session refill (Rule 10): after delete, if `len(state.nodes) < state.total_cards`, pull the next tier 1/2 due card (via the existing session assembly / due-queue query) and append; if the due queue is exhausted, leave it (session ends normally on advance).

## Tests
- `tests/test_integration/test_srs_delete_card_flow.py` (isolated DB, mocked Telegram): delete button on revealed review + FE cards; confirm yes deletes row + refills session + advances; no re-renders card; double-tap idempotent; refill keeps `total_cards` when due cards remain and ends when queue is exhausted; FE card shows 🔊.

## Gates
- Satisfies Rules 5, 7, 10.

## Wiring rows
| Dependency type | Items affected | Disposition |
|---|---|---|
| Handler functions | `handlers/srs_handler.py`: `_handle_srs_delete`, `_handle_srs_delete_yes`, `_handle_srs_delete_no`; FE reveal `show_pronounce` | add/fix |
| Imports / re-exports | srs_handler imports `delete_saved_word`, confirm keyboard, refill helpers | update |

## Acceptance criteria
- Delete-from-revealed-card works end-to-end; yes deletes + refills + advances; no cancels; FE pronounce button present.