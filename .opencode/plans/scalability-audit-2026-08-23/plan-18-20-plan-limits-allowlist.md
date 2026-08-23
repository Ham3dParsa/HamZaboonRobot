STATE: LOCKED — branch refactor/plan-limits-allowlist worktree .worktrees/a-02

# Plan 18-20 — plan-limits + allowlist single-source (Session A follow-up)

**Tickets:** #18 plan-limits-dup, #20 allowlist-dup (+ bounded #22 utils-impure) — from `TICKETS.md` Session=A (#17-22,23,24,27,31) subset unblocked after #17 merged via #461.
**Seam:** `config/plan_identity.py`, `services/db/plans.py`, `services/routing.py`, `bot.py` (`Persistence` #1 + `Telegram UI` + `config` shared registry) — claimed 2026-08-23 `refactor/plan-limits-allowlist` R1-R3.
**Worktree:** `.worktrees/a-02` branch `refactor/plan-limits-allowlist` from `origin/main` @01b62c6
**Depends:** #17 done (#461), Q claims (#3,7,8,26) on different tables — no overlap.

## CONTRACT LOCK TEMPLATE

Rule R1 — Plan limits single source:
Decision: Keep split (identity vs limits) but enforce at import
Option Chosen: A — harden import-time `valid_plans() == set(_PLAN_LIMITS)` + `DEFAULT_PLANS` derived via `plan_label()` + `validate_plan_consistency()` tested
Alternatives Rejected: B merge into one file — couples config↔DB, widens interface
Trade-offs: cost 0, zero compat, fail-loud on drift
Owner Confirmation: ALL A. to tickets now. (2026-08-23)
GATE STATUS: LOCKED

Rule R2 — Allowlist derive:
Decision: Derive allowlist from routing registry
Option Chosen: A — delete hardcoded tuple in bot.py, use `services/routing.ROUTES` longest-prefix dispatch + `tests/test_wiring` validates keyboards literals ⊆ ROUTES
Alternatives Rejected: B keep tuple + guard test — detects late, still 2 lists
Trade-offs: fix once, no compat, wiring intent single source
Owner Confirmation: ALL A (2026-08-23)
GATE STATUS: LOCKED

Rule R3 — Bounded utils impurity:
Decision: Defer unless file touched
Option Chosen: A — move domain helper only if R1/R2 touches the file, else defer to future #22 PR
Alternatives Rejected: B force move now — widens PR beyond bounded allowance
Trade-offs: minimal diff, AGENTS.md § bounded cleanup satisfied
Owner Confirmation: ALL A (2026-08-23)
GATE STATUS: LOCKED

GATE STATUS: LOCKED (all rules)

## Dependency & Wiring Map

| Dependency type | Items affected | Disposition |
|---|---|---|
| Callback prefixes | `admin:`, `llm:` already routed via routing; allowlist derived from ROUTES | update bot.py, keep ROUTES |
| Router branches | `bot.py:allowlist` tuple | remove, delegate to `services/routing.dispatch` |
| Keyboard builders | `config/keyboards.py` literals | keep, validated by wiring test |
| DB tables/columns | `plans` `_PLAN_LIMITS` / `valid_plans` | keep split, add validation |
| Handler functions | none new | — |
| Imports/re-exports | `services/db/plans.py` imports `plan_label` | keep |
| Tests | `tests/test_wiring.py`, `tests/test_single_source_of_truth.py` | update/add `validate_plan_consistency` |
| Docs | `SEAMS.md`, `AGENTS.md §3` | update if needed |

## Execution (TDD, claims each commit, rebase before PR)

1. TDD red: test that `valid_plans` drift fails, test that allowlist == ROUTES keys
2. Implement R1 validation, R2 derive, green tests
3. `compile_all.py` + `ruff F821/F811` + `pytest -n 14` + `git diff --check`
4. commit + `claim_seam.ps1 acquire` timestamp, push `gh pr create --fill`
5. Kilo loop, rebase before merge, release claim

## Tickets trace

- TICKETS.md #18, #20 → this plan; #22 bounded — defer if not touched
