# Phase 06 — awaiting namespace concentration (Finding #6)

Blocking edges: phase 07 (admin split) — this is done **alongside** #7 per report; do after the admin submodules exist.
Contract rule: #6. Gate: callback + module boundary.
Wiring rows: `bot.py:403,456-484` awaiting prefix table; `_handle_admin_text_input` (admin.py:872).

## Status: IN PROGRESS — sliced into 4 tasks (6.1–6.4). Runs alongside phase 07 (mostly after 7.8).

Slice rationale (owner-approved 2026-08-08): same low-risk slicing as phase 07 — each task
independently testable, callback strings and re-export names unchanged.

## Task breakdown (each green + committed before next)

| Task | Scope | Risk | Blocking | Gate |
|---|---|---|---|---|
| 6.1 | `handlers/admin.py`: add `is_admin_awaiting()` + `resume_admin_wizard()` | medium | 7.8 (or alongside) | callback + module |
| 6.2 | `bot.py`: replace hard-coded prefix list at :394 with `is_admin_awaiting()` | low | 6.1 | callback |
| 6.3 | `bot.py`: move `flow:back` resume logic (:445-463) into `resume_admin_wizard()` | medium | 6.2 | callback |
| 6.4 | Update/extend `tests/test_admin_awaiting.py` + wiring test | medium | 6.3 | wiring |

## Scope
- `handlers/admin.py`: add `is_admin_awaiting(awaiting) -> bool` and `resume_admin_wizard(awaiting)`.
- `bot.py`: replace hard-coded prefix list at :403 with `is_admin_awaiting()`; move `flow:back` resume logic (:456-484) into `resume_admin_wizard()`.
- Owner gate at bot.py:254 unchanged (still rejects admin_/llm_ awaiting for non-owner).

## Tests
- `tests/test_admin_awaiting.py` updated/kept green (dispatch still works).
- Wiring test covers new admin text routes.

## Acceptance
- bot.py no longer hard-codes admin awaiting prefixes.
- `test_wiring.py` green.

## Verify
`tests/test_admin_awaiting.py`, `tests/test_wiring.py`, integration tests.
