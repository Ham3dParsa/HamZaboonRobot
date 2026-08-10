---
name: parallel-work-guard
description: Claim seams before any new Contract Lock Gate session and before creating a new branch/worktree, so parallel branches/worktrees never silently collide on the same module.
license: Copyright (c) Ham3dParsa. All rights reserved.
---
# Parallel Work Guard Skill

A **claim** is a locked contract's declared ownership of one or more seams —
the domain boundaries and shared resources that two parallel branches/worktrees
could silently collide on without touching the same file. The canonical list of
seams is in SEAMS.md (this skill folder). Do not invent ad-hoc seam names.

Run this skill when a task reaches a Contract Lock Gate or creates a branch/worktree.
When a task runs entirely in one session on one branch with no parallel work in
progress, the seam check is a fast no-op — still run it, but do not slow the gate.

## Steps

1. Resolve the shared claims file as `<git-common-dir>/parallel-work-claims.json`
   by running `git rev-parse --git-common-dir`, then read that file. If it is
   missing, initialize it as `{"claims": []}`. If it exists but is malformed
   or cannot be read, STOP and request owner repair. Halt only claim-guarded
   work; unrelated read-only investigation may continue. Do not treat
   malformed JSON as an empty registry.
2. Before the Contract Lock Table is presented (AGENTS.md §2.4 step 3), list
   every seam this task's rules will touch, cross-referencing SEAMS.md's
   canonical seam names. Do not invent ad-hoc seam names.
3. For each seam identified, check the shared claims file for an existing unresolved
   claim held by a different branch on the same seam.
   - No overlap: proceed to the gate as normal.
   - Overlap found: STOP. Report the exact seam(s), the claiming branch, and
   the precise colliding resource (table/column name, callback prefix, or
    catalog identifier — never just "overlap detected"). Ask the owner to
    choose: proceed anyway, or wait. Do not proceed until answered.
4. Once the Contract Lock reaches GATE STATUS: LOCKED, resolve the current
   branch with `git branch --show-current`, then acquire a file lock or
   equivalent exclusive-write lock before reading the shared claims file. Hold
   that lock through parsing, overlap/duplicate matching, modification,
   validation, and the complete write; release it only after the write is
   finished. Under that same lock, parse the JSON object, validate it, then
   match the current branch's existing claim by exact equality of its `branch`
   value with `git branch --show-current`. If a matching claim exists, update
   it; otherwise append a new claim
   `{branch, seams: [...], locked_at (ISO 8601 UTC, e.g. 2026-08-10T12:00:00Z), rule_ids: [...]}`. Preserve
   unrelated claims. Write via a temporary file followed by an atomic
   replacement while the lock is held so concurrent sessions cannot lose
   claims.
5. On post-merge cleanup (AGENTS.md §5 step 8), atomically remove this branch's
   claim from the shared claims file. On every skill load, flag (do not
   auto-delete) any claim with `locked_at` older than 14 days for owner review.

## Completion criterion

Every seam named in the locked contract has either zero overlapping claims, or
an explicit owner decision on record for each overlapping claim found.

## Related skills

The seam-check (step 3) runs inside the Contract Lock Gate sequence; it does not
restate contract-lock-gate's own steps. See contract-lock-gate for the gate.
