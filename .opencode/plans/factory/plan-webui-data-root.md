STATE: IMPLEMENTED-UNCOMMITTED (T1+T2+T3 done in worktree 2026-09-27 — no commit, no push, no PR, no merge)

## Implementation record (uncommitted)

- T1 data-root — DONE: `env_loader.data_root()` chain env -> `W:\hamzaban_data_factory`
  (isdir-gated) -> legacy repo `data/` (isdir-gated; existing installs keep
  working) -> `~/.hamzaban/data` (no new resolver; `W_DATA_ROOT` const only);
  `server.py` consumes `data_root()` only via lazy `presets_dir()`/
  `operator_keys_path()`/`labels_path()` helpers (re-resolved per call);
  runs/registry/profiles/key-vars stay per-console; `_ensure_shared_store_migrated()`
  once-guarded on every serve path (before_request + `__main__`), copy-when-empty,
  never-overwrite, names-only logs. Live: save -> `W:\hamzaban_data_factory\webui\
  presets\t1proof-<pid>.json` (outside git); restart -> still listed; rerun clean.
- T2 telemetry race — DONE: controller-only `fetchAndRenderTelemetry` +
  `fetchAndRenderPaths` on init IN ADDITION to listeners, PLUS one-line
  side-effect import in `main.js` (found live: controller never loaded, tables
  froze on "…" — declared fix-forward, zero other behavior change). Live
  Chromium: telemetry badge + rows, paths badge + rows on page load, 0 pageerrors.
- T3 files/roots — DONE (serial after T1, `server.py` only): `/api/files/roots`
  keeps `roots` shape + adds `files.{kaikki_raw,screened}` (`exists`+`size`
  always; lines capped 50000, honest `N+`; 30s TTL cache so polling never
  rescans per request). Live: kaikki 3212282689 B -> `50000+`
  truncated; screened 1063637 B -> `267` exact.
- R6 preset edit/clone/delete: verified existing (`save_preset` upsert +
  `previous_name` rename + `delete_preset`; clone = save-as; edit = load-into-form)
  against pointed store — nothing genuinely missing, zero new scope.
- Validation: 290 passed (+11 subtests) incl. new `test_webui_data_root.py` (8),
  updated `test_data_root.py` (14), guards (wiring/dead-code/single-source);
  `compile_all.py` + `git diff --check` + ruff F821/F811 clean.

# Plan: WebUI shared data-root (presets + operator keys + labels out of git)

Branch: `refactor/webui-static-phase1` (from `origin/main` @ `03c6af6`).
Worktree: `.worktrees/refactor-webui-static-phase1`. Primary `main` stays clean and untouched.
Seam claim: `factory/webui` already held by this branch — no new seams, no new claims, claims file untouched.
Single future PR holds Phase 1 + Phase 2 + this program (no commit/push/PR/merge in this program).

## Locked rules (all owner-chosen recommended)

- R1: extend `factory/core/env_loader.py::data_root()` fallback chain to
  env `HAMZABAN_DATA_ROOT` -> `W:\hamzaban_data_factory` (when that dir exists)
  -> legacy repo-local `data/` (when that dir exists; existing installs keep
  working, no migration) -> `~/.hamzaban/data/`. No new resolver function
  anywhere (single-source rule). `server.py` consumes `data_root()` only via
  lazy helpers (never a duplicated fallback, never import-time binding).
- R2: move to shared root: `factory/webui` presets dir, `operator_keys.json`,
  `labels.jsonl` (under `<data_root>/webui/`), resolved through lazy
  `presets_dir()`/`operator_keys_path()`/`labels_path()` helpers re-resolved
  per call. Run history (`RUNS_DIR`/`runs.json`) STAYS per-console
  (still `SCRIPT_DIR/runs`, `SCRIPT_DIR/runs.json`).
- R3: first-boot auto-migration — copy existing files (e.g. `witness_benchmark.json`,
  existing operator keys) into the new root ONLY when the target slot is empty;
  never overwrite; log names-only (values never anywhere). Runs once on every
  serve path (`before_request` once-guard + `__main__`; idempotent).
- R4: `/api/files/roots` reports `kaikki_raw.jsonl` + `screened.jsonl` existence +
  byte size always; line count capped (first 50000 lines) with honest `N+` label
  when truncated — never a full unbounded count per request (3.2GB kaikki guard);
  short-TTL cached (30s) so polling never full-scans per request.
- R7 (reviewer must-fix, PR #830): screening `out_dir` confined under the
  screening root (escapes -> 400, never silent rewrite); words validated
  `^[a-z-]{1,64}$` + capped at 50.
- R5: tickets — T1 data-root (`server.py` + `env_loader.py`), T2 telemetry race
  (`static/js/telemetry/telemetry_dashboard_controller.js` ONLY: initial
  `fetchAndRenderTelemetry` + `fetchAndRenderPaths` on controller init IN ADDITION
  to `hz:providers-refreshed`/`hz:paths-refreshed` listeners), T3 files/roots
  dynamics (`server.py`, serial AFTER T1). Same branch, single future PR.
- R6 (scope guard): preset edit/clone/delete — verify existing ops against the shared
  store (`save_preset` upsert + `previous_name` rename + `delete_preset` exist;
  clone = save-as without `previous_name`; edit = load-into-form); implement ONLY
  what is genuinely missing, no invented scope.

## Ticket table (blocking edges)

| Ticket | Scope | Depends on | Status |
|--------|-------|------------|--------|
| T1 data-root | `factory/core/env_loader.py` (`data_root` fallback), `factory/webui/server.py` (shared presets/keys/labels + auto-migration), test-sync for new paths | — | `done-uncommitted` |
| T2 telemetry race | `factory/webui/static/js/telemetry/telemetry_dashboard_controller.js` ONLY (initial fetch+render on init + existing listeners) | — (\|\| T1, disjoint files, may run PARALLEL) | `done-uncommitted` |
| T3 files/roots dynamics | `factory/webui/server.py` (`/api/files/roots` file facts, capped counts) | T1 (serial AFTER T1 lands — same file) | `done-uncommitted` |

## Acceptance

- T1: preset save -> file appears under shared root outside git; server restart ->
  preset still listed; restart-safe migration (second boot never overwrites);
  tests updated for new paths (test-sync in scope).
- T2: telemetry + paths tables populate on page load with no `"..."` freeze
  (live-browser proof: badge cells + tbodies non-empty without waiting for a refresh event).
- T3: roots show real existence/size/capped counts for `kaikki_raw.jsonl` and `screened.jsonl`
  (`exists` + `size` always; `lines` capped at 50000 with honest `N+` label when truncated).

## Validation (final)

`pytest tests/factory/test_sense_linking_judge_webui*.py tests/factory/test_factory_webui_host_port.py`
+ affected suites (`test_data_root.py`, operator_keys, secrets_ignored, live_browser),
`scripts/compile_all.py`, `git diff --check`. Fix forward within scope only.

## Non-goals

No commit, no push, no PR, no merge. Plan STATE updated per ticket.
Secrets: names only, values never anywhere. No AI-call volume change.
