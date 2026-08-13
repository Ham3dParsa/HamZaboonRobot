---
name: fsrs-session-completion
description: Finish Phase 2b cleanup and Phase 3b timestamp-aware FSRS scheduling through six dependency-ordered tickets.
created: 2026-08-09
base_commit: 6ab4d40eb3eb5754387c31c4ce5cad32a3ea445b
branch: multiple-see-release-boundaries
status: in-progress
---

STATE: phase 5/6 — status: MERGED — Phases 1-5 committed and merged via PR #336
(squash `f77214c` on main); all checks green; T09 (release/docs reconciliation)
remains in progress

# FSRS Session Completion — Locked Spec and Main Plan

## Purpose

Complete the pull-based FSRS session engine in the locked order:

```text
Admin-AI PR merged
        -> Phase 2b persistence purge
        -> timestamp schema expansion
        -> FSRS grading transitions
        -> due selection and DSR priority
        -> handler/UX integration
        -> validation, docs, and release
```

This plan supersedes the Phase 2b implementation scope now archived at
`docs/archive/plan-phase-2b-drop-daily-tables-superseded-2026-08-09.md`.
Historical product and architecture plans under `docs/plans/fsrs/` remain
source references and are reconciled in Phase 6 rather than rewritten before
implementation evidence.

## Contract Status

```text
<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>
Owner confirmation: "Locked — run /to-tickets (Recommended)"
GATE STATUS: LOCKED
```

The owner selected every decision independently through the contract-lock
question gate. No production or test implementation begins until the external
admin-AI prerequisite is merged and the Phase 1 branch is created from clean
latest `origin/main`.

## Domain Terms

| Term | Meaning |
|---|---|
| First exposure | The first familiarity grade for a saved card (`first_exposure_done=0 -> 1`) |
| Regular review | A later recall grade after first exposure |
| Same-day due | Due at an exact timestamp under 24 hours, eligible only in a later session |
| Transient review state | `review_status`, `review_requested_at`, `retry_at`, and `srs_retry_attempts` |
| `GradeResult` | Handler-facing result containing success/failure reason and exact next due time |

## Contract Lock Template — One Row Per Rule

| Rule | Decision | Option chosen | Alternatives rejected | Trade-offs | Owner confirmation | Status |
|---|---|---|---|---|---|---|
| 1 | Execution order | Finish admin-AI PR; Phase 2b before Phase 3b | Stash and start; Phase 3b first | Delays FSRS start but prevents mixed work and follows the locked migration order | "Finish admin-ai PR first"; "2b then 3b" | LOCKED |
| 2 | Daily subsystem removal | Drop three daily tables/functions/migration; remove TTS `d` and stale ALTER block; leave dev tools untouched | Keep runtime residuals; widen into tool cleanup | Complete runtime purge with bounded PR scope; tools are documented stale | "Remove both"; "Leave untouched" | LOCKED |
| 3 | Old SRS schema | Drop `interval_idx`; keep pending/retry columns through Phase 3b | Defer/drop permanently; remove all legacy fields now | Completes planned dead-column removal without combining scheduling redesign into Phase 2b | "Drop in Phase 2b"; "Keep through Phase 3b" | LOCKED |
| 4 | Destructive migration safety | Offline maintenance, DB snapshot, abort if daily tables exist without migration flag | Live destructive rollout; auto-migrate; drop regardless | Requires maintenance window but prevents silent loss and keeps rollback evidence | "Yes — maintenance/offline"; "Abort without deleting" | LOCKED |
| 5 | Grading seam | Keep `grade_first_exposure` and `grade_word_review` in `words.py` | Merge by `activity_type`; add pure grading module | Keeps familiarity and recall formulas separate and avoids module/cycle churn | "Keep two functions" | LOCKED |
| 6 | Timestamp schema | Add UTC `last_review_at`/`next_review_at`; keep and dual-write `next_review`; reset invalid exposed rows | Reuse date column; drop date immediately; derive fake history | Additive and rollback-friendly, at the cost of temporary dual state | "Add UTC timestamp columns"; "reset anomalies" | LOCKED |
| 7 | FSRS timing | Exact sub-day timestamps; rounded whole days at/above one day; official short-term mode globally enabled | One-day minimum; normal formula for same-day; mixed custom mode | Adds same-day behavior and amends two prior decisions, but follows the documented FSRS-6 formula | Persian custom interval answer; "Use short-term formula"; "Enable official mode globally" | LOCKED |
| 8 | Grade transaction and guards | One immediate transaction; ownership/state checks inside; first-exposure idempotency; regular double-tap risk retained; clear all transient state | Handler stale row; permissive wrong-state grades; guard every callback; leave retry state | Correct state transition without a new callback identity or quota rule | "Guard state, keep review risk"; "Clear all transient state" | LOCKED |
| 9 | Grade result and learner UX | Return `GradeResult`; show relative Persian time | Bool + generic copy; absolute date/time | Wider return value, but truthful user feedback and explicit expected failures | "GradeResult + next interval"; "Relative Persian time" | LOCKED |
| 10 | Telemetry transaction | Commit scheduling first; write `review_events` separately | One atomic cross-module transaction | A telemetry failure can lose one history row but cannot block learning progress | "Yes — keep writes separate" | LOCKED |
| 11 | Due priority | Retrievability ASC, difficulty DESC, due timestamp ASC, ID ASC | Overdue-only; ID-only; unstable DB order | Deterministic DSR priority with difficulty used only after equal retrievability | Owner custom answer: higher difficulty is more urgent on equal R | LOCKED |
| 12 | Session/quota interaction | Same-day card appears in a later session; no current-session requeue; no quota bypass | Bonus session; current-session requeue | Uses current DB-driven 2-5 sessions/day and avoids quota/product expansion | "Due in a later session"; "Do not bypass quotas" | LOCKED |
| 13 | AI cost | No new AI calls or tokens | Any new generation/validation request | FSRS scheduling remains provider-independent | Locked scope conclusion | LOCKED |
| 14 | Tier-2 ordering | Manual/Word-Query (`entry_source='manual'`) cards before legacy AUTO before first exposure; `added_at ASC` within each group | Keep added_at ASC only | Manual-first within each group | Prioritizes user-initiated Word-Query cards; AUTO cards surface after | Owner custom: "manual cards originated from word query have more priority since asked and added by user" (2026-08-13) | LOCKED |

