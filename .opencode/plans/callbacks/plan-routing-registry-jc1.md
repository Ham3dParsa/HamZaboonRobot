---
name: plan-routing-registry-jc1
description: Central callback routing registry (R1) + B1 double-notify fix for admin/llm domains (J-C1)
created: 2026-08-16
base_commit: 542ffa8de1dee2645b81b5cb8853330d21f6404d
branch: refactor/callback-router
status: in-progress
---

STATE: phase 2/2 — status: complete — focus: validated (1047 tests), independent review clean, docs updated, ready for PR

## Scope (locked contract)
- **R1**: create `services/routing.py` (registry `ROUTES` + `dispatch()`), register the `admin` and `llm` domains as coarse routes, route them from `bot.py callback_router` through `dispatch()`.
- **B1**: remove the redundant bare ack for `admin:`/`llm:` (old `bot.py` allowlist empty ack); every admin/llm callback must be answered **exactly once**.
- **Owner decision (2026-08-16)**: COARSE flattening — keep the admin sub-router if/elif chains intact; only register the 5 sub-routers + infra leaves at coarse granularity. No full leaf flattening of `admin_ai.py` (74 elifs).
- **Seam claim**: `Telegram UI -> Admin` (8), `Telegram UI -> Stats` (9), `Telegram UI -> Plans` (10), `Telegram UI -> Cost` (11), `Telegram UI -> AI Config` (12). NOT touched: seam 7 (user.py), seam 16 (help), seam 17 (word_query).

## Phase 1 — Registry + wiring
- [x] Create `services/routing.py` with `ROUTES`, `register()`, `dispatch()` (longest-prefix match, owner gate, single-answer guarantee, unknown handled once).
- [x] Register coarse `admin` + `llm` routes in `handlers/admin.py` (`register_admin_routes()`, `_route_llm` adapter).
- [x] Route `admin:`/`llm:` through `dispatch` in `bot.py callback_router`; remove old elif branches and empty ack.
 - [x] **Single-answer guarantee (DEVIATION from plan's "per-branch bare acks"):** implemented centrally in `dispatch` via a local `query.answer` wrapper (`_invoke_and_ensure_answered`) instead of editing ~60 leaf branches. This is the report's "single answer exactly once in dispatch" design; it guarantees exactly one `answer_callback_query` per callback for matched routes without touching the shared `notify_callback` seam or every sub-router branch (lower risk, fewer diffs). The `bot.py` line-610 empty ack is preserved for `lang:`/`goal:`/`level:` (seam 7 untouched).
- [x] Update `tests/test_wiring.py` to recognize registry-registered prefixes as routed (`_collect_registry_prefixes`).
- [x] Add B1 catching integration test (`tests/test_integration/test_admin_single_answer.py`).

## Phase 2 — Validation, review, PR
- [ ] Full validation suite (pytest -n 14, compile_all, ruff F821/F811, dashboard, diff --check).
- [ ] Independent review (`hamzaboon-reviewer`), fix findings.
- [ ] Update AGENTS.md §3 + SEAMS.md, docs per documentation-protocol.
- [ ] Single conventional commit; `gh pr create --fill --base main` (no merge).

## Files
- `services/routing.py` (new)
- `bot.py` (callback_router admin/llm dispatch)
- `handlers/admin.py` (registration + infra branch answers)
- `handlers/admin_stats.py`, `admin_cost.py`, `admin_plans.py`, `admin_ai.py` (per-branch answers)
- `tests/test_wiring.py`, `tests/test_integration/test_admin_single_answer.py` (new)

## Blocked Questions
- [2026-08-16] Admin flattening depth? Owner chose: **Coarse** (keep sub-router elifs; register 5 sub-routers + infra at coarse granularity). Alternatives rejected: Full leaf flattening (too large/risky), Hybrid (medium).