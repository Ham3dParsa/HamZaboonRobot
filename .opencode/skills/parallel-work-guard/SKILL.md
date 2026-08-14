---
name: parallel-work-guard
description: Enforce parallel-work discipline — check seam claims before any Contract Lock Gate, force worktree isolation for every locked implementation, and treat a dirty primary main workspace as read-only, so parallel branches/worktrees never silently collide on a seam or pollute the shared workspace.
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

## Worktree isolation gate (always on)

Every locked-contract implementation runs in its **own isolated git worktree** —
never in the shared primary `main` workspace. This is unconditional, even when
no other branch is active, because the primary workspace is shared state that
any session may be reading. Concretely:

- Before locking, confirm the target branch has a dedicated worktree (create one
  via the `using-git-worktrees` skill if not). The worktree location is only a
  checkout-isolation detail; branch naming and the §7 git protocol are unchanged.
- Never create uncommitted or untracked changes in the primary `main` workspace.
- When the primary `main` workspace is **dirty** — it has uncommitted or
  untracked files not created by this session — treat those files as **read-only
  owned by another session**: report them, and never stash, commit, stage,
  overwrite, or move them. Route all of this session's work to its own worktree.
- Legitimate, owner-authorized `main` housekeeping (e.g. a status/documentation
  commit) is the exception, done only with the owner's explicit instruction and
  via a clean temporary worktree where the shared `main` workspace is entangled.

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
an explicit owner decision on record for each overlapping claim found. The
implementation is in an isolated worktree, and the primary `main` workspace
holds no uncommitted changes from this session.

## Parallel Git Workflow Protocol

Follow this deterministic protocol for any locked implementation in a
parallel-capable environment. It is the isolation contract on top of §5/§7.

1. **Branch** — create a feature branch from the latest `origin/main` using
   `type/short-desc` (e.g. `feat/custom-words`, `fix/collision-retry`).
2. **Check claims** — run the Steps above: resolve the shared claims file and
   confirm no other branch holds the seams this work will touch.
3. **Worktree** — create a dedicated git worktree for the branch (via
   `using-git-worktrees`). Work only inside it; keep the primary `main`
   workspace clean.
4. **Claim** — when the Contract Lock reaches GATE STATUS: LOCKED, acquire the
   claim: `powershell scripts/claim_seam.ps1 -Command acquire -Branch <branch> -Seams <s1,s2> -RuleIds <r1,r2>`.
   (PowerShell 5.1 comma-arg quirk: call the script with the array args, never a
   naive comma-separated invocation.)
5. **Implement** — do all edits and tests inside the worktree. Never stage or
   commit from the primary workspace.
6. **Validate & commit** — full validation (§6), explicit `git add <files>`,
   Conventional Commits, per §7.
7. **Push & PR** — push the branch and open the PR via
   `gh pr create --fill --base main`, linking resolved issues.
8. **Kilo review loop** — after creating or updating the PR, run this loop:
   a. Poll the review findings **token-efficiently** — never dump full comment
      bodies into the conversation on every poll. Fetch only what changed:
      - Extract a minimal delta with `gh api ... --jq` that emits only
        `id` + a short body hash (or body length) per comment, e.g.
        `gh api repos/Ham3dParsa/HamZaboonRobot/pulls/<n>/comments --jq '.[] | {id, h: (.body|length)}'`.
      - Persist the last-seen set of `id -> body-hash` to a temp file (e.g.
        `$env:TEMP/opencode/kilo_seen_<pr>.json`) between polls.
      - Surface to the conversation **only** the delta: comment IDs that are new,
        or whose body hash changed since the last poll. Do not re-print
        unchanged bodies.
   b. Sleep **120s between polls**, up to a **30-minute overall timeout**, before
      concluding Kilo is done. (The sleeps themselves consume no context tokens;
      only the delta output does.)
   c. Address the findings **one by one**, implementing only those that are
      valid and worthy; do not chase noise.
   d. Push the fixes. Kilo re-reviews **only after a push**, so each fix
      round-trip requires a new commit push.
   e. Repeat steps (a)–(d) until Kilo surfaces **no new suggestions**.
   Review summaries may appear as issue comments (`issues/<n>/comments`), not
   only inline PR comments; check both. Kilo comments do not accept CLI replies
   (`POST pulls/comments/{id}/replies` returns 404) — replying is not required;
   a push is what triggers the re-review. Note: Kilo sometimes **updates an
   existing comment** (same ID, edited body) instead of posting a new one — the
   body-hash delta in step (a) catches this, so compare `id -> body-hash` (not
   just new IDs), and treat an edited body as a new round of findings.
9. **Merge & cleanup** — on owner instruction (or an explicit "merge it"),
   `gh pr merge --squash`, then remove the worktree, delete the local branch,
   and release the claim:
   `powershell scripts/claim_seam.ps1 -Command release -Branch <branch>`.
10. **Sync primary** — bring the primary `main` workspace up to date only when
    it is clean and it is safe to do so; never force or overwrite another
    session's uncommitted files there.

## Related skills

The seam-check (step 3) runs inside the Contract Lock Gate sequence; it does not
restate contract-lock-gate's own steps. See contract-lock-gate for the gate.
