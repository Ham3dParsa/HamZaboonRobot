---
name: plan-tunnel-selection-phase-03-linker
description: T5 linker migration, google_clean helpers become adapters
created: 2026-09-22
base_commit: e4f7468
branch: feat/linker-judge-webui
status: draft
---

STATE: phase 3/6 — status: T5 implemented (2026-09-22, no commit) — google_clean is a formal seam adapter (classify→classify_exit, check via make_google_probe/KeylessGoogleProbe, select via TunnelSelector.select, remember on single writers; old direct classify call + select loop deleted same ticket); probe/webui call sites unchanged (names kept); tunnel_selection.py + probe_providers.py + linker core/sieves/gates/registry untouched (zero diff); migration tests 4 passed + 1 gated-live skipped; trio + probes-migration + google_clean + single-owner guard + dead-code/wiring/single-source suites green (116 passed + 3 skipped targeted; full suite 3729 passed + 1 flaky offloop concurrency fail that passes alone and touches no linker files); compile_all EXIT 0; ruff F821/F811 clean on touched files; git diff --check clean; supervisor --probe-google inline verdict convergence still parked (shared infra, out of scope)

# Phase 03 — Linker migration (T5, P1, serial after T4)

- **Blocking edges:** Phase 02 (T4 green — adapter behavior proven by probes first).
- **Scope:** `factory/linking/google_clean.py` (`classify`/`check_exit`/`fresh_clean_exits`/`select_clean_exit`/`verify_and_remember` converge into the official `ProviderProbe` + `remember` path — absorbed, not duplicated), `factory/linking/probe_providers.py` link-side glue (if any), `factory/net/tunnel_selection.py` (adapter registration only). `factory/linking/linker.py` core, sieves, and quality gates are FORBIDDEN — untouched. Same-PR deletion of the superseded helper path.
- **Tests (test-first):** EXTEND `tests/factory/test_google_clean_selection.py` (existing worktree test — keep passing or formally supersede with reason) + NEW `tests/factory/test_tunnel_selection_linker_migration.py` — `test_linker_clean_selection_through_seam`, `test_google_cache_namespace_separate_from_groq` (provider-aware cache: linker Google-clean rows never leak into Groq namespace), `test_linker_core_untouched` (no diff in `linker.py`/sieves/gates). Gated-live single-provider case, skipped in CI.
- **Satisfies:** R6 (linker second, core locked), R3 (worktree helpers become adapters — the "three copies converge" rejection), R4 (paid-first + provider-aware cache on the linker path).
- **Acceptance:** named tests green; dead-reference guard green (old helper path gone); `git diff --stat` shows zero lines in `linker.py`/sieves/gates.
