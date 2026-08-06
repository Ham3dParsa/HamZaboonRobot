---
name: callback-wiring
description: Enforce callback routing integrity — all callback_data prefixes from all modules have matching handlers in callback_router and relevant sub-routers; wiring integrity test (tests/test_wiring.py) covers new/affected routes; reverse-wiring guard and dead-reference guard pass. Load when adding/changing callback prefixes, router dispatch, or keyboard construction.
license: MIT
compatibility: opencode
metadata:
  category: wiring
  gate: callback-change
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
| `query:prepare:`, `query:add:` | `bot.py` | `_handle_query_prepare`, `_handle_query_add` |
| `tts:pronounce:` | `bot.py` | `_handle_tts_pronounce` |
| `study:start`, `study:inactive` | `handlers/study_handler.py` | `handle_study_start`, `handle_study_inactive` (via `bot.py callback_router`) |
| `srs:prepare:`, `srs:reveal:`, `srs:` | `handlers/srs_handler.py` | `_handle_srs_prepare`, `_handle_srs_reveal`, `_handle_srs_review` |
| `admin:` | `handlers/admin.py` | `_handle_admin_callback` (incl. plan-manager: `plans`, `plans:view`, `plans:edit`, `plans:full_edit_back`, `plans:full_edit_skip`, `plans:full_edit_cancel`, `plans:full_edit_save`, `plans:set_active`) |
| `llm:` | `handlers/admin.py` | `_handle_llm_callback` |
| `flow:` | `config/keyboards.py` | `_handle_admin_callback`, `_exit_awaiting_flow` |

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