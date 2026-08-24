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
# Kilo-CI Loop

Tight loop that turns a pushed PR into `MERGEABLE` without re-printing unchanged Kilo bodies.

## When to load
- After `gh pr create`/`git push` on a PR
- Before `gh pr merge --squash` (verify `gh pr checks` pass)
- When `mergeable == CONFLICTING`

## Steps

### 1. Poll Kilo delta — tight, token-tight
```powershell
gh api repos/Ham3dParsa/HamZaboonRobot/pulls/<n>/comments --jq '.[] | {id, h:(.body|length), path, line}'
gh api repos/Ham3dParsa/HamZaboonRobot/issues/<n>/comments --jq '.[] | {id, h:(.body|length)}'
```
Persist `id->h` to `$env:TEMP/opencode/kilo_seen_<n>.json`; surface only new `id` or changed `h`; fetch full body only for deltas:
```powershell
gh api repos/Ham3dParsa/HamZaboonRobot/pulls/comments/<id> --jq '.body'
gh api repos/Ham3dParsa/HamZaboonRobot/issues/comments/<id> --jq '.body'
```
Sleep `90-120s` (default 90, clamped), `30m` timeout. Each fix commit must be pushed — Kilo re-reviews only after push.

### 2. Poll CI
```powershell
gh pr checks <n>
```
Require `label` `test (3.10)` `test (3.13)` `ram-gate` `Kilo Code Review` = `pass`. On `fail`, `gh run view <run> --log-failed`, fix before re-poll. Do not merge with blocking failures.

### 3. Handle conflict
If `CONFLICTING`:
```powershell
git fetch origin; git rebase origin/main
```
Keep both seams when branches touched different seams. Verify `python scripts/compile_all.py` + `git diff --check`; broken indent is common failure. Continue `GIT_EDITOR=true git rebase --continue`; push `--force-with-lease`.

## Automation

Prefer `scripts/kilo_ci_loop.ps1` — implements this skill exactly:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/kilo_ci_loop.ps1 -PR <n> [-SleepSeconds 90] [-TimeoutMinutes 30]
```
Delta-optimal (`id->h` + full body only for deltas), `90-120s/30m`, CI + `mergeable` + rebase verify. Manual steps remain authoritative if script not used.

## Triage — SUGGESTION evaluated, not ignored

Kilo `SUGGESTION`s are often good — do not blanket-ignore. Evaluate each delta:

- `CRITICAL`/`WARNING` → blocking, must fix before merge.
- `SUGGESTION` → assess value first. **Fix now** if good and (a) CI-blocking, (b) in-scope and trivial ≤5 lines, or (c) clearly improves correctness/readability with no new risk. **Defer** only if valid but not mandatory: out-of-seam, needs its own contract lock, or low leverage vs. PR scope — create follow-up ticket, link as `Deferred: <reason> → #<follow-up>`, note `Kilo: SUGGESTION deferred (evaluated)`. **Noise** only for false-positive/out-of-scope with one-line justification. Never silently ignore.
- Merge-ready when every `CRITICAL`/`WARNING` fixed, every `SUGGESTION` evaluated and either fixed or deferred/noised with link+reason, blocking checks `pass`, `mergeable == MERGEABLE`.

## Completion

Every delta fetched once and fixed or triaged, blocking checks `pass`, `mergeable == MERGEABLE`. Evidence: `gh pr checks` + triage note.
