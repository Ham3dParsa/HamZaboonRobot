---
name: kilo-ci-loop
description: Poll Kilo review and CI checks after PR push — delta fetch for new/edited Kilo comments, gh pr checks status, and merge-conflict rebase. Load after gh pr create/push or before gh pr merge.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: post-pr
  author: Ham3dParsa
  author_url: https://github.com/Ham3dParsa
---
# Kilo-CI Loop Skill

Loop that turns a pushed PR into a merge-ready one without re-printing unchanged review bodies.

## When to load
- After `gh pr create` or `git push` on a PR branch
- Before `gh pr merge --squash` (must confirm `gh pr checks` pass)
- When `gh pr view --json mergeable` is `CONFLICTING`

## Steps

### 1. Poll Kilo delta (token-tight)
Fetch only `id` + body length (cheap proxy for hash), never full bodies on every poll:
```powershell
gh api repos/Ham3dParsa/HamZaboonRobot/pulls/<n>/comments --jq '.[] | {id, h:(.body|length), path, line}'
gh api repos/Ham3dParsa/HamZaboonRobot/issues/<n>/comments --jq '.[] | {id, h:(.body|length)}'
```
Persist `id -> h` to `$env:TEMP/opencode/kilo_seen_<n>.json` between polls. Surface only deltas: new `id` or same `id` with changed `h` (Kilo edits in place; equal-length edits keep same `h` and would be missed — use a checksum like `sha256` if strict). Fetch full body only for deltas:
```powershell
gh api repos/Ham3dParsa/HamZaboonRobot/pulls/comments/<id> --jq '.body'
gh api repos/Ham3dParsa/HamZaboonRobot/issues/comments/<id> --jq '.body'
```
Sleep 90-120s between polls, 30m overall timeout. Each fix commit must be pushed — Kilo re-reviews only after a push.

### 2. Poll CI checks
```powershell
gh pr checks <n>
```
Requires: `label` pass, `test (3.10)` pass, `test (3.13)` pass, `ram-gate` pass, `Kilo Code Review` pass. On `fail`, fetch failed job log (`gh run view <run> --log-failed`) and fix before re-polling. Do not merge with failing checks.

### 3. Handle merge conflict
If `gh pr view <n> --json mergeable` is `CONFLICTING`:
```powershell
git fetch origin; git rebase origin/main
```
Resolve each conflicted file keeping both sides when the branches touched different seams (e.g., `admin_cost.py` mark_awaiting_consumed + ai_read_cache). Verify with `python scripts/compile_all.py` and `git diff --check`; a broken indent is the common rebase failure. Continue with `GIT_EDITOR=true git rebase --continue` (PowerShell editor hang). Push with `--force-with-lease`.

## Automation

Prefer the reusable script that implements this skill exactly (do not hand-roll polls):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/kilo_ci_loop.ps1 -PR <n> [-SleepSeconds 90] [-TimeoutMinutes 30]
```

- `scripts/kilo_ci_loop.ps1` — delta-optimal (`id->h` in `$env:TEMP/opencode/kilo_seen_<n>.json`, full body only for deltas), `Sleep 90-120s` (default 90, clamped), `Timeout 30m`, CI + `mergeable` handling with `git fetch`/`rebase` verify (`compile_all.py` + `diff --check`) and `--force-with-lease`. Each fix commit must be pushed — Kilo re-reviews only after push. Handles PR creation, conflict/rebase, CI and Kilo findings end-to-end until merge-ready and post-merge.

Manual steps below remain authoritative if the script is not used.

## Completion criterion
Every Kilo comment delta has been fetched once and either fixed or triaged as noise, every required check is `pass`, and `mergeable` is `MERGEABLE`. `gh pr checks` output is the evidence.
