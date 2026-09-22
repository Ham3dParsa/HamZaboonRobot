---
name: plan-tunnel-selection-phase-06-web
description: T8 web-last migration and build closure
created: 2026-09-22
base_commit: e4f7468
branch: feat/linker-judge-webui
status: complete
---

STATE: phase 6/6 — status: complete (2026-09-22, no commit) — T8 web-last migration landed: server lease/tunnel/route/whitelist helpers are thin seam callers (route_for_provider→probe route_for/route_reason + registry_fn; lease_tunnel_for_run→probe lease_tunnel + lease_fn/target_fn/clean_fn/verify_fn; report_run_lease/_report_lease_outcome→probe report_outcome + report_fn; provider_model_list google leg→seam lease/report/remember_fn; key_presence/_routing_clean_exit/api_provider_route→clean_fn over google_clean; GOOGLE_TUNNEL_REASON is the probe-module alias, local literal deleted); old direct helpers deleted same ticket (inline /v1/lease + 2× /v1/report urllib blocks, registry-route mirror, reason literal — source-grep verified); NEW tests/factory/test_tunnel_selection_web_migration.py 4 passed + 1 gated-live skipped (composition-reads-seam, no-domain-logic guard, no-copies sweep); earlier suites green (tunnel 8-file trio+migrations 45 passed + 6 skipped; webui judge suites 67 passed); full suite 3744 passed + 2 parallel-load flakes (offloop concurrent-starts, load-sim-100) that pass alone and reference neither webui nor tunnel files; compile_all EXIT 0; ruff F821/F811 clean on touched files; git diff --check clean; live boot on 127.0.0.1:5561 + 7 desktop screenshots read PASS (t8-compose/watch/benchmark/screened/label/guide/settings-drawer) with /api/providers + /api/engine_info + /api/providers/google/route facts live through the seam (egress/health 503 honest fail-closed, no supervisor here); server stopped clean via PID; no new module (single-file rewire) so test_wiring/SEAMS need no update; build closes 6/6 — remaining: gated live probes (need live keys), independent review, merge

# Phase 06 — Web last + closure (T8, P3, serial after T7)

- **Blocking edges:** Phase 05 (T7 green — all four prior callers on the seam).
- **Scope:** `factory/linking/webui/` server + precard viewer composition — display/composition reads selection state from the module; NO domain logic leaks into the server (R7). Final sweep: confirm no per-caller tunnel copies remain (dead-reference guard), update `parallel-work-guard/SEAMS.md` + `tests/test_wiring.py` targets if the module map changed, file the Final Verdict (done / deliberately-not-done / deferred / uncertain).
- **Tests (test-first):** NEW `tests/factory/test_tunnel_selection_web_migration.py` — `test_webui_composition_reads_seam_only`, `test_no_domain_logic_in_webui` (import/static guard), `test_no_per_caller_tunnel_copies_remain`. Existing `test_precard_judge_webui*` worktree tests keep passing in intent.
- **Satisfies:** R6 (web last, closes the five-caller order), R7 (rejections hold end-to-end: file cache, no god-supervisor, no carrier adapter).
- **Acceptance:** named tests green; dead-reference + wiring guards green; plan STATE lines flipped to `complete` with evidence (test names + commit hashes) only after implementation lands — not now.
