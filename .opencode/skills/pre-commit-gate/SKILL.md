---
name: pre-commit-gate
description: Enforce AGENTS.md §7 Mandatory Pre-Commit Validation Gate — run full validation suite, check git diff --staged --check, scan for secrets/credentials/tokens/API keys in staged changes, verify Conventional Commits format, verify branch naming convention, verify explicit staging only (no git add .), verify <SYSTEM_GATE> keyword present. Load before committing.
license: MIT
compatibility: opencode
metadata:
  category: validation
  gate: pre-commit
---
# Pre-Commit Gate Skill

## When to load
- Immediately before creating any commit
- When user says "commit" or "stage and commit"

## Gate Checklist (AGENTS.md §7)

1. **Full validation suite** — run `hamzaban-validation` skill
2. **Whitespace check** — `git diff --check` AND `git diff --staged --check` — both must be clean
3. **Secret scan** — scan staged files for patterns:
   - API keys: `sk-[a-zA-Z0-9]{32,}`, `sk_live_[a-zA-Z0-9]{24,}`, `ghp_[a-zA-Z0-9]{36}`, `AIza[a-zA-Z0-9_-]{35}`
   - `.env` content, bot tokens, database passwords
   - `.venv/`, `venv/`, `*.db` files
4. **Single logical commit** — Conventional Commits format: `type(scope): subject`
   - Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`
   - Scope: module/subsystem (e.g., `bot`, `db`, `ai`, `catalog`, `scheduling`)
   - Subject: imperative, lowercase, no trailing period
   - Example: `fix(bot): handle collision retry on network error`
5. **Explicit staging only** — verify `git add file1.py file2.py` was used, NOT `git add .` or `git add -A` (check staging area contents)
6. **Branch naming** — verify `type/short-desc` convention: `feat|fix|docs|refactor|test|chore` + short desc
7. **SYSTEM_GATE keyword** — verify `<SYSTEM_GATE> Git validation required before commit </SYSTEM_GATE>` present in agent response before commit

## Behavior
- Run all checks in sequence
- Return consolidated GATE VERDICT: PASS or FAIL with specific failed criteria
- On FAIL: do NOT commit; report exactly what failed with actionable fix

## Notes
- Secret detection is regex-based; false positives possible — user must review
- `.gitignore` already excludes `.env`, `*.db`, `venv/`, `.venv/` — but scan staged anyway
- CI runs same validation; local gate prevents CI failures