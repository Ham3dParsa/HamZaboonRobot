---
name: plan-console-phase-09-ship
description: T9 commit plus push plus PR plus review loop, no merge (final)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: planned
---

STATE: phase 9 — status: planned — focus: ship to PR, review to APPROVED

## Blocking edges

- Blocked by: ALL phases 01–08 (serial; solo final Wave 6, single worker).
- Blocks: —.

## Scope (exact steps, in order)

1. Full validation per `hamzaban-validation`: `pytest`, `compile_all.py`,
   `ruff F821/F811`, `git diff --check` — all inside the worktree.
2. Independent review gate (`hamzaban-reviewer`): 0 confirmed findings or all
   fixed + re-verified, BEFORE commit.
3. Explicit staging only (`git add <files>` — never `git add .`);
   Conventional Commits; `git diff --staged --check` clean; secrets scan
   (no VALUES: keys/tokens pasted during dev must not appear).
4. Push branch `feat/webui-v5`; `gh pr create --fill --base main` linking
   tracking issue(s); PR body references T1–T8 tickets.
5. Review loop via `oc-merge-loop` (deltas + CI checks) until APPROVED.
6. NO MERGE (owner merges; agent merges only on explicit "merge it").

## Acceptance (verifiable artifacts)

- PR URL (open, unmerged) + green checks + APPROVED review state.
- Worktree/branch retained until owner merges; primary still on `main`.

## Wiring

- No code change in this phase (commit/push/PR mechanics only).
- `<SYSTEM_GATE>` lines (git validation + independent review) live in the
  implementation session, not in these docs.
