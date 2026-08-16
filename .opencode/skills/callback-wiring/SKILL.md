---
name: callback-wiring
description: Enforce callback routing integrity — all callback_data prefixes from all modules have matching handlers in callback_router and relevant sub-routers; wiring integrity test (tests/test_wiring.py) covers new/affected routes; reverse-wiring guard and dead-reference guard pass. Load when adding/changing callback prefixes, router dispatch, or keyboard construction.
license: MIT
compatibility: opencode
metadata:
  category: wiring
  gate: callback-change
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# Callback Wiring Integrity Skill

## When to load
- Adding/changing any `callback_data` prefix
- Modifying `callback_router` dispatch conditions
- Changing sub-router action patterns
- Adding/modifying keyboard builders in `config/keyboards.py`

## Callback Routing Map (AGENTS.md §3)

| Callback Prefix | Handler File | Key Functions |
|----------------|--------------|---------------|
| `lang:`, `goal:`, `level:` | `handlers/user.py` | `on_lang_selected`, `on_goal_selected`, `on_level_selected`, `on_lang_changed`, `on_goal_changed`, `on_level_changed` |
| `presentation:set:` | `bot.py` | `callback_router` (inline) |
| `daily:prepare:`, `daily:next:` | `bot.py` | `_handle_daily_prepare`, `_send_next_daily_card` |
| `review:prepare:`, `review:menu`, `review:page:`, `review:date:`, `review:next:`, `review:noop` | `bot.py` | `_handle_daily_prepare`, `_show_review_menu`, `_show_review_date`, `_send_card_from_store` |
| `query:add:` | `bot.py` | `_handle_query_add` (from `handlers/srs_handler.py`) |
| `query:dup:new:`, `query:dup:reuse:`, `query:dup:cancel` | `bot.py` | `_handle_query_dup_new`, `_handle_query_dup_reuse`, `_handle_query_dup_cancel` |
| `tts:pronounce:` | `bot.py` | `_handle_tts_pronounce` |
| `study:start`, `study:inactive` | `handlers/study_handler.py` | `handle_study_start`, `handle_study_inactive` (via `bot.py callback_router`) |
| `help:section:`, `help:back` | `handlers/help_command.py` | `send_help_panel` (command/text entry), `handle_help_callback` |
| `srs:prepare:`, `srs:reveal:`, `srs:` | `handlers/srs_handler.py` | `_handle_srs_prepare`, `_handle_srs_reveal`, `_handle_srs_review` |
| `admin:` (thin dispatcher, via `services/routing` registry) | `handlers/admin.py` | registered as a coarse `admin` route (`register_admin_routes()` in `handlers/admin.py`); `dispatch()` owner-gates then calls `_handle_admin_callback`, which delegates by prefix to domain sub-routers (sub-routes below) |
| `admin:stats`, `admin:stats:*` | `handlers/admin_stats.py` | `handle_admin_stats` |
| `admin:plans`, `admin:plans:*`, `admin:set_plan` | `handlers/admin_plans.py` | `handle_plan_callback` (incl. `admin:plans:view`, `:edit`, `:full_edit_back/skip/cancel/save`, `:set_active`) |
| `admin:cost_dashboard`, `admin:llm_costs`, `admin:llm_pricing` | `handlers/admin_cost.py` | `handle_cost_callback` |
| `admin:ai_*`, `admin:fallback*`, `admin:help:presets`, `admin:help:fallback_chain` | `handlers/admin_ai.py` | `handle_ai_callback` |
| `admin:back`, `admin:cancel`, `admin:phonetics*`, `admin:broadcast`, `admin:show_settings`, `admin:noop`, `admin:log_level*`, `admin:user_activity_log`, `admin:user_activity:toggle` | `handlers/admin.py` | handled inline in `_handle_admin_callback` |
| `llm:` (via `services/routing` registry) | `handlers/admin_cost.py` (re-exported via `handlers/admin.py`) | `_handle_llm_callback` — registered as a coarse `llm` route via `_route_llm` adapter (rebuilds `llm:<action>`); `dispatch()` runs it (not owner-gated, matching pre-existing behavior) |
| `flow:back` | `handlers/admin.py` | `handle_flow_back` (resume_admin_wizard) |
| `flow:cancel` | `bot.py` → `services/utils/helpers.py` | `callback_router` calls `_exit_awaiting_flow` (now in `services/utils/helpers.py`); `config/keyboards.py` only emits the `flow:back`/`flow:cancel` buttons |

## Wiring Integrity Requirements

### For any callback change:
1. **Prefix registration** — new prefix added to routing map above AND to relevant handler
2. **Router coverage** — `callback_router` (or sub-router) has a matching branch for the prefix
3. **Keyboard alignment** — `config/keyboards.py` builders emit the exact prefix string
4. **Test coverage** — `tests/test_wiring.py` updated to assert the new route exists in router and handler

### Verification guards (must pass):
- `tests/test_wiring.py` — reverse-wiring guard: every `callback_data` prefix in keyboards/handlers has a router match
- `tests/test_dead_code_guard.py` — dead-reference guard: no leftover references to removed symbols

## Dependency & Wiring Map (AGENTS.md §2.4.2)
When contract removes/changes feature, migrates, refactors, changes schema/callbacks, or changes module boundaries, the contract MUST include completed map:

```markdown
| Dependency type | Items affected | Disposition (update / remove / keep) |
|---|---|---|
| Callback prefixes | ... | ... |
| Router branches (callback_router / sub-routers) | ... | ... |
| Keyboard builders / constants | ... | ... |
| DB tables / columns / functions | ... | ... |
| Handler functions | ... | ... |
| Imports / re-exports | ... | ... |
| Prompts / formatting helpers | ... | ... |
| Tests referencing them | ... | ... |
| Docs (ROADMAP, AGENTS.md §3 map, issues) | ... | ...
```

### Post-implementation verification
Each row's disposition demonstrated by concrete evidence (grep output, test, PR diff). Row with no evidence = unverified = blocks PR review.

## Notes
- Callback strings are case-sensitive; must match exactly
- Sub-router dispatch uses string prefix matching (e.g., `data.startswith("review:")`)
- New prefixes follow existing naming conventions (lowercase, colon-separated)
- The `admin:` prefix is a **two-level dispatch**: `bot.py callback_router` routes `admin:`/`llm:` into `services/routing.dispatch()` (R1 registry), which owner-gates (admin only) and calls `handlers/admin.py::_handle_admin_callback`; that function delegates to domain sub-routers (`handle_admin_stats` / `handle_plan_callback` / `handle_cost_callback` / `handle_ai_callback`). When adding an `admin:` route, cover the sub-router branch; the coarse route is registered in `register_admin_routes()` and asserted in `tests/test_wiring.py` via `_collect_registry_prefixes`. The dispatch guarantees exactly one `query.answer` per callback (B1/R8).
- `flow:back` / `flow:cancel` are emitted only by `config/keyboards.py`; their handling lives in `handlers/admin.py` (`handle_flow_back`) and `bot.py callback_router` (`_exit_awaiting_flow` in `services/utils/helpers.py`), not in `config/keyboards.py`.