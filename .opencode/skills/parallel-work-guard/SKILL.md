---
name: parallel-work-guard
description: Check for seam claims before any new Contract Lock Gate session, before creating a new branch/worktree, or when multiple branches/worktrees run at once, so parallel work never silently collides on a shared seam.
license: Copyright (c) Ham3dParsa. All rights reserved.
---
# Parallel Work Guard Skill

A **claim** is a locked contract's declared ownership of one or more seams —
the domain boundaries and shared resources that two parallel branches/worktrees
could silently collide on without touching the same file. The canonical list of
seams is in SEAMS.md (this skill folder). Do not invent ad-hoc seam names.

Run this skill at every Contract Lock Gate, before creating a branch/worktree, and whenever parallel branches/worktrees are already in progress.
When a task runs entirely in one session on one branch with no parallel work in
progress, the check usually finds no overlap — still run every step in order, since other worktrees may hold claims in the shared registry.

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
   branch with `git branch --show-current`, then run:
   ```
   powershell scripts/claim_seam.ps1 -Command acquire -Branch <branch> -Seams <s1,s2> -RuleIds <r1,r2>
   ```
   The script handles exclusive file lock, JSON parsing, atomic write via temp
   file + `Move-Item`, and path normalization. Do not inline PowerShell
   file-lock logic; always call this script.

5. On post-merge cleanup (AGENTS.md §5 step 8), run:
   ```
   powershell scripts/claim_seam.ps1 -Command release -Branch <branch>
   ```
   For stale-claim review (14+ days old), run:
   ```
   powershell scripts/claim_seam.ps1 -Command prune -OlderThanDays 14
   ```

## Completion criterion

Every seam named in the locked contract has either zero overlapping claims, or
an explicit owner decision on record for each overlapping claim found.

## Related skills

The seam-check (step 3) runs inside the Contract Lock Gate sequence; it does not
restate contract-lock-gate's own steps. See contract-lock-gate for the gate.
