---
name: git-protocol
description: Enforce AGENTS.md §7 Git and Security Discipline — commit rules (Conventional Commits, explicit staging, no amend, no destructive git), branch naming, PR creation/merge via gh CLI, security/bounds, PowerShell backtick safety, subagent non-ASCII sanitization, and the Error Recovery Protocol. Load before proposing, running, or reviewing any git/gh command.
license: MIT
compatibility: opencode
metadata:
  category: workflow
  gate: git-operation
author: Ham3dParsa
author_url: https://github.com/Ham3dParsa
---
# Git Protocol Skill (AGENTS.md §7)

## When to load
- Before running ANY git command (commit, branch, rebase, reset, push, merge)
- Before creating or reviewing a PR via `gh`
- When a commit is proposed, staged, or created
- On validation/test/CI failure that needs the Error Recovery Protocol

## Commit Rules
- **Single logical commit per PR** — one coherent change (feature, fix, docs, refactor, test, chore).
- **Conventional Commits**: `type(scope): subject`
  - Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`
  - Scope: module/subsystem (e.g., `bot`, `db`, `ai`, `catalog`, `scheduling`)
  - Subject: imperative, lowercase, no trailing period
  - Example: `fix(bot): handle collision retry on network error`
- **Explicit staging only**: `git add file1.py file2.py` — never `git add .` or `git add -A`.
- **No commit amending** — add corrective commit if needed.
- **No destructive Git commands**: `reset --hard`, `clean -fd`, force-push protected branches.
- **Never skip hooks** unless owner explicitly requests.

## Branch & PR Rules
- **Branch naming**: `type/short-desc` (e.g., `feat/custom-words`, `fix/collision-retry`, `docs/git-workflow`).
- **Branch creation**: after validation passes, not before implementation.
- **PR creation**: `gh pr create --fill --base main` — owner reviews on GitHub UI.
  If the PR resolves tracked issues, link them in the body (e.g., "Resolves #N").
  If `gh` is unavailable, provide the GitHub PR creation URL as a fallback.
- **CI monitoring**: after PR push, load the `kilo-ci-loop` skill for `gh pr checks` + Kilo delta polling (do not re-implement the loop here).
- **Agent-initiated merge**: only on explicit owner instruction ("merge it" or equivalent).
  MUST run `gh pr checks` and confirm all required checks pass before `gh pr merge --squash` (see `kilo-ci-loop` for conflict rebase handling when `mergeable` is `CONFLICTING`).
- **Merge method**: **Squash and merge** (single commit on `main`).
- **Post-merge cleanup**: `git checkout main && git pull && git branch -d branch-name`.
- **Local merge fallback only**: with explicit owner instruction `git checkout main && git pull && git merge --ff-only branch-name`.
- **Remote branch deletion**: owner may delete via GitHub UI after merge.

## GitHub CLI — Allowed Operations
The agent may use `gh` only for:
- **PRs**: `gh pr create --fill --base main`, `gh pr checks`, `gh pr merge --squash` (explicit owner instruction only), `gh pr view`
- **Issues (read-only only)**: `gh issue list [--label <label>] [--state <state>]`, `gh issue view <N>`
- Commands outside this list require explicit prior approval.

## Security, Bounds & Shell Safety
- MUST NOT expose the `gh` auth token in logs, commits, or PR descriptions.
- MUST NOT close, reopen, or create GitHub Issues ad hoc (governed by AGENTS.md §2).
- MUST NOT merge a PR with failing CI checks.
- **PowerShell String & Backtick Safety:** When passing formatted text (PR descriptions, multi-line strings, markdown with backticks) to CLI tools (`gh pr create`, `gh pr edit`), NEVER pass inline double-quoted strings in PowerShell (backticks are escape characters, e.g. `` `t `` becomes a tab).
  - **MUST write the Markdown to a temp file using the file write tool** (not PowerShell `Set-Content`/`Out-File`), then pass `--body-file <path>`.
  - **Why:** even a double-quoted here-string (`@"..."@`) still interprets backticks as escape sequences, so `` `audit-workflow` `` becomes BEL (0x07) + `udit-workflow` (shows as `^Gudit-workflow`), and PS 5.1 `Set-Content -Encoding UTF8` prepends a UTF-8 BOM. Both corrupt the GitHub body.
  - **Verify before sending:** re-read the temp file and confirm no BOM (first byte must not be `239`/`EF`), no control characters (0x07/BEL), and all intended backticks/asterisks are intact.
- **Subagent Non-ASCII Output Sanitization:** When synthesizing report documents from subagent outputs containing Persian or non-ASCII text, verify Unicode integrity before saving. If encoding artifacts/corrupted tokens occur, perform an atomic full-file update via the file writing tool rather than incremental `edit` over invisible control characters (such as ZWNJs).

## Security Rules
- Do not commit `.env`, credentials, tokens, API keys, or generated secrets.
- Do not expose `gh` auth tokens or session credentials in code, logs, tests, commits, issue evidence, or PR descriptions.
- Prefer established dependencies and standard-library solutions.
- Treat database migrations as production code: preserve existing data, handle old schemas, test both fresh and upgraded databases.

## Error Recovery Protocol (AGENTS.md §7)
If validation fails (tests, `git diff --check`, or other checks), do NOT immediately ask for help:
1. **Analyze** the stack trace or diff output to identify the root cause.
2. **Attempt a fix** targeting the specific failure.
3. **Retry** the full validation suite.
4. Only after **2 consecutive failed attempts** should the agent reset state (e.g., `git reset HEAD~1` or discard staged changes), report the exact error and context, and halt for human input.

## Gate Integration
- Pre-commit checklist (validation suite, secret scan, SYSTEM_GATE keyword) lives in the `pre-commit-gate` skill.
- Full validation commands live in the `hamzaban-validation` skill.
- The `<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>` keyword is enforced by AGENTS.md §7.