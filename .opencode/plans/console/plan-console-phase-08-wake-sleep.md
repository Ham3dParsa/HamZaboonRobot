---
name: plan-console-phase-08-wake-sleep
description: T7 wake-on-demand gate plus idle sleep plus state buttons (P1)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: planned
---

STATE: phase 8 — status: done — 3/3 ticket tests green (fakes only), 83/83 console suites green, diff-check clean; live proof on port 5571: wake→503 friendly wait line (names-only), sleep→parked refusal, supervisor card screenshot read PASS (wake+sleep buttons + lifecycle badge wired); stopped pid-only (port closed); IDLE_SLEEP_MINUTES still parked (owner minutes pending — nothing invented).

## Blocking edges

- Blocked by: phase-01-bind, phase-07-candidates-join (serial; solo Wave 5,
  exclusive: touches `server.py` wake region AND `index.html` state buttons).
- Blocks: phase-09-ship.

## Scope (exact files)

- `factory/webui/server.py` (wake region ONLY: `_ensure_supervisor_for_leased`,
  `_wake_supervisor_background`, lease path): gate TRULY closes the loop
  (no-token → background wake → retry → friendly wait line, never raw error);
  idle sleep after a named constant `IDLE_SLEEP_MINUTES` — value PARKED
  (owner number pending; never invented); `/api/supervisor/wake` +
  `/api/supervisor/sleep` endpoints (names + booleans out).
- `factory/webui/index.html`: state surface with wake + sleep buttons + status
  badge wired to the endpoints.
- Tests: extend host-port-adjacent or new
  `tests/factory/test_factory_webui_wake_sleep.py` (one place).

## Test-first tests (names)

- `test_wake_gate_closes_loop` (fake `wake_fn`/`health_fn`: no token → wake → retry → wait line)
- `test_wake_sleep_buttons_wired` (endpoints + button ids present)
- `test_idle_sleep_uses_owner_minutes` (idle path honors injected minutes;
  shipped default == parked constant, asserted — not a real duration)

## Acceptance (verifiable artifacts)

- Named tests green (fakes only — never a real process/network).
- Panel shows supervisor state + working wake/sleep buttons; idle-minutes
  question still open in plan §6 until owner answers.

## Wiring

- Rule: locked lifecycle rules. Token names-only (`EGRESS_SUP_TOKEN`).
