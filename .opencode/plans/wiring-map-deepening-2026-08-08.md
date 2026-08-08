# Dependency & Wiring Map — Architecture Deepening Refactor

Date: 2026-08-08 · Branch: `main` (no code changed — this is a read-only artifact)
Companion: `docs/audit/architecture_review_deepening_2026-08-08.html` + `docs/audit/architecture_review_admin_ai_2026-08-08.html`
Purpose: ground the §2.4.2 Dependency & Wiring Map in **actual call sites** (grep-verified), the prerequisite for locking the contract.

## Routing entry points (grep-verified)

| Entry | Location | Dispatches on |
|---|---|---|
| `callback_router` `admin:` | bot.py:601 | → `_handle_admin_callback(action)` (admin.py:145, ~50 elif) |
| `callback_router` `llm:` | bot.py:571 | → `_handle_llm_callback(data)` (admin.py:771) |
| `text_router` awaiting → admin | bot.py:403-404 | prefixes `admin_`/`llm_cost_`/`llm_price_`/`ai_preset_`/`ai_custom_test_` → `_handle_admin_text_input` (admin.py:872) |
| Owner gate on awaiting | bot.py:254 | `admin_`/`llm_cost_`/`llm_price_` + `not is_owner` → reject |
| `flow:back` wizard resume | bot.py:456-484 | special-cases `ai_preset_edit:` / `ai_preset_full_edit:` / `admin_plan_full_edit:` |

## Import edges that will change (module boundaries)

| Edge | Current | Target | Finding |
|---|---|---|---|
| `handlers/admin.py:462` | `from bot import _apply_log_level` | `from config.<helper> import _apply_log_level` | #5 |
| `bot.py:104` | `from handlers.admin import (...)` (top-level) | keep, but sources now re-exported by thin dispatcher | #7 |
| `config/keyboards.py:40` (admin.py:40) | `ai_custom_test_wizard_keyboard` (dead) | delete | #2 |
| `services/session/__init__.py` | exports `ACTIVITY_REGISTRY`, `ActivityHandler`, `build_session` | prune to `build_session_list`, `GRADE_POLICIES`, `resolve_grade`, `SessionNode` | #4 |
| `services/db/__init__.py` | 919-line mixed façade | thin re-export; cost + preset → own modules | #3 |
| `services/ai/ai.py` | outcome ternary ×5 (143,517,602,646,756) | `_call_tracked(...)` wrapper | #1 |

## Keyboard → router surface (must stay byte-identical)

`config/keyboards.py` emits many `admin:` (plans/ai_preset/ai_fallback/ai_custom_test/llm_costs/phonetics/stats/log_level...) and `llm:` (range/set/kind/status/pricing...) prefixes. **These strings must not change** — `test_all_callback_prefixes_are_routed` + `test_admin_sub_router_has_all_actions` (test_wiring.py:393,413) assert every emitted prefix has a matching branch.

## Guard tests that bind the refactor

| Guard | File:line | Binds |
|---|---|---|
| admin sub-actions resolve | test_wiring.py:413 (uses `_collect_admin_sub_actions` :337, scans **only** admin.py) | #7 — must be reworked to scan all 4 admin submodules |
| all prefixes routed | test_wiring.py:393 | #7 (must stay green) |
| reverse resolve (imports resolve to symbols) | test_wiring.py:225 (`_resolve_import`), :494 | #4,#5 — **currently treats `bot` as external/trusted**; extend to flag handler→bot |
| dead-reference guard | tests/test_dead_code_guard.py | #2,#3,#4 — removed symbols (dead keyboard, dormant registry, `build_session`) must have zero refs |
| session engine | tests/test_session_engine.py:91-108,276-291 | #4 — exercises `ACTIVITY_REGISTRY`/`get_interaction_ui`/`build_session`; must be updated/split |
| admin awaiting | tests/test_admin_awaiting.py | #6 — asserts awaiting dispatch from bot.py |
| callback router | tests/test_callback_router.py | #7 |
| keyboards | tests/test_keyboards.py:154-159 | #2,#7 |

## Callers that must keep importing identical names

- `from services import db` — used by handlers/bot/services (test_db_guard.py, test_custom_word_query.py, scheduling.py, etc.) — re-export names must stay.
- `from handlers.admin import ...` — bot.py:104 + tests (test_admin_awaiting.py:32,64,150,164).
- `from services.session import SessionNode, build_session_list, ...` — study_handler.py:29,178.

## Disposition per symbol (binds findings)

| Symbol | Disposition |
|---|---|
| `ai_custom_test_wizard_keyboard` (keyboards.py:806) | **remove** (#2) |
| `from bot import _apply_log_level` (admin.py:462) | **update** → shared helper (#5) |
| `ACTIVITY_REGISTRY`/`get_interaction_ui`/`ActivityHandler` (grade_policy.py) | **remove** (#4) |
| `build_session` (assembly.py:26) | **remove** (keep `build_session_list`) (#4) |
| cost + preset blocks in services/db/__init__.py | **update** → new modules, same re-export names (#3) |
| `_handle_admin_callback` (admin.py:145) + `_handle_llm_callback` (771) + `_handle_admin_text_input` (872) | **split** into admin_ai/cost/plans/stats, thin prefix dispatcher (#7) |
| awaiting prefix table in bot.py:403,456-484 | **update** → `is_admin_awaiting()`/`resume_admin_wizard()` in admin.py (#6) |
| AI outcome ternary in ai.py | **update** → `_call_tracked(...)` (#1) |

## Verify-after (reverse-wiring + dead-reference)

After implementation: `tests/test_wiring.py`, `tests/test_dead_code_guard.py`, repo suite + CI must pass per batch; grep each removed symbol for zero refs; `test_wiring.py::_collect_admin_sub_actions` updated to scan all admin modules.

## Contract status

**GATE STATUS: LOCKED** — owner: "locked" (2026-08-08). All 7 findings approved with recommended options. Next: branch `refactor/architecture-deepening`, per-phase tickets (expand→migrate→contract), TDD one ticket at a time, run guards (`test_wiring.py`, `test_dead_code_guard.py`, repo suite + CI) between batches.

### Phase status (2026-08-08)
- #1 (ai outcome) **done** — `_call_tracked`; committed 883371a.
- #4 (session + registry) **done** — `build_session`/`ACTIVITY_REGISTRY`/`get_interaction_ui`/`ActivityHandler` removed; `__init__.py` pruned; 4 `BANNED_SYMBOLS`; guards green.
- #2 (dead wizard keyboard) **done** — `ai_custom_test_wizard_keyboard` + admin.py:40 import removed; `BANNED_SYMBOLS`; guards green.
- #3 (db split) **done** — cost analytics → `cost_tracking.py`, presets/fallback → `preset_registry.py`, settings → `settings.py`; `__init__.py` is a thin façade; `test_db_facade_split.py` seam tests; full suite green.
- Remaining: #5 circular import, #6 awaiting, #7 admin split.
