---
name: plan-network-run-ux-phase-02-table
description: LEG_FALLBACKS single table in net.py with call_leg chain walk
created: 2026-09-15
base_commit: 926a19b
branch: TBD (feat/network-fallback-table)
status: merged
---
STATE: phase 4/6 — status: merged — PR 716 squash f6d62d3 (HEAD 927d946, OpenCode APPROVED zero-blocking, 6/6 blocking CI pass, Kilo review in-progress at merge per standing permission)

## Scope
- `LEG_FALLBACKS[(provider, leg)]` in `net.py` with per-entry cost labels; move `JUDGE_MODELS` + precard/avalai/google consts in (legs hold zero lists); `call_leg` walks chain on ROTATE only; ABORT stops+flushes; per-step provider_map + telemetry entries. `tests/test_single_source_of_truth.py` gains `LEG_FALLBACKS` keyword.
- Files: `factory/precard/net.py`, `factory/precard/judge.py`, `factory/precard/topics.py`, `factory/precard/pipeline.py`, `factory/precard/transport.py`, `tests/factory/test_precard_net.py`.

## Rules: R3 (resolution) R5 R6.

## Tests
- Hermetic per leg: 429→next model same leg; 401→STOP, no second call, progress flushed; provider_map records every model tried; cost labels printed by `--list-models`.

## Gates
R5 R6. Paid legs never auto-switch (stop+resume); free legs may switch provider on COOLDOWN_SWITCH.

## Wiring rows
Leg-local model lists → table (remove); legs → `net.call_leg` (update); single-source keyword (update).

## Blocking edges
PR-A (needs CLI/env resolution + entry).

## Acceptance
No leg-local fallback list in grep; injected-429 run reaches model 2; injected-401 run makes zero second calls; full suite green.