## Amended Previous Decisions

This contract deliberately supersedes two entries in
`docs/plans/fsrs/plan_fsrs_migration_v2.md` once implementation is verified:

| Previous decision | Previous behavior | Locked replacement |
|---|---|---|
| Decision 1 — short-term formula | Present but `enable_short_term=False` | Official short-term mode enabled globally; elapsed under one day uses `short_term_stability` |
| Decision 10 — first-exposure grade 1 | Forced one-day revisit | Exact interval from stability `0.212` days, approximately 5 hours 5 minutes |

Decision 34 remains partially intact: first-exposure double taps are prevented
by the state transition, while regular-review double taps remain an accepted
risk until a separate callback-identity contract is approved.

## Scheduling Contract

### First exposure

```text
require first_exposure_done = 0
stability = initial_stability_first_exposure(grade)
difficulty = initial_difficulty(grade)
last_review_at = now UTC
interval < 1 day  -> preserve exact fractional duration
interval >= 1 day -> max(1, round(interval)) days
next_review_at = now UTC + interval
next_review = next_review_at converted to APP_TIMEZONE date
first_exposure_done = 1
clear review_status/review_requested_at/retry_at/srs_retry_attempts
```

### Regular review

```text
require first_exposure_done = 1
elapsed_days = (now UTC - last_review_at) as fractional days
difficulty = update_difficulty(old_difficulty, grade)

if elapsed_days < 1:
    stability = short_term_stability(old_stability, grade)
else:
    retrievability = compute_retrievability(elapsed_days, old_stability)
    stability = update_stability(
        old_difficulty, old_stability, retrievability, grade
    )

schedule exact hours below one day; rounded days otherwise
last_review_at = now UTC
dual-write next_review_at and next_review
clear transient review state
```

### GradeResult

The public return value is intentionally small:

```text
ok: bool
reason: "" | "not_found" | "wrong_state"
next_review_at: aware UTC datetime | None
interval_seconds: int | None
```

Invalid grades raise `ValueError`. SQLite errors propagate. Expected missing or
wrong-state actions return a falsy result and do not create telemetry, touch
streak, or advance the session.

## Learner UX Contract

Storage remains exact. Only display hours are rounded:

```text
Under 24 hours: ثبت شد؛ مرور بعدی: حدود N ساعت دیگر.
One day:        ثبت شد؛ مرور بعدی: فردا.
Longer:         ثبت شد؛ مرور بعدی: N روز دیگر.
```

These are plain callback alerts with no Markdown parse mode. Session quotas
remain DB-driven. The current live rows are free=2, bronze=3, silver=3,
gold=4, emerald=5 sessions/day. A card that becomes due after all slots are
used stays due until the next allowed session.

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefix | `tts:pronounce:` | keep |
| TTS action | `q`, `s` | keep |
| TTS action | legacy `d` | remove/reject |
| SRS callbacks | `srs:fe:`, `srs:1..4:` | keep unchanged |
| Router branches | top-level TTS/SRS routes | keep |
| Handler branch | `_handle_tts_pronounce` daily source | remove |
| Grade handlers | `_handle_srs_review`, `_handle_first_exposure_grade` | update for `GradeResult` and relative alert |
| Keyboards | query/saved-word TTS and grade buttons | keep |
| DB tables | `daily_cards`, `daily_progress`, `daily_card_sessions` | remove |
| DB column | `interval_idx` | remove |
| DB columns | `last_review_at`, `next_review_at` | add |
| DB column | legacy `next_review` | keep and dual-write |
| DB columns | pending/retry state | keep; clear after successful grade |
| DB functions | daily-table functions and startup migration | remove |
| DB functions | two grade functions and due selection | implement/update |
| Prompt | `daily_batch_system_prompt` | keep |
| Formatting | relative Persian due-time helper | add |
| Tools/notebook | old daily-table utilities | keep; document stale |
| Tests | schema, migration, dead refs, TTS wiring, grading, due priority, integration, quota | update/add |
| Docs | FSRS plans, active plan index, roadmap/status/issues/dashboard | reconcile |
| AI | provider calls and token use | keep unchanged (zero new calls) |

