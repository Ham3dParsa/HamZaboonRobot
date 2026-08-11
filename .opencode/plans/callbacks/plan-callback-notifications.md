---
name: callback-notifications
description: Centralize Telegram callback-query notices behind a semantic notification module.
created: 2026-08-11
base_commit: a62bb1204610c3f587e23937526cef5a936c14d1
branch: refactor/callback-notifications
status: in-progress
issue: 310
---

STATE: phase 3/3 - status: in-progress - focus: final review, validation, and PR evidence

## Locked Contract

| Rule | Chosen behavior | Owner confirmation |
|---|---|---|
| 1 | Centralize every Telegram callback toast, modal, and empty acknowledgement; ordinary chat delivery remains outside this module. | "All callback notices." |
| 2 | Callers supply `CallbackNoticeIntent`, never Telegram `show_alert`; SUCCESS and INFO toast, IMPORTANT_ERROR is modal. | "Semantic intent." |
| 3 | Migrate every current production callback answer; add a direct-answer guard; delete `_answer_callback_safely` only after zero references. | "Migrate all plus guard." |
| 4 | Place the deep module at `services/utils/callback_notifications.py`; it owns expected Telegram callback-answer failures and logging. | "Dedicated module." |
| 5 | Land foundation first, then paused feature branches rebase and re-register claims; do not modify either worktree. | "Foundation first, then rebase both worktrees." |
| 6 | Keep `این دکمه دیگر معتبر نیست.` and `ویزارد منقضی شده` as INFO toasts. | "Keep as toasts (INFO)" |

## Contract Lock Template

Rule #: 1-6
Decision: Shared callback-notification foundation and complete current-surface migration.
Option Chosen: Locked design above.
Alternatives Rejected: Telegram flag exposure, partial migration, helpers.py placement, broad send/reply wrapper, and modal promotion for existing informational error toasts.
Trade-offs: One focused refactor now provides one deep policy seam while preserving present callback presentation and copy.
Owner Confirmation: "proceed per plan persistance skill and write an issue to track it as well."
GATE STATUS: LOCKED

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | All existing prefixes | keep |
| Router branches | `bot.callback_router` and existing sub-routers | keep |
| Keyboard builders / constants | Existing callback data and labels | keep |
| DB tables / columns / functions | None | keep |
| Handler functions | Current direct callback-answer call sites | update |
| Imports / re-exports | `_answer_callback_safely`; new notification module imports | update / remove |
| Prompts / formatting helpers | Existing Persian copy | keep |
| Tests | Reliability, notification, wiring, integration, dead-code tests | update |
| Docs | AGENTS.md, SEAMS.md, plan, rebase report, GitHub issue #310 | update |

## Phases

| Phase | Plan | Status | Evidence |
|---|---|---|---|
| 1 | `plan-callback-notifications-phase-01-module-tests.md` | complete | Focused module tests pass |
| 2 | `plan-callback-notifications-phase-02-migration.md` | complete | All current production answers migrated; helper removed |
| 3 | `plan-callback-notifications-phase-03-guards-handoff.md` | in-progress | Guards and handoff report added; validation pending |

## Constraints

- No callback prefix, keyboard, persistence, quota, scheduling, or AI behavior changes.
- No new AI calls; expected AI token and cost impact is zero.
- Paused `feat/grade-feedback-toast` and `feat/custom-word-query` worktrees are read-only to this work.
- Foundation claim: `Telegram Callback Notifications`; owner authorized the reported overlaps with the paused Study, SRS Grading, and User Domain seams.
