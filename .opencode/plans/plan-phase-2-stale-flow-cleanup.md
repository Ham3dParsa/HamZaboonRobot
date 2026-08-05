---
name: phase-2-stale-flow-cleanup
description: Remove stale card systems (daily flow, review menu, dead SRS handlers) and drop daily DB tables after the Phase 3a migration
created: 2026-08-05
base_commit: 628b9e48c104528c2b971f59ff11865095b93977
branch: (to be created) feat/phase-2-stale-flow-cleanup
status: in-progress
---

# Phase 2 — Remove Stale Card Systems + Drop Daily Tables

Traces to `docs/plans/plan_fsrs_session_cleanup.md` (Phase 2) and follows the
Phase 3a migration (merged as PR #252, commit `628b9e4`). The migration has
been validated as run against `hamzaban.db` (`settings.fsrs_migration_done='1'`,
531 saved_words reset to first-exposure, daily tables intact).

Because the migration has completed, `migrate_saved_words_to_fsrs()` is now
**provably dead code** (returns `False` at `words.py:323` forever).

## Split into two PRs (Rule 2 = B)

- **Phase 2a** — Remove stale flows + fold in the session-completion bug fix (ONE PR).
- **Phase 2b** — Drop the daily tables + remove the now-dead migration + update guards (follow-up PR).

Per-phase detail lives in:
- `.opencode/plans/plan-phase-2a-stale-flow-cleanup.md`
- `.opencode/plans/plan-phase-2b-drop-daily-tables.md`

## Locked Contract Rules (owner-approved 2026-08-05)

| Rule | Decision | GATE |
|------|----------|------|
| 1 | Remove all three stale systems at once (daily flow + review menu + dead SRS) in a single PR | LOCKED |
| 2 | Split: Phase 2a removes flows (keep tables + migration); Phase 2b drops tables + migration (two PRs) | LOCKED |
| 3 | Drop `daily_cards`, `daily_progress`, `daily_card_sessions` + update guards (applies to 2b) | LOCKED |
| 4 | Rewrite `SchemaMigrationTest` so it does not depend on daily tables (in 2b) | LOCKED |
| 5 | Keep `send_grammar_tip` + `grammar_tip_system_prompt` (do NOT remove) | LOCKED |
| 6 | Remove only dead SRS; keep live 4-grade flow (`_handle_srs_review`, `srs:fe:`, `_handle_query_add`, `study:start`) | LOCKED |
| Bug | Fold session-completion crash fix (empty `tier3_context` TypeError + inaccurate `/study` message) into Phase 2a | LOCKED |

## Keep items (do NOT remove)

- `_handle_srs_review` (4-grade) — `handlers/srs_handler.py:69`
- `srs:fe:` → `_handle_first_exposure_grade` — `handlers/srs_handler.py:123`
- `_handle_query_add` — `handlers/srs_handler.py:47`
- `study:start` → `handle_study_start` — `handlers/study_handler.py:82`
- `get_review_keyboard` / `get_first_exposure_keyboard` — `config/keyboards.py:410-497`
- `study_start_keyboard` — `config/keyboards.py:201-205`
- `services/scheduling.py` (study-session quota — distinct from daily flow)
- `daily_batch_system_prompt` (admin custom-test wizard still uses it)
- `send_grammar_tip` + `grammar_tip_system_prompt` (Rule 5 = B)
- `record_review_event` (NOT v2 — `record_review_event_v2` does not exist)

## Main Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | `daily:prepare:`, `daily:next:`, `daily:prev:`, `review:prepare:`, `review:menu`, `review:page:`, `review:date:`, `review:next:`, `review:noop`, `srs:prepare:`, `srs:reveal:` | remove (2a) |
| Callback prefixes (keep) | `srs:fe:`, `srs:` (4-grade), `query:add:`, `study:start`, `query:prepare:`, `tts:`, `admin:`, `llm:`, `lang:`/`goal:`/`level:` | keep |
| Router branches | `callback_router` daily/review/srs-prepare/srs-reveal branches (`bot.py:946-1091,1118-1129`) | remove (2a) |
| Keyboard builders | `daily_card_keyboard`, `daily_review_menu_keyboard`, `daily_review_dates_keyboard`, `srs_hidden_keyboard`, `srs_revealed_keyboard`, `srs_review_keyboard` | remove (2a) |
| Keyboard builders (keep) | `get_review_keyboard`, `get_first_exposure_keyboard`, `study_start_keyboard` | keep |
| DB tables | `daily_cards`, `daily_progress`, `daily_card_sessions` | drop (2b) |
| DB functions (daily tables) | `get_daily_cards`, `get_recent_daily_words`, `get_recent_daily_card_dates`, `count_daily_cards`, `add_daily_card`, `update_daily_card_fields`, `get_daily_progress`, `set_daily_progress`, `get_daily_card_session`, `ensure_daily_card_session` | remove (2b) |
| DB function | `migrate_saved_words_to_fsrs()` (`words.py:312`) | keep in 2a (tables still read); remove/simplify in 2b |
| DB functions (keep) | `get_saved_word`, `update_saved_word_fields`, `record_review_event`, `grade_word_review` (stub), `grade_first_exposure` (stub) | keep |
| Handler functions | `_handle_daily_prepare`, `_show_review_menu`, `_review_history_page`, `_handle_srs_reveal`, `_handle_srs_prepare`, `start_srs_review` | remove (2a) |
| Imports / re-exports | bot.py dead imports (`srs_*`, `daily_review_*`, `_saved_word_card`); `services/db/__init__.py` exports | update (2a) |
| Prompts / formatting | **keep** `daily_batch_system_prompt`; keep `grammar_tip_system_prompt`; one corrected message string via `escape_mdv2` | update |
| Session handler | `advance_session` (`study_handler.py:239`) — Tier-3 guard + message fix | update (2a) |
| Tests | `test_wiring.py`, `test_dead_code_guard.py`, `test_migration_guards.py`, `test_custom_word_query.py`, `test_keyboards.py`, `test_reliability.py`, `test_integration/test_srs_callback_routing.py`, `test_integration/test_ai_timeout_flow.py` | update |
| Docs | AGENTS.md §3 callback map, ROADMAP.md, `project_status.json` + regenerate dashboard, issue #245 | update |

**AI cost:** none — no new AI calls (removal + one message string only).
**Formatting:** only the corrected fallback message; pass through `escape_mdv2`.

## Update Log
- 2026-08-05: Contract locked (7 rules: Rules 1–6 + session-completion bug). Migration validated complete against `hamzaban.db`. Plan persisted.
- 2026-08-05: Phase 2a detail persisted (next).
