---
name: srs-delete-card-fe-pronounce
description: Add 🗑 حذف کارت از جعبه مرور (remove-card) with confirm + session refill to revealed study cards, and fix the missing first-exposure pronounce button (issue #338 Phase 3 P3-T2, scoped)
created: 2026-08-19
base_commit: 6305c18
branch: feat/srs-delete-card
status: implemented
---
STATE: phase 5/5 — status: IMPLEMENTED (LOCKED) — all phases done; full suite green (3 pre-existing plan failures out of scope); reviewer findings #1-#3 fixed; awaiting commit/PR/merge

## Contract Lock (GATE STATUS = LOCKED, 2026-08-19)

Owner confirmed each rule independently. Locked decisions:

- **Rule 1 — Scope:** ship the FE pronounce fix + the delete-card feature (P3-T2) only. Defer P3-T1 (review telemetry), P3-T3/T4 (display-toggle UI) to a later PR.
- **Rule 2 — Delete button placement:** on the **revealed (back-stage)** card, for both review and first-exposure cards (owner overrode plan's front-stage). Delete is reachable *after* revealing.
- **Rule 3 — Confirm flow:** two-step confirm — tap delete → `بله حذف شود` / `انصراف` keyboard → only `بله` deletes; `انصراف` re-renders the card.
- **Rule 4 — Delete semantics:** physical `DELETE FROM saved_words` (`services/db/words.py::delete_saved_word(word_id, user_id)`), idempotent.
- **Rule 5 — After delete-yes:** toast + **refill the session** from tier 1/2 due cards (Rule 10) then advance; `انصراف` leaves the session untouched.
- **Rule 6 — Callbacks + routing:** new prefixes `srs:delete:`, `srs:delete:yes:`, `srs:delete:no:` registered in `services/routing.py` (R1); handlers `_handle_srs_delete` / `_handle_srs_delete_yes` / `_handle_srs_delete_no` in `handlers/srs_handler.py`.
- **Rule 7 — FE pronounce fix:** in the reveal handler, pass `show_pronounce=db.should_show_pronounce(user_id)` to `get_first_exposure_keyboard` (currently omitted at srs_handler.py:161) so FE revealed cards show 🔊 exactly like review cards.
- **Rule 8 — Seam handling:** Persistence seam is claimed by `refactor/db-concurrency`; owner chose **proceed-anyway + rebase before PR** (additive `delete_saved_word`, low collision risk).
- **Rule 9 — Tests:** wiring test (`tests/test_wiring.py`) for the 3 new prefixes; integration test (`tests/test_integration/`) covering delete from review + FE cards, confirm/yes/no, double-tap idempotency, and session refill; FE-pronounce-button assertion. DB snapshot-isolated, Telegram mocked.
- **Rule 10 — Session refill after delete:** delete triggers a refill from **tier 1/2 (due)** cards if any remain, so the session stays at `total_cards`; if the due queue is exhausted, the session ends normally. (Owner clarification, 2026-08-19.)

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | `srs:delete:`, `srs:delete:yes:`, `srs:delete:no:` | add |
| Router branches | `services/routing.py` (R1) register | add |
| Keyboard builders / constants | `config/keyboards.py`: `get_srs_delete_confirm_keyboard`, delete row on revealed review + FE keyboards | add |
| DB tables / columns / functions | `services/db/words.py::delete_saved_word` | add |
| Handler functions | `handlers/srs_handler.py`: `_handle_srs_delete`, `_handle_srs_delete_yes`, `_handle_srs_delete_no`; FE reveal `show_pronounce` | add/fix |
| Imports / re-exports | srs_handler → routing, words | update |
| Prompts / formatting helpers | none | keep |
| Tests referencing them | `tests/test_wiring.py`, `tests/test_integration/`, `tests/test_srs_staged_reveal.py` | add/update |
| Docs (ROADMAP, AGENTS.md §3 map, issues) | issue #338 Phase 3 | update on merge |

## Test Plan (Rule 9)

- `tests/test_wiring.py`: assert `srs:delete:`, `srs:delete:yes:`, `srs:delete:no:` registered in `services/routing.py` → handled in `handlers/srs_handler.py`; reverse-wiring guard passes.
- `tests/test_integration/test_srs_delete_card_flow.py`: delete button on revealed review + FE cards; confirm shows `بله حذف شود`/`انصراف`; `yes` deletes row + refills session + advances; `no` re-renders card; double-tap idempotent; FE card shows 🔊 pronounce button (Rule 7).
- DB snapshot isolation, Telegram mocked.

## Blocked Questions

- [2026-08-19] Phase 1 (Rule 10): After a delete, should the session refill to keep the original card count? Owner: "delete must trigger a refill from tier 1/2 cards if there are any (unless the queue is exhausted)." Decision: **refill to total_cards from remaining tier 1/2 due cards; end normally if queue exhausted.**