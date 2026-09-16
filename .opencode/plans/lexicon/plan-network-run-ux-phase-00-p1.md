---
name: plan-network-run-ux-phase-00-p1
description: P1 whitelist move (probe/choose/retire/never-overwrite-empty into net home)
created: 2026-09-15
base_commit: 926a19b
branch: TBD (fix/network-p1)
status: locked
---
STATE: phase 1/6 — status: complete — focus: merged c540d07 (PR 710); reviewer 0 findings; 2841 passed

## Scope
- Move 4 probe functions into `factory/precard/net.py`; supervisor CLI calls them (no logic rewrite); `egress_pool.json` single writer; per-provider cooldown (429 on one provider never cools another).
- Files: `tools/egress/supervisor.py`, `factory/precard/net.py`, `tests/factory/test_precard_net.py`, `factory/README.md`, `tools/egress/README.md`.

## Rules: locked P1 ticket (TICKETS-network-home.md P1) + R4 health hook (supervisor reports healthy/unhealthy for later auto-spawn).

## Tests
- Hermetic: top-N rank, google-first ping order, separate cooldowns, never-write-empty (empty probe clobbers nothing), fake clock/servers. Real probes never run in tests (manual once).

## Gates
R4-health only. No behavior change on identical SUBs (one manual before/after compare).

## Wiring rows
supervisor `--probe-zen/--probe-google` → home fns (update); pool writer single (update); docs READMEs (update).

## Blocking edges
None. Parallel-safe with phase-05 (disjoint files).

## Acceptance
Supervisor holds zero probe logic; empty-probe test green; full suite green.