## Test Contract

1. Fresh DB and prior-schema upgrade prove removed tables and `interval_idx` are absent.
2. Upgrade aborts before deletion if daily tables exist without `fsrs_migration_done=1`.
3. Fresh/upgrade schema proves timestamp columns and deterministic anomaly reset.
4. All first-exposure grades persist valid FSRS state; grade 1 is due at approximately 5h5m.
5. Same-day review uses `short_term_stability`; later review uses normal FSRS formulas.
6. Exact timestamps are preserved below one day; documented rounding applies above one day.
7. Ownership and wrong-state failures leave rows unchanged.
8. Successful grading clears all transient pending/retry fields.
9. Due priority is `R ASC, D DESC, due ASC, id ASC`.
10. TTS `q`/`s` continue; stale TTS `d` is rejected.
11. Existing SRS callback strings remain wired and handler integration asserts persisted state.
12. `review_events` failure does not roll back scheduling.
13. Session quota remains unchanged; no bonus session or same-session requeue.
14. Full local validation and independent reviewer are mandatory before commit.

## Phase Tickets

| Phase | Ticket | Branch/PR boundary |
|---|---|---|
| 1 | `plan-fsrs-session-completion-phase-01-daily-schema-purge.md` | `feat/phase-2b-drop-daily-tables` |
| 2 | `plan-fsrs-session-completion-phase-02-timestamp-schema.md` | `feat/fsrs-timestamp-schema` |
| 3 | `plan-fsrs-session-completion-phase-03-grade-transitions.md` | `feat/phase-3b-fsrs-scheduling` (not mergeable alone) |
| 4 | `plan-fsrs-session-completion-phase-04-due-priority.md` | same behavior branch (not mergeable alone) |
| 5 | `plan-fsrs-session-completion-phase-05-handler-integration.md` | same behavior branch; merge after Phase 5 |
| 6 | `plan-fsrs-session-completion-phase-06-release.md` | validation/docs across relevant PRs |

## AI Cost Impact

No new AI calls, validations, repairs, embeddings, prompts, tokens, or provider
quota are introduced. The work is SQLite persistence, pure FSRS math, Telegram
handler state, tests, and documentation only.

## Deferred and Deliberately Not Done

- Do not remove legacy `next_review` in this plan.
- Do not requeue cards inside the current session.
- Do not grant bonus sessions or change DB plan quotas.
- Do not implement Tier-3 AI generation, pooling, or semantic cache.
- Do not add a general regular-review double-tap identity guard.
- Do not update/delete old one-off tools or the inspect-DB notebook.

## Update Log

- 2026-08-09: Current plans and code audited after approximately 35 intervening commits.
- 2026-08-09: Design-It-Twice completed with four independent interface proposals.
- 2026-08-09: Owner independently selected all Phase 2b/3b rules.
- 2026-08-09: Contract locked; `/to-tickets` breakdown approved.
- 2026-08-09: Plan persisted in build mode; implementation initially blocked pending owner decision and admin-AI PR completion.
- 2026-08-09: Owner instructed implementation; PR #287 verified merged; isolated branch/worktree created from `origin/main` at `6ab4d40`; baseline `python -m pytest tests/ -n 14` passed (594 tests).
- 2026-08-13: Rule 14 locked (manual/Word-Query tier-2 ordering, owner custom answer). Phase 04 committed `f7d35be`; Phase 05 committed `be97597` (guards + relative time; owner locked telemetry log-and-continue and 23.5-24h formatter boundary). PR #336 CI green; full suite 847+153 green. Phases 1-5 implemented; awaiting Kilo review and Phase 6 release gate.
- 2026-08-13: Owner accepted Kilo's `enable_short_term` finding as a deliberate Rule-7 decision: production keeps the library default `True`; the standalone simulators (`tools/Fsrs_simulation_v5`, `tools/fsrs-replay`) are outdated research tools and are intentionally left hard-coding `False`. Also fixed Kilo perf suggestion (single `_row_effective_due` parse per due row) and `project_status.json` Phase-3b wiring row.

## Blocked Questions

None. Ticket 01 is in progress.
