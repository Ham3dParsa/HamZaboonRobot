---
name: plan-awaiting-flow-registry-r2
description: Central awaiting text-input flow registry (R2) — deep module handlers/flows.py
created: 2026-08-17
base_commit: 9c822ce
branch: refactor/awaiting-flows
status: in-progress
---

STATE: phase 1/2 DONE, phase 2/2 — validation + independent review complete; commit/PR/merge pending

## Scope (locked contract)
- **R2**: single deep module `handlers/flows.py` owning the awaiting text-input namespace.
  `AwaitingFlow(prefix, handler)` dataclass + `text_router(update, context, awaiting, text)` lookup.
  Removes `_ADMIN_AWAITING_PREFIXES` (admin.py) and all manual `awaiting.split(":")` branches
  in bot.py text_router + admin.py `_handle_admin_text_input`.
- Owner decision (2026-08-17): deep module; remove the bug-source allowlist; no manual prefix
  branches in the text router. (Matches report R2.)
- Seam claim: seams 7 (User Domain), 8 (Admin), 9 (Stats), 10 (Plans), 11 (Cost), 12 (AI Config).

## Design (from report R2 + codebase-design)
`handlers/flows.py`:
- `@dataclass(frozen=True) class AwaitingFlow:` with `prefix: str`, `handler: Callable[[Update, ContextTypes.DEFAULT_TYPE, str, str], AwaitingTask]`.
- `register_flow(prefix, handler)` and `resolve_flow(awaiting: str) -> AwaitingFlow | None`
  (longest-prefix match). Flows registered at import time from each domain module.
- `text_router(update, context, awaiting, text)` — the ONLY entry bot.py calls; it looks up
  the flow and delegates, or handles the terminal `None` awaiting. Hides all `split(":")`.
- `is_admin_awaiting(awaiting)` keeps its signature (bot.py + admin.py still import it) but
  delegates to the registry.

## Phases

### Phase 1 — registry + wiring
- [x] Create `handlers/flows.py` with `AwaitingFlow`, `register_flow`, `resolve_flow`, `text_router`, `is_admin_awaiting`.
- [x] Register every admin awaiting flow — centralized in `handlers/admin.py` `_register_admin_flows()` via small adapters
      (decided over owning-module registration: less churn, one discoverable place, registry still owns routing; wiring
      guard is unaffected because `is_admin_awaiting` delegates to the registry).
- [x] Rewire `bot.py` text_router to call `flows.text_router` (removed `_handle_admin_text_input` import + admin special-case).
- [x] Rewire `handlers/admin.py` `_handle_admin_text_input` → delegates to `flows.text_router` (manual branches removed).

### Phase 2 — validation, review, PR
- [x] Wiring-integrity guard (`tests/test_wiring.py::test_is_admin_awaiting_covers_all_admin_awaiting_keys`) green against registry.
- [x] Updated `tests/test_admin_awaiting.py` to the registry seam (routing-through adapter assertions, Finding #6 regression guards).
- [x] Full validation suite (1083 passed; compile_all 0; ruff F821/F811 clean; git diff --check clean; dashboard regenerated).
- [x] Independent review (`hamzaboon-reviewer`) — no CRITICAL; WARNING (module-change guard) + SUGGESTION 1 (remove dead shim) resolved; docstrings updated.
- [ ] Single commit; PR; Kilo loop; merge.

## Files
- `handlers/flows.py` (new)
- `bot.py` (text_router → flows.text_router)
- `handlers/admin.py` (`_ADMIN_AWAITING_PREFIXES` removed; `_handle_admin_text_input` → flows; `_register_admin_flows()`)
- `tests/test_admin_awaiting.py` (rewritten to registry seam)
- `tests/test_wiring.py` (existing guard now validates the registry)

## Blocked Questions
- (none)