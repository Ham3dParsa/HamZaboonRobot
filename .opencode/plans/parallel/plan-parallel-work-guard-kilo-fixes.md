---
name: parallel-work-guard-kilo-fixes
description: Resolve Kilo review findings against PR #302 under the revised locked contract.
created: 2026-08-10
base_commit: fe8f61b
branch: docs/parallel-work-guard-skill
status: in-progress
---
STATE: phase 1/1 — status: in-progress — focus: update registry location and claim-write safety

## Locked Rules

1. Use a named seam registry, with mutable claims in a shared file resolved
   from the common Git directory: `<git-common-dir>/parallel-work-claims.json`.
2. Exclude settings keys from this PR's claimable resources; create a separate
   follow-up for a canonical settings inventory.
3. Use atomic read-modify-write with duplicate-branch handling and preservation
   of unrelated claims.
4. Treat malformed JSON as a repair-required error; halt claim-guarded work
   only, while unrelated read-only investigation may continue.

## Steps

| Step | Scope | Status | Evidence |
|------|-------|--------|----------|
| 1 | Persist revised contract and inspect PR files | complete | Locked owner choices; PR #302 at `fe8f61b` |
| 2 | Update skill and seam registry | complete | `.opencode/skills/parallel-work-guard/SKILL.md`, `SEAMS.md` |
| 3 | Update AGENTS/contract-lock references and remove tracked mutable seed | complete | `AGENTS.md`, `.opencode/skills/contract-lock-gate/SKILL.md`, deleted `.opencode/state/claims.json` |
| 4 | Create settings follow-up issue | complete | GitHub issue #303 |
| 5 | Validate, commit, push, and monitor PR | in-progress | `git diff --check`, path review, commit SHA, `gh pr checks` |

## Deliberately Not Done

- No application Python code changes.
- No settings-key inventory in this PR.
- No new subagent.
- No Git merge or PR merge.

## Blocked Questions

None. Owner selected all four corrective decisions and authorized execution.
