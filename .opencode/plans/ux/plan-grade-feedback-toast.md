---
name: grade-feedback-toast
description: Owner-locked grade-submission feedback UX - success toast vs important-error modal.
created: 2026-08-11
base_commit: a62bb12
branch: feat/grade-feedback-toast
worktree: .worktrees/grade-feedback-toast-308
github_issue: 308
status: in-progress
---

STATE: phase 1/1 - status: in-progress - focus: inspect the grade callback, write focused tests, and implement the locked feedback behavior.

# Grade-Feedback-Toast

## Locked Contract

<SYSTEM_GATE> Contract lock required before proceeding </SYSTEM_GATE>

### Rule 1
Decision: Feedback shown after a successful grade submission.

| Option | Practical effect | Trade-offs |
|---|---|---|
| A - silent toast (chosen) | Show a brief notification with `show_alert=False`. | Does not interrupt study flow; easier to miss than a modal. |
| B - modal | Require the learner to dismiss a popup. | More visible, but adds a tap after every successful grade. |

## CONTRACT LOCK TEMPLATE

Rule #: 1
Decision: Successful grade feedback presentation.
Option Chosen: A - silent toast using `update.callback_query.answer(text, show_alert=False)`.
Alternatives Rejected: B - modal, because it interrupts every successful review.
Trade-offs: The toast preserves study flow but is less prominent than a modal.
Owner Confirmation: "lock it hell yeah."
GATE STATUS: LOCKED

### Rule 2
Decision: Feedback shown for important grade-submission errors.

| Option | Practical effect | Trade-offs |
|---|---|---|
| A - modal (chosen) | Show an error popup with `show_alert=True`. | Ensures the learner notices the problem; requires dismissal. |
| B - silent toast | Show a brief non-blocking notification. | Faster, but an important failure may be missed. |

## CONTRACT LOCK TEMPLATE

Rule #: 2
Decision: Important error feedback presentation.
Option Chosen: A - modal using `show_alert=True`.
Alternatives Rejected: B - silent toast, because important failures may be missed.
Trade-offs: The modal adds one dismissal tap only on errors, in exchange for visibility.
Owner Confirmation: "lock it hell yeah."
GATE STATUS: LOCKED

## Scope

- Grade-submission feedback in `handlers/study_handler.py` and, only if required by the existing flow, `bot.py`.
- This ticket owns the toast/modal UX contract consumed by the session-engine T05 integration plan.
- Feedback must go through the shared `notify_callback(query, text, intent=...)` module (`services/utils/callback_notifications.py`, merged in #311); do not call `query.answer(...)` directly.
- No callback-data, router-prefix, keyboard, persistence, quota, scheduling, schema, or AI-contract changes.
- Keep this as its own small PR.
- AI cost impact: zero new AI calls and zero token-cost increase.

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | Existing grade callback prefix | keep |
| Router branches | Existing grade callback dispatch | keep |
| Keyboard builders / constants | Existing study keyboards | keep |
| DB tables / columns / functions | Existing grade persistence | keep |
| Handler functions | Existing grade-submission feedback path | update |
| Imports / re-exports | Existing imports only | keep unless a focused test proves an update is needed |
| Prompts / formatting helpers | Existing callback-answer text | keep unless the locked feedback path already supplies relative-time text |
| Tests referencing them | Focused handler/integration tests | update |
| Docs | Issue #308 and this plan | update |

Callback wiring assessment: callback data, router dispatch, sub-router actions, and keyboard construction are not changing. A new wiring-integrity route test is therefore not required; existing wiring guards remain part of repository validation.

## Acceptance Criteria

- Successful grade submissions call `notify_callback(query, text, intent=CallbackNoticeIntent.SUCCESS)` (silent toast).
- Important grade-submission errors call `notify_callback(query, text, intent=CallbackNoticeIntent.IMPORTANT_ERROR)` (modal).
- No direct `query.answer(...)` / `show_alert` usage is introduced.
- Existing persistence, session advancement, quotas, and callback routing remain unchanged.
- Focused handler-level integration tests cover both outcomes.
- Full repository validation passes before commit.

## Relation to Other Tracks

- #308 remains a separate small ticket from FSRS T05, but its locked feedback UX is an input to T05's Handler/UX Integration plan.
- Independent of the custom-word query track.
- See `.opencode/plans/TICKETS.md` for the global register.

## Blocked Questions

None.
