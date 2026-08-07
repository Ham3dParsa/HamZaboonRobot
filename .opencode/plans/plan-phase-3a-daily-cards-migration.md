---
name: phase-3a-daily-cards-migration
description: Migrate daily_cards to saved_words as Tier-2 first-exposure cards, add FSRS columns, wire startup migration
created: 2026-08-05
base_commit: 97997534ef86fe50fb3e03dc18813e4555a813fa
branch: feat/phase-3a-daily-cards-migration
status: complete
---

# Phase 3a — Daily Cards Migration to Session Engine (Tier 2 First-Exposure)

Traces to `docs/plans/fsrs/plan_daily_cards_migration.md` (PR 1 of 3) and
`docs/plans/fsrs/plan_fsrs_migration_v2.md` (Phase 1a.6–1a.11, Phase 2 partial).

## Locked Contract Rules (owner-approved 2026-08-05, all "Recommended")

| Rule | Decision |
|------|----------|
| 1 | Language: per-date `daily_card_sessions.target_lang`, fallback to `users.target_lang` |
| 2 | Scope: migrate ALL historical daily_cards (deduped) |
| 3 | Conflict: keep existing `saved_words.card_data` (INSERT OR IGNORE, no DO UPDATE) |
| 4 | Timing: one-time startup migration, idempotent via `settings.fsrs_migration_done` |
| 5 | Fix `due_words_for_user()` to `AND first_exposure_done=1` in THIS PR (prevent Tier1/Tier2 double-presentation) |

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| DB schema | `saved_words`: add `first_exposure_done`, `stability`, `difficulty` | update |
| DB function | `migrate_saved_words_to_fsrs()` (words.py:305) | update (stub→real) |
| DB function | `get_pre_first_exposure_words()` (words.py:293) | update (stub→real) |
| DB function | `due_words_for_user()` (words.py:258) | update (add first_exposure_done=1) |
| DB function | `add_saved_word()` (words.py:180) | update (write new columns) |
| Settings | `fsrs_migration_done` guard key | add |
| Startup | `bot.py main()` (bot.py:1322) | update (call migration after init_db) |
| Callback prefixes | none | keep |
| Session assembly | `build_session_list`/`build_session` consume the two DB functions | keep |
| Tests | `test_migration_guards.py`, `test_srs_callback_routing.py`, new Tier2/session tests | update |
| Docs | AGENTS.md §3, ROADMAP.md, project_status.json (+dashboard), issue #245 | update |

## Steps

| Step | Description | Status |
|------|-------------|--------|
| 1 | Persist plan | complete |
| 2 | Schema: add 3 columns in schema.py saved_word_columns block | complete |
| 3 | Implement migration + get_pre_first_exposure_words + due_words filter + add_saved_word | complete |
| 4 | Wire migration into bot.py main() | complete |
| 5 | Update/add tests | complete |
| 6 | Full validation suite | complete |
| 7 | Independent review subagent | complete (2 findings fixed: vacuous tests onboarded) |
| 8 | Commit, push, PR; update docs/issues | complete (commits 88e80fc+304f077, PR #252, CI green; docs/issues updated) |

## Update Log
- 2026-08-05: Plan persisted; contract locked (5 rules, all Recommended).
- 2026-08-05: Implementation complete; full suite 384 tests OK; reviewer confirmed no bugs after fixing 2 vacuous test fixtures.
- 2026-08-05: PR #252 (commits 88e80fc + 304f077) CI green; docs/issues updated. Phase 3a done.
