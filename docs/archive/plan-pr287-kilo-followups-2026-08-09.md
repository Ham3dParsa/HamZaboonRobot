---
name: pr287-kilo-followups
description: Resolve Kilo review findings on the admin AI-preset panel in PR #287.
created: 2026-08-09
base_commit: a871300
branch: fix/admin-ai-presets-audit
status: archived
---

# Plan: PR #287 Kilo Code Review follow-ups

STATE: phase 3/3 - status: complete - all tickets merged via PR #287 (squash `6ab4d40`)

## Problem Statement

Kilo Code Review found two owner-visible defects, a missing per-preset group-detach action, and four test/code-quality gaps in the admin AI-preset panel on PR #287. A rename confirmation can display HTML entities literally, and a stale group-label callback can save a hash as a real label.

## Solution

Made group-label callbacks stale-safe, rename confirmations plain text, added a pending-save per-preset detach action, and completed the focused rollback, formatting, import, and test cleanup work.

## Implemented Tickets

| Phase | Ticket | Commit | Status | Evidence |
|---|---:|---|---|---|
| 1 | #289 Group-label callback and escaping safety | `5dad67f` | complete | Rules 1, 2, 5, 6; focused 77 + 589 full tests passed |
| 2 | #290 Per-preset group detachment | `577aec7` | complete | Rules 3, 7-14; 602 full tests passed |
| 3 | #291 Rollback test proof | `e995426` | complete | Rule 4; focused tests and 602 full tests passed |
| — | Plan documentation | `cb2f6c7` | complete | Phase status table finalized |

Merged by owner instruction via squash into `main` as `6ab4d40` (PR #287). CI green: label, test (3.10), test (3.13), Kilo Code Review (0 issues found, recommends merge).

## Contract Lock (all LOCKED)

| Rule | Decision | Chosen option |
|---|---|---|
| 1 | Rename confirmation rendering | Plain text |
| 2 | Unresolvable group-label callback | Reject safely; preserve legacy plain callbacks |
| 3 | Per-preset detach | Add button; stage change until Save |
| 4 | Priority rollback | Keep explicit rollback; strengthen proof |
| 5 | Minor cleanup | Remove unused import; narrow `html_escape` guard |
| 6 | Dead test setup | Remove unreachable mock |
| 7 | Stale detach preset reference | Reject unresolved token for detach only |
| 8 | Last-member shared key | Delete orphaned key transactionally |
| 9 | Rename plus detach | One atomic preset Save transaction |
| 10 | Existing orphan paths | Defer batch/tool cleanup to a follow-up |
| 11 | Direct edits plus full edit | Require Save or Discard before Full Edit |
| 12 | Late rename collision | Reject without writing or deleting either preset |
| 13 | Detach during Full Edit | Reject without changing either staging area |
| 14 | Cross-preset staging | Keep Full Edit and detach exclusive for the whole admin session |

## Final Verdict

- Done: stale-safety for group-label callbacks; plain-text rename confirmations; per-preset detach orchestrated through the Save/Discard flow with session-wide exclusivity against Full Edit; atomic rename-plus-detach Save; orphaned shared-key cleanup on final-member detach; late-rename-collision rejection; explicit rollback preserved and proven by a non-vacuous reindex test; formatting/import/test cleanup.
- Deliberately Not Done: no schema/migration changes; no new AI requests or cost impact (zero token impact); group-wide label clear behavior unchanged; batch-size ceiling work (R2) skipped per owner; full-edit wizard Save path left non-atomic.
- Deferred: existing batch group-label changes and the preset-manager tool still leave orphaned shared keys — tracked in #292 (Rule 10); the full-edit wizard's separate non-atomic rename — tracked in #299.
- Uncertain: none beyond the two tracked follow-ups; Kilo re-review of the final HEAD found 0 issues.

## Archive Note

Active working files `.opencode/plans/callbacks/plan-pr287-kilo-followups*.md` were removed from the working tree on 2026-08-09 after this plan completed; content is preserved here and in git history (added in `5dad67f`, finalized in `cb2f6c7`).
