---
name: parallel-work-guard
description: Check for seam claims before starting parallel work, or when the owner is running multiple branches/worktrees at once. Trigger on any new Contract Lock Gate session and before creating a new branch/worktree.
license: Copyright (c) Ham3dParsa. All rights reserved.
---
# Parallel Work Guard Skill

A **claim** is a locked contract's declared ownership of one or more seams —
the domain boundaries and shared resources that two parallel branches/worktrees
could silently collide on without touching the same file. The canonical list of
seams is in SEAMS.md (this skill folder). Do not invent ad-hoc seam names.

## Steps

1. Read `.opencode/state/claims.json`. If it is missing or unreadable, treat it
   as `{"claims": []}`.
2. Before the Contract Lock Table is presented (AGENTS.md §2.4 step 3), list
   every seam this task's rules will touch, cross-referencing SEAMS.md's
   canonical seam names. Do not invent ad-hoc seam names.
3. For each seam identified, check `claims.json` for an existing unresolved
   claim held by a different branch on the same seam.
   - No overlap: proceed to the gate as normal.
   - Overlap found: STOP. Report the exact seam(s), the claiming branch, and
     the precise colliding resource (table/column name, settings key, callback
     prefix, or catalog identifier — never just "overlap detected"). Ask the
     owner to choose: proceed anyway, or wait. Do not proceed until answered.
4. Once the Contract Lock reaches GATE STATUS: LOCKED, append a new claim object
   to `claims.json`: `{branch, seams: [...], locked_at (ISO 8601), rule_ids: [...]}`.
5. On post-merge cleanup (AGENTS.md §5 step 8), remove this branch's claim from
   `claims.json`. On every skill load, flag (do not auto-delete) any claim with
   `locked_at` older than 14 days for owner review.

## Completion criterion

Every seam named in the locked contract has either zero overlapping claims, or
an explicit owner decision on record for each overlapping claim found.

## Related skills

The seam-check (step 3) runs inside the Contract Lock Gate sequence; it does not
restate contract-lock-gate's own steps. See contract-lock-gate for the gate.
