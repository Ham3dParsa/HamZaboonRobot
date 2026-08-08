# Phase 06 — awaiting namespace concentration (Finding #6)

Blocking edges: phase 07 (admin split) — this is done **alongside** #7 per report; do after the admin submodules exist.
Contract rule: #6. Gate: callback + module boundary.
Wiring rows: `bot.py:403,456-484` awaiting prefix table; `_handle_admin_text_input` (admin.py:872).

## Status: COMPLETE — all 4 tasks (6.1–6.4) committed and independently reviewed clean.

Slice rationale (owner-approved 2026-08-08): same low-risk slicing as phase 07 — each task
independently testable, callback strings and re-export names unchanged.

## Task breakdown (each green + committed before next)

| Task | Scope | Risk | Blocking | Gate |
|---|---|---|---|---|
| 6.1 ✅ | `handlers/admin.py`: add `is_admin_awaiting()` + `resume_admin_wizard()` | medium | 7.8 (or alongside) | callback + module |
| 6.2 ✅ | `bot.py`: replace hard-coded prefix list at :394 with `is_admin_awaiting()` | low | 6.1 | callback |
| 6.3 ✅ | `bot.py`: move `flow:back` resume logic into `resume_admin_wizard()` | medium | 6.2 | callback |
| 6.4 ✅ | Update/extend `tests/test_admin_awaiting.py` + wiring test | medium | 6.3 | wiring |

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

## Dependency & Wiring Map (Finding #6)

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | `flow:back` (callback_router dispatch body) | kept; body moved into `resume_admin_wizard()` (admin.py), branch label unchanged |
| Router branches | `callback_router` `flow:back` block (was inline) → `resume_admin_wizard` call | moved; `if data == "flow:back":` branch itself unchanged |
| Keyboard builders / constants | none changed | keep |
| DB tables / columns / functions | none | keep |
| Handler functions | NEW `is_admin_awaiting()`, NEW `resume_admin_wizard()` in `handlers/admin.py` | added |
| Imports / re-exports | `bot.py` gains `is_admin_awaiting`, `resume_admin_wizard` from `handlers.admin`; drops `_edit_ai_preset` (now unused in bot.py) | updated; `handlers.admin._edit_ai_preset` still exported + used by `resume_admin_wizard` |
| Awaiting keys covered | `admin_*`, `ai_preset_*`, `ai_custom_test_*`, `ai_fallback_rank:*`, `llm_cost_*`, `llm_price_*` | now centralized in `_ADMIN_AWAITING_PREFIXES`; **fixes the `ai_fallback_rank:` routing gap** |
| Tests referencing them | `tests/test_admin_awaiting.py`, `tests/test_wiring.py` | extended (is_admin_awaiting unit tests, flow:back wiring test, awaiting-key coverage guard) |
| Docs (ROADMAP, AGENTS.md §3 map, issues) | none needed (no module boundary change) | keep |

## Verify
`tests/test_admin_awaiting.py`, `tests/test_wiring.py`, integration tests.
