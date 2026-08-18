---
name: plan-study-session-grade-restart
description: Fix study-session grade rejected after bot restart (issue #401, follow-up to Bug #363 / PR #364)
created: 2026-08-18
base_commit: dd7c409
branch: fix/study-session-grade-restart
status: in-progress
---
STATE: phase 1/1 — status: in-progress — focus: make grading session-aware + DB-backed advance + idempotent re-grade, so a mid-session restart no longer soft-locks the learner

## Context
Bug #401 / follow-up to Bug #363 (PR #364). PR #364 restored the *card display* after restart but not the grade transaction. The session's progress (which card is next) lives only in `context.user_data["current_session"]` (in-memory, wiped on restart). Grade handlers commit the word's scheduling state to the DB independently, then call `advance_session`, which no-ops when `current_session` is None → the grade is orphaned and the same card is re-shown; re-grading hits `wrong_state`. Revealed/prompt state is also in-memory (secondary, deferred).

## Locked contract (owner 2026-08-18, "proceed")
- R1 — DB-backed advance: `advance_session` restores from `_restore_persisted_session` when `current_session` is None, then pops+persists+renders. (Recommended)
- R2 — Stale-callback guard on both grade handlers (mirror `_handle_srs_reveal`): reject `word_id != nodes[0].source_id` with `این پیام دیگر معتبر نیست`. (Recommended)
- R3 — Idempotent re-grade + resume reconciliation, **scoped to a single session** (owner clarification): track per-session `graded_word_ids`; if a grade's DB write landed but advance was lost (restart/network) or the learner double-taps, the bot recognizes the card was already graded *in this session* and just advances — no double grade (FSRS corruption), no soft-lock. A card legitimately reappearing in a *new* session later today (normal FSRS review) is still graded normally. (Recommended)
- R4 — Reveal-state persistence: deferred (owner: "not a big deal").
- R5 — Integration test reproducing restart→grade, double-tap, and stale-button.
- R6 — Day-scoping (Tehran): persisted session valid for today only; existing `_restore_persisted_session` date check (`session_date != _app_day_str()`) already discards cross-day and is verified — no new code.

## Implementation
- `handlers/study_handler.py`:
  - `SessionState` gains `graded_word_ids: list[int]` (default_factory).
  - `_state_to_json`/`_state_from_json` include `graded_word_ids`.
  - `handle_study_start` fresh build initializes `graded_word_ids=[]`.
  - New public `get_active_study_session(user_id, context)` → user_data current_session, else restore+stash.
  - `advance_session` falls back to `_restore_persisted_session` when `current_session` is None (R1).
- `handlers/srs_handler.py`:
  - Import `get_active_study_session`.
  - Both `_handle_srs_review` and `_handle_first_exposure_grade`: resolve session; stale guard (R2); on `ok` append word_id to `graded_word_ids` + telemetry/streak + advance; on `wrong_state` with matching `nodes[0]` → idempotent skip (`قبلاً ثبت شد.`) + advance, no telemetry/streak (R3); else error.
  - No callback prefix / keyboard change.

## Dependency & Wiring Map
| Type | Items | Disposition |
|---|---|---|
| Callback prefixes | `srs:fe:`, `srs:` | keep |
| Router branches | `bot.py` srs dispatch | keep |
| DB tables/cols | `study_sessions`, `saved_words.first_exposure_done/last_review_at` | keep (no schema change) |
| Handlers | `study_handler.py` (SessionState, advance_session, get_active_study_session, handle_study_start), `srs_handler.py` (both grade handlers) | update |
| Tests | `tests/test_integration/test_study_session_grade_restart.py` (new) | add |

## Blocked Questions
- None — all rules locked 2026-08-18.

## Notes
- Persistence seam (#1) is held by `refactor/db-concurrency`; this fix only *consumes* the DB layer, does not edit `get_conn`/schema. Owner chose proceed-anyway; rebase onto `origin/main` before PR.
