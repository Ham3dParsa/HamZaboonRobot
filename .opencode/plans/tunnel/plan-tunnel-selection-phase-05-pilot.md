---
name: plan-tunnel-selection-phase-05-pilot
description: T7 pilot migration, direct urllib calls route through seam
created: 2026-09-22
base_commit: e4f7468
branch: feat/linker-judge-webui
status: draft
---

STATE: phase 5/6 — status: T7 implemented (2026-09-22, no commit) — call_responses is a thin select/prove/remember caller over provider "zen" (key NAME only; HTTPError control-flow re-raises, judging/content untouched) + _pilot_post_once leaf holds the only urlopen; old inline urllib path deleted same ticket; migration tests 5 passed + 1 gated-live skipped; earlier suites still green (trio + probes/linker/precard-migration + card_pilot/blind50: 169 passed + 5 skipped); full suite 3741 passed + 1 flaky offloop timing fail that passes on rerun and touches no pilot files; compile_all EXIT 0; ruff F821/F811 clean on touched files; git diff --check clean; blind50 untouched (optional scope, parked)

# Phase 05 — Pilot migration (T7, P2, serial after T6)

- **Blocking edges:** Phase 04 (T6 green — precard caller behavior stable first).
- **Scope:** `factory/pipeline/card_pilot.py` (+ optional `factory/pipeline/blind50.py`) — direct `urllib` provider calls route through `select`/`prove`/`remember`; judging/content logic untouched (FORBIDDEN). `factory/net/tunnel_selection.py` unchanged (no interface drift allowed at this stage).
- **Tests (test-first):** NEW `tests/factory/test_tunnel_selection_pilot_migration.py` — `test_pilot_provider_calls_cross_seam`, `test_pilot_judging_logic_unchanged` (content verdicts identical on fixtures), `test_pilot_batch_five_respected`. Hermetic; one gated-live pilot probe, skipped in CI.
- **Satisfies:** R6 (pilot fourth), R2 (seam crossing), R5 (batch discipline on the pilot path).
- **Acceptance:** named tests green; fixture verdicts byte-identical before/after; no new AI-call volume (cost discipline holds).
