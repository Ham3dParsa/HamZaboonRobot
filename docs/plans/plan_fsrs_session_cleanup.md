# Plan — Session-Engine Landing + Stale Flow Removal + SRS Reset

**Status:** `> STATUS: active`
**Cutover strategy:** Sequential PRs (Phase 1 merges the engine; Phase 2 removes stale flows; Phase 3 applies the reset)
**References:**
- `docs/plans/plan_fsrs_migration_v2.md` — the FSRS-6 migration plan (Phases 0–1c marked complete on the branch)
- `services/fsrs_core.py` — pure FSRS-6 engine
- Local branch `feat/fsrs-migration` — carries the working session engine (unmerged onto `main`)
- `gap_analysis.md` — pre-plan code audit

---

## Table of Contents

- [1. Background and Current State](#1-background-and-current-state)
- [2. Locked Architecture Decisions](#2-locked-architecture-decisions)
- [3. Canonical Product Model](#3-canonical-product-model)
- [4. Execution Phases](#4-execution-phases)
- [5. Stale Inventory (from audit)](#5-stale-inventory-from-audit)
- [6. Validation](#6-validation)
- [7. Rollback Appendix](#7-rollback-appendix)
- [8. Owner Decision Log](#8-owner-decision-log)

---

## 1. Background and Current State

The repository is on branch `main`. `handlers/study_handler.py` is a 33-line stub that answers
"جلسه مطالعه در حال آمادهسازی… (هنوز پیادهسازی نشده)". The working session engine — 265-line
study handler, `services/session/` package (`assembly.py`, `grade_policy.py`), rewritten
`scheduling.py`, 4-grade keyboards with `srs:fe:` callbacks, rewritten `record_review_event` with
`grade`/`activity_type`/`grade_source`/`raw_signal`/`response_time_ms`, plus its own tests
(`test_study_handler.py`, `test_session_engine.py`, `test_srs_callback_routing.py`, `test_reviews.py`)
— exists **only** on the unmerged local branch `feat/fsrs-migration` (tip `025f968`, shared ancestor
`ba0f6816`). None of the engine commits are on `main`.

The branch still contains the stale daily / review / old-SRS flows; those are removed in Phase 2.
The branch's `migrate_saved_words_to_fsrs()` is a stub (`return True`); the reset is implemented in
Phase 3.

## 2. Locked Architecture Decisions

Owner-confirmed via the question gate on 2026-08-02:

| # | Decision | Owner choice |
| --- | --- | --- |
| 1 | Session engine source | **Review & merge `feat/fsrs-migration` onto `main`** (rejected: rebuild fresh) |
| 2 | Stale flow removal scope | **Remove all three at once** — daily flow, review menu, old 2-button SRS flow (rejected: staged) |
| 3 | Saved-word reset | **Reset scheduling fields, keep cards + review history** (rejected: wipe saved words) |
| 4 | `daily_batch_system_prompt` | **Keep the prompt** — admin custom-test wizard (`admin.py:2078`) still uses it (rejected: delete and point admin at `custom_word_system_prompt`) |
| 5 | Reset timing | **One-time startup migration** (rejected: manual owner command, every-startup) |

## 3. Canonical Product Model

The ONLY ways a user sees a flashcard:

1. **Ask a word** — `text_router` custom-word path (`bot.py:660-803`): reserve quota → `ai.ask_card`
   behind `_call_ai_limited` → validate/repair → persist `query_result` → render `format_card` →
   `query_result_keyboard`.
2. **Start a pull-based session** via the "شروع مطالعه امروز" button → the session engine assembles
   Tier 1/2/3 nodes and drives the in-place editing flow.

The session engine decides per node whether the user gets a Tier-3 card (new AI generation) or
Tier-1/Tier-2 cards (from the saved-words review box). All saved cards are treated as first-time /
unseen per the reset directive.

No auto-push, no scheduled delivery, no separate review menu.

## 4. Execution Phases

### Phase 1 — Merge the engine onto `main` (Q1)

See `docs/plans/plan_fsrs_phase1_merge_engine.md` for the detailed, lockable plan.

Summary: stash the unrelated working-tree change; update `main`; create `merge/fsrs-engine`; merge
`feat/fsrs-migration`; resolve conflicts; full validation; independent review; PR; owner squash-merge.

### Phase 2 — Remove all three stale card systems (Q2)

On top of the merged engine, one PR:

1. **Daily flow** — remove from `bot.py`: `_generate_daily_batch`, `_ensure_daily_cards`,
   `_ensure_next_daily_card`, `_send_next_daily_card`, `_send_card_from_store`, `send_daily_card_now`,
   `_show_review_date`; callbacks `daily:prepare:`, `daily:next:`, `daily:prev:`; from
   `config/keyboards.py`: `daily_card_keyboard`, `daily_review_menu_keyboard`,
   `daily_review_dates_keyboard`; DB tables `daily_cards`, `daily_progress`, `daily_card_sessions` and
   their get/add/update functions in `services/db/words.py`. Keep `daily_batch_system_prompt`.
2. **Review menu** — remove `_show_review_menu`, `_review_history_page`, callbacks
   `review:menu`/`review:page:`/`review:date:`/`review:next:`/`review:noop`.
3. **Old 2-button SRS flow** — remove `_handle_srs_review`/`_handle_srs_reveal`/`_handle_srs_prepare`
   and old `srs_hidden_keyboard`/`srs_revealed_keyboard`/`srs_review_keyboard`. Keep
   `_handle_query_add` ("Add to review") and the 4-grade handlers + `srs:fe:` routing.
4. **Grammar tip** — remove `send_grammar_tip` (`handlers/user.py:351`) and
   `grammar_tip_system_prompt` (dead, never registered).
5. **Dead code** — `record_review_event_v2` (zero callers), dead imports (`study_start_keyboard`,
   old SRS imports at `bot.py:69-71,85,155`), `services/srs_engine.py` (already deleted by branch).
6. **Tests** — update `tests/test_wiring.py` ALLOWLIST, `test_custom_word_query.py`,
   `test_keyboards.py`, `test_reliability.py`, `test_srs_staged_reveal.py`; add wiring-integrity
   assertions for `srs:fe:` and `study:start`.

Result: session button + ask-word are the ONLY ways to see a card.

### Phase 3 — Reset saved words to first-time (Q3)

1. Implement `migrate_saved_words_to_fsrs()` in `services/db/words.py`: reset `interval_idx`,
   `next_review`, `review_status` to brand-new state on every saved word; keep `card_data` and
   `review_events` history.
2. Wire it as a one-time startup migration.
3. Verify `due_words_for_user` / `get_pre_first_exposure_words` / `grade_word_review` /
   `grade_first_exposure` consume `services/fsrs_core.py`; close any remaining wiring gap.
4. Focused tests: fresh-DB reset, migrated-DB reset, "treated as first-time in a session".

### Phase 4 — Docs, issues, validation

- Update `AGENTS.md` §3 Callback Routing Map (remove `daily:`/`review:` rows; add `study:start`,
  `srs:fe:`, `query:add:`/`query:prepare:`).
- Update `ROADMAP.md`, `project_status.json`; regenerate the dashboard.
- File GitHub issues for findings (e.g., `record_review_event_v2` dead, `migrate_saved_words_to_fsrs`
  stub).

## 5. Stale Inventory (from audit)

Canonical (keep):
- Custom-word query (`bot.py:660-803`), `_handle_query_add` (`handlers/srs_handler.py:64`),
  `_prepare_cached_card`, `_call_ai_limited`, `ai_presets`, cost chokepoints
  (`ai._log_llm_request`, `llm_services._log_preset_usage`), `db.get_saved_word`,
  `db.update_saved_word_fields`.

Stale (remove):
- Daily: `_generate_daily_batch`, `_ensure_daily_cards`, `_ensure_next_daily_card`,
  `_send_next_daily_card`, `_send_card_from_store`, `send_daily_card_now`, `_show_review_date`,
  callbacks `daily:prepare:`/`daily:next:`/`daily:prev:`, keyboards `daily_card_keyboard`/
  `daily_review_menu_keyboard`/`daily_review_dates_keyboard`, DB `daily_cards`/`daily_progress`/
  `daily_card_sessions`.
- Review menu: `_show_review_menu`, `_review_history_page`, callbacks
  `review:menu`/`review:page:`/`review:date:`/`review:next:`/`review:noop`.
- Old SRS: `_handle_srs_review`/`_handle_srs_reveal`/`_handle_srs_prepare`,
  `start_srs_review` (already orphaned), old `srs_*` keyboards, `format_srs_prompt`/
  `SRS_HIDDEN_INSTRUCTION`/`SRS_REVEAL_QUESTION`.
- Dead: `send_daily_card_now` (`bot.py:550`), `send_grammar_tip` (`handlers/user.py:351`),
  `record_review_event_v2`, dead imports at `bot.py:69-71,85,155`.
- Stale SRS scheduling semantics: `INTERVALS_DAYS` ladder, `interval_idx`, `next_review`-based
  `due_words_for_user`, `advance_word_review`, `defer_word_review`,
  `review_status`/`review_requested_at`/`retry_at`/`srs_retry_attempts`, outcome-string
  `record_review_event`.
- Stubs: `get_pre_first_exposure_words`, `grade_word_review`, `grade_first_exposure`,
  `migrate_saved_words_to_fsrs`.

Disconnected on `main`: `services/fsrs_core.py` (zero production importers), `services/srs_engine.py`
(stale scaffold; plan deletes it), `services/scheduling.py` (stub).

## 6. Validation

```powershell
python -m unittest discover -s tests
python scripts/compile_all.py
python -m ruff check --select F821,F811
python scripts/generate_dashboard.py
git diff --check
```

Per-phase focused tests as listed in each phase. CI via `gh pr checks` on every PR. Independent
reviewer subagent per Section 5 of AGENTS.md for behavioral changes.

## 7. Rollback Appendix

- Phase 1: before merging, record `main` tip and stash state. If the merge breaks `main`, revert the
  merge commit (`git revert -m 1 <merge-sha>`) — the branch remains intact for a retry.
- Phase 2: the removal is a normal PR; revert = revert the squash commit. The daily/review flows
  remain reconstructible from git history if ever needed.
- Phase 3: the reset is a destructive-ish data migration. The migration MUST be idempotent and MUST
  first take a one-time snapshot of `saved_words` scheduling fields into a backup table so the reset
  can be reversed if the owner requests it.

## 8. Owner Decision Log

| Date | Question | Choice |
| --- | --- | --- |
| 2026-08-02 | Q1 — engine source | Review & merge `feat/fsrs-migration` |
| 2026-08-02 | Q2 — stale flow scope | Remove all three at once |
| 2026-08-02 | Q3 — saved-word reset | Reset scheduling, keep cards |
| 2026-08-02 | Rule 4 — daily prompt | Keep prompt for admin tool |
| 2026-08-02 | Rule 5 — reset timing | One-time startup migration |
