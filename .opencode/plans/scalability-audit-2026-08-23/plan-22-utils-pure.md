STATE: LOCKED — branch refactor/utils-pure worktree .worktrees/a-04

# Plan 22 — utils-impure pure utils (Session A)

**Ticket:** #22 `utils-impure` — `services/utils/formatting.py` and `helpers.py` contain business logic (quota text, prompt helpers) that belongs in domain modules. Decision: **Move quota/prompt to domain** (owner 2026-08-23).
**Seam:** `services/utils/*` → `services/scheduling.py`, `services/ai/prompts.py` — claimed R22.
**Worktree:** `.worktrees/a-04` branch `refactor/utils-pure` from 870fd7e
**Depends:** none — standalone, Q/S/P complete, A-24 done.

## CONTRACT LOCK TEMPLATE

Rule R1 — Move quota/prompt to domain:
Decision: Move quota_text from formatting to scheduling, prompt helper to services/ai/prompts; utils stays pure helpers only
Option Chosen: A — Move (recommended, owner: Move quota/prompt to domain)
Alternatives Rejected: B Keep utils as is — leaves impurity, violates AGENTS.md §3 (no business logic in utils)
Trade-offs: bounded move only in touched files, utils becomes domain-agnostic, no quota/AI behavior change
Owner Confirmation: Move quota/prompt to domain (Recommended) (2026-08-23)
GATE STATUS: LOCKED

GATE STATUS: LOCKED

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| utils formatting | `services/utils/formatting.py:quota_text`, prompt helpers | move to `services/scheduling.py` / `services/ai/prompts.py` |
| helpers | `services/utils/helpers.py:quota helpers` if any | keep retry/cancel only, move domain parts |
| Callers | `handlers/user.py`, `bot.py` quota rendering | update import to domain |
| Tests | `tests/test_*` formatting helpers | update import path, keep behavior |

## Execution
1. Identify domain logic in utils (grep business terms)
2. Move to domain with re-export shim if needed for compat (one PR)
3. pytest + ruff + diff-check
4. claim timestamp each commit, push PR, Kilo loop
