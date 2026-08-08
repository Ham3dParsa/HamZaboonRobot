# Main Plan — Architecture Deepening Refactor (Locked 2026-08-08)

Source: `.opencode/plans/wiring-map-deepening-2026-08-08.md` (Dependency & Wiring Map)
Reports: `docs/audit/architecture_review_deepening_2026-08-08.html`, `docs/audit/architecture_review_admin_ai_2026-08-08.html`
Branch: `refactor/architecture-deepening` (to be created)

## Locked contract (owner: "locked")

| # | Finding | Decision | Gate |
|---|---|---|---|
| 1 | AI telemetry ×5 | `_call_tracked(...)` wrapper, configurable log target | fast-track |
| 2 | Dead `ai_custom_test_wizard_keyboard` | delete, keep inline path | keyboards |
| 3 | services/db kitchen sink | extract cost + preset, thin façade | module |
| 4 | Duplicate assembly + dormant registry | single `build_session_list`; delete registry | module |
| 5 | `bot.py↔admin.py` circular import | move `_apply_log_level` to shared; strengthen reverse guard | module |
| 6 | `awaiting` split across files | `is_admin_awaiting()`/`resume_admin_wizard()` in admin.py | callback+module |
| 7 | admin monolith 2745 lines | split into admin_ai/cost/plans/stats, thin dispatcher | callback+module |

## Sequencing strategy (Pocock expand→migrate→contract)

Lowest risk / highest locality first. Phase files:
- `plan-...-phase-01-telemetry.md` (#1)
- `plan-...-phase-02-session.md` (#4)
- `plan-...-phase-03-dead-keyboard.md` (#2)
- `plan-...-phase-04-db-split.md` (#3)
- `plan-...-phase-05-circular-import.md` (#5)
- `plan-...-phase-06-awaiting.md` (#6, alongside #7)
- `plan-...-phase-07-admin-split.md` (#7, do last)

## Validation per batch
`tests/test_wiring.py`, `tests/test_dead_code_guard.py`, `tests/test_session_engine.py` (phases 2), focused tests, then full suite. Commit per phase (Conventional Commits). Independent review via `hamzaboon-reviewer` before commit per §5.

## Status
- Phase 01: complete — `_call_tracked(log_target=...)` + 7 tests, committed 883371a, reviewer clean, 460 tests pass
- Phase 02: complete — single `build_session_list`; removed `ACTIVITY_REGISTRY`/`ActivityHandler`/`get_interaction_ui`/`build_session`; `__init__.py` `__all__` pruned; 4 `BANNED_SYMBOLS` added; reviewer clean, 454 tests pass
- Phase 03: complete — `ai_custom_test_wizard_keyboard` deleted + admin.py:40 import removed; `BANNED_SYMBOLS` added; wiring/dead-code/admin tests green
- Phase 04: complete — split cost analytics + preset registry + settings into own modules; `__init__.py` is thin façade; seam tests green; AGENTS.md §3 updated
- Phase 05: complete — `_apply_log_level` → `apply_log_level` in services/utils/helpers.py; no `from bot import` in handlers; wiring reverse guard added; reviewer clean
- Phase 06: in-progress — sliced into tasks 6.1–6.4 (awaiting concentration); runs alongside phase 07
- Phase 07: in-progress — sliced into tasks 7.1–7.9 (admin monolith split); 7.1 next
