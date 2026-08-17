---
name: plan-send-pretty-followups-t8-admin-ai
description: T8 — migrate handlers/admin_ai.py (~30 HTML screens, seam 12) to send_pretty spans, split into sub-tickets
created: 2026-08-17
base_commit: 537b6fd
branch: refactor/admin-ai-spans
status: in-progress
---

STATE: phase 6/N — status: in-progress — focus: T8e DONE, next T8f (fallback chain); Newline/HTML fix 694b3ae; group-manager gluing fix owner-approved

## Contract lock (owner 2026-08-17, GATE LOCKED)
- R1: T8 split into sub-tickets T8a..T8h (each a commit/PR, like R3).
- R2: Admin AI screens render as **HTML** via spans (Backend.HTML). send_pretty owns parsing; admin code writes only spans.
- R3: Converted screens call `say(update, context, Message(...), backend=Backend.HTML)` directly.
- R4: Persist T6/T7/T8 follow-up plan + TICKETS rows here in the isolated worktree branch (primary main TICKETS.md is dirty/owned by another session).
- R5: Add `backend: Backend = Backend.MDV2` parameter to `say()` and `send()`. Default MDV2 preserves all existing learner call sites. Admin passes `backend=Backend.HTML`.

## Ticket map (each = one commit; sub-tickets = one PR)
- **T8-PRE** — Add `backend=` param to `say()`/`send()` (default MDV2) + focused tests. Unblocks all admin HTML spans.
- **T8a** — Settings/overview screen: `_show_ai_settings`, `_show_ai_presets` header, fallback status → spans.
- **T8b** — Presets list/view: `_show_linear_presets`, `_show_grouped_presets`, `_show_ai_preset_view`.
- **T8c** — Edit wizard: `_edit_ai_preset`, `_edit_ai_preset_field`, `_handle_ai_preset_field_input`, `_start_full_edit_wizard`, `_show_wizard_field`, `_handle_full_edit_input`/`_next`/`_skip`/`_back`/`_cancel`/`_summary`/`_save`.
- **T8d** — Create wizard: `_add_ai_preset`, `_handle_ai_preset_new_name`, `_show_create_priority`/`_status`, `_finish_create`, `_handle_create_test`/`_toggle_enable`/`_priority_choice`/`_priority_manual`/`_status_choice`.
- **T8e** — Group manager: `_toggle_preset_view_mode`, `_handle_group_view`/`_batch_key`/`_set_label`, `_show_group_manager`, `_handle_group_manager_rename`/`_clear`.
- **T8f** — Fallback chain: `_show_ai_fallback`, `_handle_ai_fallback`, `_show_fallback_preset_picker`, `_show_fallback_chain`, `_show_fallback_usage_details`.
- **T8g** — Custom test: `_test_ai_connection`, `_start_custom_test_wizard`, `_custom_test_step_lang`/`_goal`/`_level`/`_target`/`_preset`, `_run_custom_test`, `_handle_custom_test_wizard`.
- **T8h** — Help screens: `_show_help_presets`, `_show_help_fallback_chain`.
- **T8-last** — Activation/save/delete/dup/discard/detach: `_activate_ai_preset`, `_confirm_save_preset`, `_discard_all_preset_changes`, `_detach_ai_preset_group`, `_save_ai_preset`, `_delete_ai_preset`, `_confirm_delete_yes`/`_no`, `_duplicate_ai_preset`.

## Deferred (owner 2026-08-17) — separate follow-up PRs
- T6 — `format_card` / `format_srs_*` → Message factories (services/utils/formatting.py). DEFERRED.
- T7 — 13 direct bypass sites (study/srs/admin/admin_plans) → send()/say(). DEFERRED.

## Progress
- T8-PRE DONE — added `backend=Backend.MDV2` param to `say()`/`send()` + `_resolve_content`; 4 new tests (say HTML, say edit HTML, send HTML, default MDV2). Full suite 1134 passed, compile/ruff/dashboard/diff-check clean. (committed 1b332fd)
- T8a DONE — `_show_ai_settings` + no-active notice → spans (Message + Backend.HTML), byte-exact HTML preserved (bold labels, emoji 🤖/⚠️/📇, "Fallback:" prefix, trailing-space after `:</b>`). New integration test `test_ai_settings_with_active_preset_renders_html_bold` (escapes `<x>`). Full suite 1135 passed. (committed e378857)
- T8b DONE — `_show_linear_presets` / `_show_grouped_presets` / `_show_ai_preset_view` → spans; byte-exact verified (multipage MATCH, single-page only trailing-newline diff = invisible). Kilo SUGGESTION addressed in 8cb1170: extracted shared `_preset_brief_spans` (single source of truth) used by linear list; `_render_preset_brief` builds HTML from same spans (byte-identical verified). Full suite 1136 passed. (committed 5c9e4d9 + 8cb1170)
- T8c DONE — `_edit_ai_preset` / `_edit_ai_preset_field` / `_handle_ai_preset_field_input` (success msg) / `_show_wizard_field` / `_show_wizard_summary` → spans (added `code`, `italic` imports). Byte-exact verified (wizard draft/current/help/group, summary). Fixed ZWNJ regression in draft label (`پیش‌نویس`→`پیشنویس`). New integration test `test_field_edit_prompt_escapes_current_in_code`. Full suite 1137 passed. (uncommitted)
- T8d DONE — `_add_ai_preset` / `_show_create_priority` / `_show_create_status` / `_finish_create` / `_handle_create_test` / `_handle_create_priority_choice` (manual) → spans. Byte-exact verified (add/priority/status/finish/test_success/test_fail/test_fresh/manual). Deleted now-dead `CREATE_PRIORITY_PROMPT`. New integration test `test_create_finish_escapes_name_in_code`. Full suite 1138 passed. (uncommitted)
- T8e DONE — `_handle_group_view` / `_show_group_manager` / `_handle_group_manager_rename` → spans. Byte-exact verified (group_view after adding blank line; rename MATCH). Owner-approved behavior fix: `_show_group_manager` now puts each group on its own line (was glued by `"".join`). New integration test `test_group_manager_puts_each_group_on_own_line`. Full suite 1140 passed. (uncommitted)
- T8f PENDING
- T8g PENDING
- T8h PENDING
- T8-last PENDING

## Notes / evidence
- admin_ai.py measured: 1,893 lines, ~60 async functions, ~30 HTML screens, ~119 formatting/_edit_or_send sites, uses html_escape + parse_mode=HTML.
- send_pretty render() already supports Backend.HTML; say()/send() hardcode Backend.MDV2 today → T8-PRE adds the backend param.

## Blocked Questions
- (none)