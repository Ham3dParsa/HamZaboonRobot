---
name: kilo-ci-loop
description: Poll Kilo + OpenCode reviews and CI checks after PR push — delta fetch for new/edited comments from both bots, gh pr checks status, and merge-conflict rebase. Load after gh pr create/push or before gh pr merge.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: post-pr
  author: Ham3dParsa
  author_url: https://github.com/Ham3dParsa
---
# Kilo + OpenCode — CI Loop

Tight loop that turns a pushed PR into `MERGEABLE` without re-printing unchanged reviewer bodies. Handles **both** `kilo-code-bot[bot]` and `opencode-agent[bot]`.

## When to load
- After `gh pr create`/`git push` on a PR
- Before `gh pr merge --squash` (verify `gh pr checks` pass)
- When `mergeable == CONFLICTING`

## Steps

### 1. Poll reviewer delta — tight, token-tight (Kilo + OpenCode)

```powershell
gh api repos/Ham3dParsa/HamZaboonRobot/pulls/<n>/comments --jq '.[] | select(.user.login=="kilo-code-bot[bot]" or .user.login=="opencode-agent[bot]") | {id, h:(.body|length), user:.user.login, path, line}'
gh api repos/Ham3dParsa/HamZaboonRobot/issues/<n>/comments --jq '.[] | select(.user.login=="kilo-code-bot[bot]" or .user.login=="opencode-agent[bot]") | {id, h:(.body|length), user:.user.login}'
```
Persist `id->h` to `$env:TEMP/opencode/reviewer_seen_<n>.json` (fallback: also check legacy `kilo_seen_<n>.json` on first load, then migrate); surface only new `id` or changed `h`; fetch full body **only** for deltas:
```powershell
gh api repos/Ham3dParsa/HamZaboonRobot/pulls/comments/<id> --jq '.body'
gh api repos/Ham3dParsa/HamZaboonRobot/issues/comments/<id> --jq '.body'
```
Filter `jq` to reviewer bots only, check `$LASTEXITCODE` after each `gh api` (on non-zero return `apiFailed` and skip `seen` update to avoid clobbering baseline), wrap `ConvertFrom-Json` with `$line=$_; try{...}catch{return}` (use `return` not `continue` inside `ForEach-Object`). Migrate legacy `kilo_seen_<PR>.json` to `reviewer_seen_<PR>.json` on first fallback hit. Tag each delta by `user`. Sleep `90-120s` (default 90, clamped), `30m` timeout. Each fix commit must be pushed — both reviewers re-review only after push.

### 2. Poll CI
```powershell
gh pr checks <n>
```
Require `label` `test (3.10)` `test (3.13)` `ram-gate` `Kilo Code Review` `review` (opencode-review) = `pass` — match anchored `(?m)^\s*<name>\b\s+pass` with `\b` to avoid `review` matching `review-docs` or `Kilo Code Review` substring (see `scripts/kilo_ci_loop.ps1:Test-Checks` + `Test-Mergeable`; both wrapped in `try/catch` to allow retry on transient `gh` failure). On `fail`, `gh run view <run> --log-failed`, fix before re-poll. Do not merge with blocking failures.

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
Delta-optimal (`id->h` + full body only for deltas, per-bot tagged), `90-120s/30m`, CI + `mergeable` + rebase verify. Manual steps remain authoritative if script not used.

## Triage — every finding evaluated, not ignored

Both reviewers use comparable severities — map unified:

- **Kilo** `CRITICAL` / **OpenCode** `[critical]` + `REQUEST_CHANGES` → blocking, must fix before merge.
- **Kilo** `WARNING` / **OpenCode** `[warning]` → blocking, must fix before merge.
- **Kilo** `SUGGESTION` / **OpenCode** `[info]`/`[suggestion]` → assess value first. **Fix now** if good and (a) CI-blocking, (b) in-scope and trivial ≤5 lines, or (c) clearly improves correctness/readability with no new risk. **Defer** only if valid but not mandatory: out-of-seam, needs its own contract lock, or low leverage vs. PR scope — create follow-up ticket, link as `Deferred: <reason> → #<follow-up>`, note `Kilo/OpenCode: SUGGESTION deferred (evaluated)`. **Noise** only for false-positive/out-of-scope with one-line justification. Never silently ignore.
- Merge-ready when every `CRITICAL`/`[critical]`/`WARNING`/`[warning]` fixed, every `SUGGESTION`/`[info]` evaluated and either fixed or deferred/noised with link+reason, blocking checks `pass`, `mergeable == MERGEABLE`.

## Completion

Every delta (Kilo + OpenCode) fetched once and fixed or triaged, blocking checks `pass` (including both `Kilo Code Review` and `review`), `mergeable == MERGEABLE`. Evidence: `gh pr checks` + triage note per reviewer.
