---
name: plan-tunnel-selection-phase-01-foundation
description: T1-T3 hermetic module, adapters, provider-aware store, batch loop
created: 2026-09-22
base_commit: e4f7468
branch: feat/linker-judge-webui
status: draft
---

STATE: phase 1/6 — status: T1+T2+T3 integrated (Wave-integration 2026-09-22) — trio 21 passed + 1 gated-live skipped across seam(5)+store(9)+prove(7) files; seam skeleton asserts updated to locked real behavior (prove clean==[e1,e2] 2 probes, prove writes 0, remember writes 1, empty writes 1); compile_all EXIT 0; ruff F821/F811 clean; git diff --check clean; no production code touched (test fix, not bug fix)

# Phase 01 — Foundation: module, interface, seam, adapters (T1–T3)

## T1 — Module skeleton + 3-method seam (P0, serial root)

- **Blocking edges:** none (root; blocks T2–T8).
- **Scope (files/modules):** NEW `factory/net/tunnel_selection.py` (class `TunnelSelector`, `Selection`/`Proof` shapes, `NoTunnelExit`, `SubscriptionSource` + `ProviderProbe` ABCs); NEW `factory/net/__init__.py` re-export. Touches nothing else.
- **Tests (test-first, red before green):** NEW `tests/factory/test_tunnel_selection_seam.py` — `test_seam_select_prove_remember_importable`, `test_ctor_touches_no_io` (constructor with fakes performs zero network/file/key access), `test_deletion_justifies_seam` (removing `ProviderProbe` breaks the two-probe test — documents R3). Update `tests/test_wiring.py` scan targets + `parallel-work-guard/SEAMS.md` for the new module (module-add guard).
- **Satisfies:** R1, R2, R7 (rejection of multi-class library; lock-outside-network rule stated).
- **Acceptance (verifiable artifacts):** `pytest tests/factory/test_tunnel_selection_seam.py -k "importable or no_io"` green; `python scripts/compile_all.py` clean; `ruff` F821/F811 clean; `git diff --check` clean. No caller migrated.

## T2 — Provider-aware store + paid-first subscription adapter (P0, parallel with T3 after T1)

- **Blocking edges:** T1 (consumes locked seam signatures, read-only).
- **Scope:** `factory/net/tunnel_selection.py` ONLY (internal store: per-provider whitelist read/write, never-overwrite-with-empty, best-effort IO; `SubscriptionSource` paid-first refresh + dedup). Reads env **names** only (`EGRESS_SUB_URL`/`EGRESS_SUB_URLS`, `EGRESS_CLEAN_TTL`, `EGRESS_CLEAN_CACHE_PATH`). Provider-aware cache in this ticket: Google-clean list and Groq-clean list are separate namespaces; a Google hit never serves a Groq `select` and vice versa; rows carry id + timing only.
- **Tests (test-first):** EXTEND `tests/factory/test_tunnel_selection_seam.py` or NEW `tests/factory/test_tunnel_selection_store.py` — `test_select_serves_fresh_provider_cache_without_refresh`, `test_stale_cache_is_miss`, `test_provider_cache_isolation_google_vs_groq`, `test_paid_first_ordering_in_refresh`, `test_dedup_singletons`, `test_remember_empty_never_touches_file`, `test_injected_clock_drives_ttl_boundary`. All hermetic (fake subs, tmp store, injected clock).
- **Satisfies:** R3 (subscription adapter; writers internal), R4 (paid-first + provider-aware cache).
- **Acceptance:** named tests green; `test_provider_cache_isolation_google_vs_groq` fails on any global-cache implementation (deletion test for the amendment).

## T3 — Prove batch-5/keep-5 loop + two-adapter proof (P0, parallel with T2 after T1)

- **Blocking edges:** T1 (same as T2; independent of T2's internals).
- **Scope:** `factory/net/tunnel_selection.py` ONLY (internal `prove`: max-5 batches in priority order, early stop at `keep` clean, `blocked` vs `unknown` split, no cache writes inside `prove`; `ProviderProbe` mapping: keyless Google + keyed second probe behind one `Proof` shape). `batch`/`keep` injectable (default 5), never literals in the body. Provider-aware cache touch: `prove` reads per-provider priority (paid-first, then latency) but writes nothing — stabilization stays in `remember`.
- **Tests (test-first):** NEW `tests/factory/test_tunnel_selection_prove.py` — `test_prove_batches_max_five_with_early_stop_at_keep`, `test_prove_no_second_batch_once_keep_met`, `test_transport_timeout_is_unknown_not_blocked`, `test_two_adapters_same_prove_scenario` (keyless Google probe + keyed probe both green on one scenario — R3 justification), `test_prove_writes_no_cache`. Gated-live test stub declared but skipped in CI (`test_live_prove_gated_skipped_without_flag`).
- **Satisfies:** R3 (probe adapter), R5 (batch/keep), R4-cache-read (per-provider priority).
- **Acceptance:** named tests green; batch-size violation (6-wide) and keep-overflow (6 stabilized) both fail loudly.

## Wave placement

Wave 0 = T1 (1 worker). Wave 1 = T2 ∥ T3 (2 workers): disjoint internals, shared read-only seam, no caller touched — safe parallel pair, within budget.
