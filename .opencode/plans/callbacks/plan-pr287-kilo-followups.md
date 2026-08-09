---
name: pr287-kilo-followups
description: Resolve Kilo review findings on the admin AI-preset panel in PR #287.
created: 2026-08-09
base_commit: a871300
branch: fix/admin-ai-presets-audit
status: in-progress
---

STATE: phase 2/3 - status: in-progress - focus: per-preset group detachment

## Problem Statement

Kilo Code Review found two owner-visible defects, a missing per-preset group-detach action, and four test/code-quality gaps in the admin AI-preset panel on PR #287. A rename confirmation can display HTML entities literally, and a stale group-label callback can save a hash as a real label.

## Solution

Make group-label callbacks stale-safe, show rename confirmations as plain text, add a pending-save per-preset detach action, and complete the focused rollback, formatting, import, and test cleanup work.

## User Stories

1. As an admin, I want a group rename confirmation to show the label I entered, including characters such as `&`, so that the confirmation is understandable.
2. As an owner, I want a stale group-label button to fail safely, so that a callback hash is never saved as a group label.
3. As an admin, I want to detach one preset from its group while leaving the other presets unchanged.
4. As an admin, I want group detachment to use the existing Save or Discard flow, so that it is not applied accidentally.
5. As a maintainer, I want the priority-reindex rollback test to prove data was not changed, so that transaction behavior is verified rather than assumed.
6. As a maintainer, I want the formatting helper and tests to handle their inputs precisely, so that small regressions are caught.

## Implementation Decisions

1. Group-rename confirmations remain plain text. The non-HTML confirmation does not apply HTML escaping to dynamic labels.
2. An unresolvable hashed group-label callback is rejected before it can alter wizard state or persistence. Legacy plain-label callback payloads continue to resolve through URL decoding.
3. A new `admin:ai_preset:detach_group:<preset-ref>` action is emitted from the primary custom-preset edit keyboard when the stored group label is non-empty. It stages `group_label` as an empty string in the existing pending edits and requires the established Save confirmation before the database write.
4. Full-edit wizard behavior is unchanged: an empty text response still skips that field. The primary edit keyboard is the single detach entry point for this scope.
5. Explicit transaction rollbacks remain in place. The test verifies state preservation as well as a later successful write.
6. `html_escape` treats only `None` as the special empty value. The unused keyboard import and unreachable test mock are removed.
7. The new detach action accepts only a currently resolvable preset hash. It rejects stale tokens instead of using the general legacy raw-name fallback because this action has no legacy callbacks.
8. When a detach removes the final member of a shared-key group, the same preset-save transaction deletes that label's orphaned shared key. Existing group-wide clear behavior remains unchanged.
9. The existing preset Save operation accepts optional rename and detach-cleanup context so its update/create, old-name removal, and final-member key cleanup complete in one immediate transaction.
10. Orphan cleanup remains limited to the new detach flow. Existing batch label changes and the separate preset-manager tool are recorded as follow-up work rather than broadened here.
11. Starting the full-edit wizard while direct changes are pending is rejected. The admin must Save or Discard first, preserving both staging models without silent merging or loss.
12. An atomic rename Save verifies the destination name remains unclaimed inside its transaction. A late conflict rolls back entirely and leaves the pending edit available for correction.
13. A detach callback is rejected while Full Edit is active for that same preset, so neither staging model can leave a surprise change for the other.
14. Full Edit and detach are session-wide exclusive workflows: Full Edit is blocked by any pending direct edit, and any active Full Edit blocks every detach callback.

## Testing Decisions

1. Use existing callback-codec and admin handler test seams to prove stale hashes leave pending edits and database data unchanged.
2. Add a handler-level integration flow through the owner-gated admin callback path for the detach button. It asserts Telegram feedback, the emitted callback prefix, staged state, Save persistence, and unchanged peer presets using the established isolated database helpers and mocked Telegram APIs.
3. Extend the existing priority-reindex tests to assert no priority changes after a rejected rank, then assert a valid later write succeeds.
4. Extend formatting tests for `None` and falsy non-string input values.
5. Run wiring and dead-reference guards because the detach action changes keyboard construction and AI sub-router dispatch.

## Out of Scope

- Group-wide label clear behavior.
- Batch-size ceiling work (R2).
- Schema or migration changes.
- Any new AI request or provider behavior.
- Adding detach behavior to the full-edit wizard.

## Further Notes

- Owner confirmation: "i accept your recommendations on these. /to-spec , and then /to-tickets, and then implement each in the correct order and commit per validated ticket."
- No AI calls are added; token and cost impact is zero.
- Each phase is a separately validated, explicitly staged Conventional Commit on the existing PR #287 branch.

## Contract Lock

| Rule | Decision | Chosen option | Status |
|---|---|---|---|
| 1 | Rename confirmation rendering | Plain text | LOCKED |
| 2 | Unresolvable group-label callback | Reject safely; preserve legacy plain callbacks | LOCKED |
| 3 | Per-preset detach | Add button; stage change until Save | LOCKED |
| 4 | Priority rollback | Keep explicit rollback; strengthen proof | LOCKED |
| 5 | Minor cleanup | Remove unused import; narrow `html_escape` guard | LOCKED |
| 6 | Dead test setup | Remove unreachable mock | LOCKED |
| 7 | Stale detach preset reference | Reject unresolved token for detach only | LOCKED |
| 8 | Last-member shared key | Delete orphaned key transactionally | LOCKED |
| 9 | Rename plus detach | One atomic preset Save transaction | LOCKED |
| 10 | Existing orphan paths | Defer batch/tool cleanup to a follow-up | LOCKED |
| 11 | Direct edits plus full edit | Require Save or Discard before Full Edit | LOCKED |
| 12 | Late rename collision | Reject without writing or deleting either preset | LOCKED |
| 13 | Detach during Full Edit | Reject without changing either staging area | LOCKED |
| 14 | Cross-preset staging | Keep Full Edit and detach exclusive for the whole admin session | LOCKED |

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | Existing label-picker callbacks; new per-preset detach action | update |
| Router branches | Owner-gated admin dispatcher; AI preset sub-router | keep / update |
| Keyboard builders / constants | Custom-preset edit keyboard; detach label | update |
| DB tables / columns / functions | Existing preset Save transaction gains optional atomic rename and detach-only orphan-key cleanup | update |
| Handler functions | Label resolution, full-edit selection, detach action | update |
| Imports / re-exports | Callback codec / keyboard imports | update / remove |
| Prompts / formatting helpers | Persian admin confirmation; HTML escaping | update |
| Tests | Codec, handler, integration, formatting, DB rollback, wiring | update |
| Docs / issues | Parent specification, three tickets, PR #287 evidence | update |

## Phase Status

| Phase | Ticket | Execution order | Status | Evidence |
|---|---|---:|---|---|
| 1 | #289 Group-label callback and escaping safety | 1 | complete | `5dad67f`; focused suite and 589 full tests passed |
| 2 | #290 Per-preset group detachment | 2 | ready | Rules 3, 7-14 implemented; 602 full tests passed; staged pending commit |
| 3 | #291 Rollback test proof | 3 | pending | Not started |

## Follow-up Risks

- Existing batch group-label changes and the separate preset-manager tool can leave orphaned shared keys. Owner selected deferred handling (Rule 10); tracked in #292 rather than widening this PR.
- The full-edit wizard Save path remains a separate non-atomic rename (pre-existing; plan held wizard unchanged). Owner deferred; tracked in #299.
