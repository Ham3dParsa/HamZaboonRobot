# Seam Registry (SEAMS.md)

Canonical list of seams that parallel branches/worktrees can silently collide
on without touching the same file. Cross-reference these exact names from
parallel-work-guard's SKILL.md. Do not invent ad-hoc seam names.

This is disclosed reference — loaded only when parallel-work-guard fires.

## Domain Seams

| # | Domain Area | Path | Interface Exposed |
|---|---|---|---|
| 1 | Persistence | services/db/__init__.py + services/db/schema.py | get_conn() |
| 2 | AI/LLM Provider | services/ai/ai.py | _client(), ask_json(), ask_card(), ask_batch() |
| 3 | Session Assembly | services/session/__init__.py + assembly.py + summary.py | build_session_list(), generate_tier3_node(), build_report() |
| 4 | SRS Algorithm | services/fsrs_core.py | compute_retrievability(), compute_interval(), initial_stability(), update_stability() |
| 5 | Telegram UI -> Study | handlers/study_handler.py | handle_study_start(), advance_session() |
| 6 | Telegram UI -> SRS Grading | handlers/srs_handler.py | _handle_srs_review(), _handle_first_exposure_grade() |
| 7 | Telegram UI -> User Domain | handlers/user.py | cmd_start, ask_for_ask_word, send_grammar_tip, on_lang_selected |
| 16 | Telegram UI -> Help | handlers/help_command.py | send_help_panel(), handle_help_callback() |
| 8 | Telegram UI -> Admin | handlers/admin.py | open_admin_panel, _handle_admin_callback, _register_admin_flows() |
| 9 | Telegram UI -> Stats | handlers/admin_stats.py | handle_admin_stats |
| 10 | Telegram UI -> Plans | handlers/admin_plans.py | handle_plan_callback, _start_plan_wizard, _show_plan_list |
| 11 | Telegram UI -> Cost | handlers/admin_cost.py | handle_cost_callback, _show_llm_cost_dashboard |
| 12 | Telegram UI -> AI Config | handlers/admin_ai.py | handle_ai_callback, _show_ai_presets, _show_ai_settings |
| 13 | TTS Provider | services/tts.py | async pronounce(word, lang) |
| 14 | Scheduling/Quota | services/scheduling.py | daily_session_budget(), consume_session_slot(), release_session_slot() |
| 15 | Telegram Callback Notifications | services/utils/callback_notifications.py | notify_callback(query, text, intent=...) |
| 16 | Custom-word input validation | services/utils/validation.py | validate_word_query(text, language) |
| 17 | Custom-word query orchestration | services/word_query.py (core) + bot.py `_process_ask_word` / `_handle_query_dup_new` / `_handle_query_dup_reuse` / `_handle_query_dup_cancel` + handlers/srs_handler.py `_handle_query_add` + config/keyboards.py `query_result_keyboard` + `query_duplicate_keyboard` | ask(), toggle_save(), find_duplicate(); callback `query:add:`, `query:dup:new:`, `query:dup:reuse:`, `query:dup:cancel` (the old `query:prepare:`/prepare() path was removed in #340 R3) |
| 18 | Display-toggle store | services/db/display_toggles.py | DisplayToggleService.get_effective(), set_user_toggle(), set_forced(), get_global_defaults(), set_global_defaults(); settings key `display_toggle_defaults` (J0.2 registry-backed). users.py/settings.py are thin delegates. |
| 19 | Awaiting Text-Input Flow Registry | handlers/flows.py | register_flow(), resolve_flow(), text_router(), is_admin_awaiting() |

## Shared Resource Registries (non-seam collision surfaces)

These are flat namespaces — table/column names, callback prefixes, and catalog
identifiers — where two branches can collide silently
even though they edit different files.

### DB tables / columns

users, saved_words, settings, daily_cards, daily_progress,
daily_card_sessions, query_results, grammar_tips, llm_requests, review_events,
ai_presets, preset_hourly_usage, preset_groups, config_tests, plans,
study_sessions, session_grade_ledger
(source: services/db/schema.py)

### Settings keys (deferred)

Settings keys are not claimable in this version. They remain a known collision
surface because the flat key-value store has no central registry and keys are
scattered across services/db/settings.py, services/db/preset_registry.py,
services/ai/ai.py, services/ai/llm_services.py, services/ai/preset_fields.py, handlers/admin.py,
handlers/study_handler.py, bot.py, and services/scheduling.py. The dynamic
pattern sessions_used_{session_slug} also requires a canonical inventory or
namespace policy before settings claims can provide precise resource names.
Track the settings inventory as a separate follow-up issue.

### Callback prefixes

Defined inline across config/keyboards.py (~95 prefix string literals) and
dispatched in bot.py's callback_router.

### Catalog identifiers

config/catalog.py — LANGUAGES, GOALS, LEVELS keys.

## Maintenance

Update this file whenever AGENTS.md §3's module change guard fires
(new/renamed/split/removed module), same trigger as tests/test_wiring.py's
scan-target update requirement.

Copyright (c) Ham3dParsa. All rights reserved.
