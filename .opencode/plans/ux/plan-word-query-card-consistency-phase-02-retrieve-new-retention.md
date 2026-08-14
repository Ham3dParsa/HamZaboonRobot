---
name: word-query-card-consistency-phase-02-retrieve-new-retention
description: Phase 2 of the word-query card-consistency spec — duplicate-word retrieve-vs-new (R7) + 30-day retention (R8). Issue #344.
created: 2026-08-14
base_commit: 0d9a491
branch: feat/word-query-dup-retention
status: in-progress
---

STATE: phase 2/2 — status: in-progress — focus: #344 R7/R8 implemented, tests green, pending review/commit/PR

# Phase 2 — Duplicate retrieve-vs-new + 30-day retention (issue #344)

## Scope (locked #344 R7/R8)
- R7a: a "prior card" is the most recent unexpired query_result for the same
  user + lang + normalized `query_text` (the text the user typed).
- R7b: 2-button choice «درخواست جدید (مصرف سهمیه)» / «بازیابی کارت قبلی» via
  new callbacks `query:dup:new:` / `query:dup:reuse:`.
- R7c: retrieve is free (no quota, no AI) — re-render stored `result_json`.
- R8a: default TTL 24h -> 30 days.
- R8b: purge all query_results older than 30 days; wire the previously-dead
  `cleanup_expired_query_results` into the primary retry job (1800s).

## Locked Contract Decisions (owner-confirmed 2026-08-14)
- Dedup match field: **query_text (user-typed)**, not AI word. Runs pre-AI/quota.
- Cleanup cadence: **reuse the existing retry job** (no new repeating job).
- No schema migration: reuse `expires_at` / `query_text` / `word`.

## Implementation
1. `services/db/__init__.py`
   - `create_query_result` default `ttl_seconds` 24h -> `30 * 24 * 60 * 60` (R8a).
   - New `find_unexpired_query(user_id, query_text, lang)` -> most recent unexpired
     row, matching on normalized `query_text` (R7a).
2. `services/word_query.py`
   - New `RetrieveResult` dataclass + `find_duplicate(user_id, text, lang)` (pure
     DB read; corrupt JSON -> None).
   - `ask()` returns `AskResult(kind="duplicate", token=...)` when a prior card
     exists AND `skip_duplicate` is False. `skip_duplicate=True` lets the
     explicit "new card" path avoid re-bouncing onto the same prior card.
3. `config/keyboards.py`
   - New `query_duplicate_keyboard(token)` emitting `query:dup:new:{token}` and
     `query:dup:reuse:{token}` (R7b).
4. `bot.py`
   - Ask block refactored into `_process_ask_word(update, context, user_id, row,
     text, skip_duplicate=False)`; duplicate kind sends the choice.
   - Card delivery factored into `_send_query_card` / `_send_query_closing`,
     shared by fresh-ask and retrieve (R7c).
   - `_handle_query_dup_new` (re-ask with skip_duplicate=True) and
     `_handle_query_dup_reuse` (free re-render).
   - callback_router: allowlist + branches for `query:dup:new:` / `query:dup:reuse:`
     (split on `data.split(":", 3)` — 4 colon-segments).
   - `primary_retry_job`: calls `db.cleanup_expired_query_results()` (R8b).

## Tests
- `tests/test_word_query_duplicate.py` — R7a/R8a unit coverage:
  - 30-day default TTL; explicit ttl override retained.
  - `find_unexpired_query` matches normalized text + user + lang; ignores
    expired / different user / different lang; returns most recent.
  - `find_duplicate` returns None on no prior / corrupt JSON; returns prior card
    without AI.
- `tests/test_integration/test_word_query_duplicate_flow.py` — R7b/R7c end-to-end:
  - Retype word -> 2-button choice, no quota, no AI.
  - `query:dup:reuse` -> free re-render of stored card, no quota/AI.
  - `query:dup:new` -> fresh ask, quota + AI consumed.
- `tests/test_wiring.py` — added `query:dup:new`, `query:dup:reuse` survivors.

## Validation
- Full suite green: `python -m pytest tests/ -n 14` -> 879 passed, 153 subtests.
- `compile_all.py`, `ruff check --select F821,F811`, `generate_dashboard.py`,
  `git diff --check` all pass.

## Status / Evidence
| Rule | Status | Evidence |
|---|---|---|
| R7a | done | `test_find_unexpired_query_*`, `find_duplicate` |
| R7b | done | `query_duplicate_keyboard`, `test_retype_word_*` |
| R7c | done | `_handle_query_dup_reuse`, `test_retrieve_prior_card_*` |
| R8a | done | `test_create_query_result_default_ttl_is_30_days` |
| R8b | done | `primary_retry_job` cleanup call |

## Pending
- Independent review (hamzaboon-reviewer).
- Commit, push, PR (Resolves #344).
- Post-merge docs/issue/roadmap reconciliation.