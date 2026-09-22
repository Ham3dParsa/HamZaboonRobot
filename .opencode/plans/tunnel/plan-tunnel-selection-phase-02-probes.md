---
name: plan-tunnel-selection-phase-02-probes
description: T4 probes migration, lowest-risk first caller
created: 2026-09-22
base_commit: e4f7468
branch: feat/linker-judge-webui
status: draft
---

STATE: phase 2/6 — status: T4 implemented (2026-09-22, no commit) — probe_one is a thin select+prove caller, old inline transport block deleted same ticket (source-grep verified); KeylessGoogleProbe + KeyedProviderProbe registered in tunnel_selection (no interface change); migration tests 4 passed + 1 gated-live skipped; trio still 21 passed + 1 skipped; probe-adjacent suites green (steps2to6, google_clean, egress 61 passed); compile_all EXIT 0; ruff F821/F811 clean on touched files; git diff --check clean; probe_keys.py + --probe* flags verified no-op (no tunnel-exit logic; supervisor --probe-google convergence parked for T5); one unrelated pre-existing failure (single-owner guard vs untouched google_clean.py classify, T5 territory)

# Phase 02 — Probes migration (T4, P1, serial gate)

- **Blocking edges:** Phase 01 (T1–T3 green).
- **Scope:** `factory/linking/probe_providers.py` (`probe_one` sits behind `prove`; `route_for`/`lease_tunnel` become thin callers), `factory/core/probe_keys.py` + `--probe*` CLI flags (same treatment), `factory/net/tunnel_selection.py` (only to register the keyless-Google and keyed-second `ProviderProbe` implementations — no interface change). Old probe path stays until green, then is deleted in the SAME PR (route-delete rule). Registry cooperates via `registry_fn` injection; default stays on `TARGETS`.
- **Tests (test-first):** NEW `tests/factory/test_tunnel_selection_probes_migration.py` — `test_probe_one_routes_through_prove_seam`, `test_old_probe_path_deleted_same_pr` (dead-reference guard: `tests/test_dead_code_guard.py` green), `test_probe_reports_latency_and_error_kind_unchanged`. Hermetic fakes; one gated-live case (`test_live_probe_single_provider_capped` — explicit flag + provider + batch cap, free probe only, skipped in CI).
- **Satisfies:** R6 (probes first, same-PR old-path deletion, registry untouched), R2 (callers cross the seam), R3 (probe adapter exercised by a real caller).
- **Acceptance:** named tests green; old `probe_one` body unreferenced (guard proves deletion); no screening/evidence/ranking file touched; batch/concurrency knobs untouched.
