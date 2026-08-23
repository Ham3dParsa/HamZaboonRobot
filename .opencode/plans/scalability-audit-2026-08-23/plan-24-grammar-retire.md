STATE: phase 1/1 — in-progress — focus: implemented b816655 retired stub + archive awaiting CI/Kilo

Evidence: commit b816655 handlers/user.py stub + docs/archive/retired/grammar_tip_2026-08-23.md; tests: pytest 40 passed 2026-08-23; ruff clean

# Plan 24 — O-grammar-standalone retire (Session A quick win)

**Ticket:** #24 `O-grammar-standalone` — `send_grammar_tip` dead handler, table `grammar_tips` exists but no UI. Decision: **Retire** (export logic, disable in prod) — owner 2026-08-23.
**Seam:** `handlers/user.py`, `services/db/__init__.py:grammar_tips`, `services/ai/prompts.py:grammar_tip_system_prompt` — claimed R24.
**Worktree:** `.worktrees/a-03` branch `chore/retire-grammar-tip` from f821f3d
**Depends:** none — standalone, no Q/S/P block.

## CONTRACT LOCK TEMPLATE

Rule R1 — Retire vs Wire:
Decision: Retire (export) — keep DB table/columns for future, disable handler in prod
Option Chosen: B — Retire (owner: "export it's logic for now as retired code")
Alternatives Rejected: A Wire — would add BTN + quota + 15 lines, not wanted now
Trade-offs: cost 0, no AI quota burn, table stays but idle; logic archived to `docs/archive/retired/grammar_tip_2026-08-23.md`
Owner Confirmation: "export it's logic for now as retired code. i might work on it later." (2026-08-23)
GATE STATUS: LOCKED

GATE STATUS: LOCKED

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Handler | `handlers/user.py:send_grammar_tip` | move body to `docs/archive/retired/grammar_tip_2026-08-23.md`, stub returns retired msg |
| DB | `services/db/__init__.py:add_grammar_tip`, `recent_grammar_tip_titles`, `services/db/schema.py:grammar_tips` | keep table/columns (no migration), keep functions for future, no calls in prod |
| Quota UI | `handlers/user.py:_grammar_tip_usage_text` + quota line | hide grammar line from status, keep helper for archive |
| Prompts | `services/ai/prompts.py:grammar_tip_system_prompt` | keep (no call) |
| Tests | none — feature was dead, no coverage to update | — |

## Execution
1. Export handler body to archive
2. Stub handler + hide quota line, keep DB intact
3. `pytest -q` + `ruff` + `git diff --check`
4. claim timestamp each commit, push PR
