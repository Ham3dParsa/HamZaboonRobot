---
name: phase-2a-stale-flow-cleanup
description: Remove stale card systems (daily flow, review menu, dead SRS handlers) and fold in the session-completion crash fix
created: 2026-08-05
base_commit: 628b9e48c104528c2b971f59ff11865095b93977
branch: (to be created) feat/phase-2-stale-flow-cleanup
status: in-progress
---

# Phase 2a — Remove Stale Card Systems + Session-Completion Fix (ONE PR)

This is the first PR of Phase 2 (Rule 2 = B). It removes the three stale card
systems while **keeping** the daily tables and `migrate_saved_words_to_fsrs()`
intact (they are removed in Phase 2b). It also folds in the session-completion
crash fix (owner Rule "Bug" = A).

## Locked Contract Rules in scope

| Rule | Decision |
|------|----------|
| 1 | Remove all three stale systems at once |
| 2 (partial) | Keep daily tables + migration intact in this PR |
| 5 | Keep grammar tip |
| 6 | Remove only dead SRS; keep live 4-grade flow |
| Bug | Fix empty `tier3_context` TypeError + inaccurate `/study` message |

## Scope of this PR

### A. Remove stale daily flow (`bot.py`)
- `_generate_daily_batch` (321), `_daily_avoid_words` (396), `_daily_card_session_profile` (413), `_ensure_daily_cards` (424), `_ensure_next_daily_card` (447), `_send_next_daily_card` (479), `send_daily_card_now` (550, dead), `_show_review_date` (611), `_send_card_from_store` (243).
- `_handle_daily_prepare` in `handlers/user.py:606` (imported at `bot.py:139`).
- Router branches: `daily:prepare:`, `daily:next:`, `daily:prev:` (`bot.py:946-1032`) and `review:prepare:` (`bot.py:948-949`); `startswith` guard rows at `bot.py:848-850`.
- **Do NOT** remove daily tables / their DB get/add/update functions yet (Phase 2b).

### B. Remove review menu (`bot.py` + `handlers/user.py`)
- `_show_review_menu` (`user.py:786`; imported `bot.py:141`), `_review_history_page` (`user.py:562`).
- Router branches: `review:menu`, `review:page:`, `review:date:`, `review:next:`, `review:noop` (`bot.py:1033-1091`).

### C. Remove dead SRS (keep live flow)
- `_handle_srs_reveal` (`srs_handler.py:165`), `_handle_srs_prepare` (`srs_handler.py:233`), `start_srs_review` (`user.py:516`, zero callers).
- Router branches: `srs:prepare:` (`bot.py:1118-1123`), `srs:reveal:` (`bot.py:1124-1129`).
- **KEEP** `_handle_srs_review` (4-grade, `srs_handler.py:69`), `srs:fe:` → `_handle_first_exposure_grade`, `_handle_query_add`.

### D. Remove keyboards (`config/keyboards.py`)
- `daily_card_keyboard` (290), `daily_review_menu_keyboard` (343), `daily_review_dates_keyboard` (351), `srs_hidden_keyboard` (531), `srs_revealed_keyboard` (543), `srs_review_keyboard` (555).
- **KEEP** `get_review_keyboard`, `get_first_exposure_keyboard`, `study_start_keyboard`.

### E. Remove dead bot.py imports
- `srs_hidden_keyboard`, `srs_revealed_keyboard`, `srs_review_keyboard` (`bot.py:68-70`), `daily_review_dates_keyboard` (`bot.py:65`), `daily_review_menu_keyboard` (`bot.py:66`), `_saved_word_card` (`bot.py:155`, unused in bot.py).

### F. Session-completion bug fix (`handlers/study_handler.py`)
- `advance_session:273` — only call `generate_tier3_node(**state.tier3_context)` when `tier3_context` is non-empty (has `user_id`); otherwise go straight to session-complete.
- `advance_session:303` — replace "لطفاً `/study` را دوباره بزنید" with an accurate Persian message (e.g. "لطفاً دوباره مطالعه را شروع کنید") via `escape_mdv2`. `/study` is not a registered command (only `/start`, `/backup`, `/restore`).

