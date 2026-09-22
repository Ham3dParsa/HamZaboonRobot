---
name: plan-tunnel-selection-phase-04-precard
description: T6 precard migration, busiest path becomes caller-only
created: 2026-09-22
base_commit: e4f7468
branch: feat/linker-judge-webui
status: draft
---

STATE: phase 4/6 — status: T6 implemented (2026-09-22, no commit) — call_leg frames the rotation attempt behind select/prove/remember (keyed probe, key NAME only; control-flow re-raises, legs byte-identical) and lease_for serves cache preference via select + ping gates via prove(keep=1) + winner via remember over provider-scoped order_cache_exits; TARGETS/keys/lease-cooldown shapes/registry/run-entry zero-diff; old inline cache+ping loop deleted same ticket; migration tests 7 passed + 1 gated-live skipped; earlier suites still green (trio + probes/linker-migration + precard-net/run-leg/google-clean + factory-run/judge/linker-judge: 294 passed + 3 skipped); full suite 3736 passed + 1 flaky offloop concurrency fail that passes alone and touches no precard files; compile_all clean; ruff F821/F811 clean on touched files; git diff --check clean

# Phase 04 — Precard migration (T6, P2, serial after T5)

- **Blocking edges:** Phase 03 (T5 green — linker adapters stable before touching the busiest path).
- **Scope:** `factory/precard/` pipeline/judge/topic call sites + `factory/run.py` (`ensure_supervisor` stays at run entry only; `call_leg` and lease acquisition become thin `select`/`prove`/`remember` callers), `factory/precard/provider_lease_policy.py` (single-writer rules preserved; cache reads become per-provider namespaces — provider-aware cache: `clean_cache_candidates` split by provider, no shared fallback). `TARGETS` table, key semantics, `call_leg` meaning, audit format — all FORBIDDEN/untouched. Same-PR old-path deletion.
- **Tests (test-first):** NEW `tests/factory/test_tunnel_selection_precard_migration.py` — `test_call_leg_routes_through_select_prove_remember`, `test_precard_cache_hit_is_provider_scoped`, `test_targets_table_semantics_unchanged`, `test_registry_default_stays_on_targets` (no forced migration). Existing precard integration tests keep passing unmodified in intent.
- **Satisfies:** R6 (precard third, registry untouched, forbidden zone intact), R2 (3-method seam), R4 (provider-aware cache on the hot path).
- **Acceptance:** named tests green; zero diff in `TARGETS`/key/audit sections (reviewer confirms); supervisor still self-starts only at run entry.
