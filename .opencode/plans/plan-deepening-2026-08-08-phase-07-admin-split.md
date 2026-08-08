# Phase 07 — admin monolith split (Finding #7)

Blocking edges: phase 05 (remove circular import), phase 06 (awaiting done alongside). Heavily gated — do last.
Contract rule: #7. Gate: callback + keyboards + module boundary.
Wiring rows: `_handle_admin_callback` (admin.py:145-471, ~50 elif), `_handle_llm_callback` (771-869), `_handle_admin_text_input` (872-1072), config/keyboards.py admin:/llm: prefixes.

## Status: IN PROGRESS — sliced into 9 tasks (7.1–7.9), committed + reviewed per task.

Slice rationale (owner-approved 2026-08-08): split the 2744-line monolith into small,
independently-testable increments so a bug is isolated to one slice. Each task keeps
**callback strings and `from handlers.admin import ...` re-export names identical**.

## Task breakdown (each green + committed before next)

| Task | Scope | Risk | Blocking | Gate |
|---|---|---|---|---|
| 7.1 ✅ | Create `handlers/admin_stats.py` — empty module re-exporting only stats functions verbatim | none | — | module |
| 7.2 ✅ | Create `handlers/admin_plans.py` — re-export plan functions verbatim | none | 7.1 | module |
| 7.3 ✅ | Create `handlers/admin_cost.py` — re-export cost/pricing/llm funcs verbatim | none | 7.2 | module |
| 7.4 ✅ | Create `handlers/admin_ai.py` — re-export AI/preset/fallback/custom-test funcs verbatim | none | 7.3 | module |
| 7.5 ✅ | Migrate Batch A: `_handle_admin_callback` routes `stats:`→admin_stats, `plans:`→admin_plans, cost→admin_cost, AI→admin_ai | medium | 7.4 | callback + module |
| 7.6 ✅ | Migrate Batch B: `_handle_llm_callback` → admin_cost | medium | 7.5 | callback + module |
| 7.7 ✅ | Migrate `_handle_admin_text_input` awaiting handlers → submodules | medium | 7.6 | callback + module |
| 7.8 ✅ | **Contract**: `_handle_admin_callback` → thin prefix→sub-router dispatcher; delete moved defs from monolith | high | 7.7 (+ phase 06 alongside) | callback + keyboards + module |
| 7.9 ✅ | Rework `tests/test_wiring.py::_collect_admin_sub_actions` (:337-363) to scan ALL admin modules | medium | 7.8 | wiring |

## Scope — expand→migrate→contract
- **Expand**: create `handlers/admin_ai.py`, `handlers/admin_cost.py`, `handlers/admin_plans.py`, `handlers/admin_stats.py` as empty modules re-exporting the monolith's existing functions verbatim. No behavior change; all call sites still import from monolith.
- **Migrate** (per prefix batch, green after each):
  - Batch A: `admin:` sub-actions (plans → admin_plans; ai_preset/ai_fallback/ai_custom_test → admin_ai; cost_dashboard/llm_costs/pricing → admin_cost; stats → admin_stats).
  - Batch B: `llm:` callbacks → admin_cost.
- **Contract**: make `_handle_admin_callback` a thin prefix→sub-router dispatcher re-exporting sub-modules' entry points; remove monolith internal cruft once no caller remains.

## Required collateral (gated)
- Update AGENTS.md §3 responsibilities table + scan-target paths.
- Rework `tests/test_wiring.py::_collect_admin_sub_actions` (:337-363) to scan ALL admin modules, not only admin.py.
- Keep callback strings byte-identical (`test_all_callback_prefixes_are_routed`, `test_admin_sub_router_has_all_actions` green).
- Keep `from handlers.admin import ...` re-export names identical (bot.py:104, tests).

## Tests
- Wiring tests updated + green.
- Admin integration tests per domain.
- `test_callback_router.py`, `test_keyboards.py` green.

## Acceptance
- admin.py reduced to thin dispatcher; 4 domain modules exist with seams; callback strings unchanged; wiring guard validates per-module.

## Verify
`tests/test_wiring.py`, `tests/test_dead_code_guard.py`, admin integration tests, full suite + CI, then AGENTS.md §3 updated.

## Findings (logged during 7.7, NOT regressions of this split)
- **PRE-EXISTING**: `ai_fallback_rank:<preset>` is unreachable via `bot.py` text_router. The dispatch condition
  (~bot.py:394) only matches `admin_` / `llm_cost_` / `llm_price_` / `ai_preset_` / `ai_custom_test_`. Since
  `_handle_fallback_rank` (admin_ai.py) sets `awaiting = "ai_fallback_rank:..."`, a user typing a rank number falls
  through to the main menu and the rank is never changed. Out of scope for 7.7 (module split); needs owner decision
  (add `ai_fallback_rank` / a general `ai_` prefix to the text_router condition, or rename the awaiting key).
- Carried over verbatim (byte-identity contract): `count = len(chain)` dead local in `_handle_ai_text_input`.
  Leave as-is unless owner approves F841 cleanup.