## Callback Routing Map changes (AGENTS.md §3 + callback-wiring skill)

| Prefix | Disposition |
|---|---|
| `daily:prepare:`, `daily:next:`, `daily:prev:` | remove |
| `review:prepare:`, `review:menu`, `review:page:`, `review:date:`, `review:next:`, `review:noop` | remove |
| `srs:prepare:`, `srs:reveal:` | remove |
| `srs:fe:`, `srs:` (4-grade), `query:add:`, `study:start`, `query:prepare:`, `tts:`, `admin:`, `llm:`, `lang:`/`goal:`/`level:` | keep |

**Wiring-integrity test required:** update `tests/test_wiring.py` to assert the removed prefixes are gone and the surviving routes (`srs:fe:`, `study:start`, `query:add:`) still resolve in `callback_router`.

## Tests to update

- `tests/test_wiring.py` — ALLOWLIST / removed-route assertions; keep reverse-wiring guard.
- `tests/test_custom_word_query.py` — remove refs to `daily_card_keyboard`, `daily_review_menu_keyboard`, `daily_review_dates_keyboard` (lines 21-24, 91-94, 153-163, 176-183).
- `tests/test_keyboards.py` — remove daily/review keyboard tests (lines 246-298, import line 9).
- `tests/test_reliability.py` — remove daily-table usage (lines 259-268, 335-348, 419-436, 490, 508, 551, 581-589). **Keep** `request_kind="daily_batch"` (line 167) — admin wizard still uses it.
- `tests/test_srs_staged_reveal.py` — KEEP (tests live 4-grade flow). Verify no stale refs.
- `tests/test_integration/test_srs_callback_routing.py` — the `SchemaMigrationTest` and daily-table setup **stay for 2a** (tables still exist); only remove if a stale-flow test breaks. Verify.
- `tests/test_dead_code_guard.py` — add BANNED symbols for removed handlers/keyboards (`_handle_srs_reveal`, `_handle_srs_prepare`, `start_srs_review`, `daily_card_keyboard`, etc.). Daily tables NOT banned yet (that is 2b).

## New / updated focused tests
- Wiring-integrity assertions for surviving routes (`srs:fe:`, `study:start`, `query:add:`) and absence of removed routes.
- Session-completion: grading the last card of a session shows "جلسه مطالعه تموم شد" (no crash) — unit + integration.
- Dead-reference guard additions for removed SRS symbols.

## Steps

| Step | Description | Status |
|------|-------------|--------|
| 1 | Persist plan | complete |
| 2 | Create branch `feat/phase-2-stale-flow-cleanup` from latest `origin/main` | complete |
| 3 | Remove daily flow handlers + router branches (`bot.py`, `user.py`) | complete |
| 4 | Remove review menu handlers + router branches (`bot.py`, `user.py`) | complete |
| 5 | Remove dead SRS handlers + router branches (keep live flow) | complete |
| 6 | Remove stale keyboards (`config/keyboards.py`) | complete |
| 7 | Remove dead bot.py imports | complete |
| 8 | Fix session-completion crash + message (`study_handler.py`) | complete |
| 9 | Update/add tests (wiring, keyboards, custom_word_query, reliability, dead_code_guard, session-completion) | complete |
| 10 | Full validation suite (`hamzaban-validation`) | complete |
| 11 | Independent review subagent (`hamzaboon-reviewer`) | in-progress |
| 12 | Commit, push, PR; update AGENTS.md §3, ROADMAP.md, project_status.json + dashboard, issue #245 | planned |

## Update Log
- 2026-08-05: Plan persisted; contract locked (Rules 1, 2-partial, 5, 6, Bug=A).
- 2026-08-05: Phase 2a implementation + tests done. Full suite: 372 tests OK. Ruff (tracked files) clean; `git diff --check` clean. `user.py` extra dead imports removed. `tests/test_wiring.py` added `test_phase2_stale_callbacks_removed_and_survivors_routed`.
- (Phase 2b continues in `.opencode/plans/fsrs/plan-fsrs-session-completion-phase-01-daily-schema-purge.md`.)
