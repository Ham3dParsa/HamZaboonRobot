STATE: IMPLEMENTED-UNCOMMITTED (Phase 1 + Phase 2 + R5/R6 + locked W1+W2 backend done in worktree, no commit, no PR, no merge)

## Locked addendum R5/R6 — DONE UNCOMMITTED (2026-09-27)

- R5: `test_surfaces_names_only` + `test_wake_sleep_buttons_wired` now read
  `static/js/providers/provider_registry_controller.js` TOGETHER WITH
  `index.html` (IDs asserted on markup, endpoint paths on markup+module).
  No string returned to `index.html`; zero behavior change.
- R6: noshrink ×2 `_css()` now reads the four stylesheets in link order
  from `factory/webui/static/` (actual location — owner wrote `static/css/`,
  no such subdir exists; `layout.css` + `cabins.css` included). Fallout fix
  in the same file: `_run_browser` serves via a real console subprocess on
  a free alternate port (live-browser pattern) — `file://` cannot resolve
  absolute `/static/*` links (proven: 4 sheets, 0 rules) — plus a boot-settle
  wait (`queue-remaining` leaves `…`) so `loadScreened` never wipes fixtures.
- Suite: 178 passed, 0 skipped (all three `judge_webui*` files + host_port
  + noshrink + operator_keys + wake_sleep).
- Proofs: `window.` in all 8 JS modules = 0; `onclick` in `index.html` = 0.
- NOT confirmed: `index.html` is 425 lines (python splitlines; 424 `\n`, no
  trailing newline) — over the 250 target. Markup body alone exceeds it;
  left for owner decision, no scope invented.

# Plan: WebUI Static Phase 1 — CSS extraction + /static/ route

Branch: `refactor/webui-static-phase1` (from `origin/main` @ `03c6af6`).
Worktree: `.worktrees/refactor-webui-static-phase1`. Primary `main` untouched.
Seam claim: `factory/webui` held by this branch (R1,R2,R3,R4).

## Locked contract (owner chose recommended options)

- R1: new branch + isolated worktree, primary untouched, seam claim on lock.
- R2: verbatim CSS move, zero word changes. tokens = :root/light/`*`/body/
  ltr+code (blocks 0-5); layout = scrollbar base + shell/nav/header/grids +
  responsive (6-15, 21-49, 82-84, 93-98, 172); components = shared cards/forms/
  tables/errors incl. dead `.label-settings` kept verbatim (99-118, 120,
  133-145, 155-170); cabins = sense/candidate/queue/preset-only (16-20, 50-81,
  85-92, 119, 121-132, 146-154, 171).
- R3: link order exactly tokens, layout, components, cabins.
- R4: JS inline untouched; server change ONLY `/static/<path:filename>`
  via `send_from_directory` (import already present, none added).

## Changes (all uncommitted)

- NEW `factory/webui/static/tokens.css` (6 rules), `layout.css` (49),
  `components.css` (50), `cabins.css` (68). No file headers (keeps proof exact).
- `factory/webui/index.html` 2474 -> 1827 lines: `<style>` block replaced by
  the four `<link>` tags in R3 order. No other line touched.
- `factory/webui/server.py` +6 lines: `/static/<path:filename>` route after
  `index()`; traversal blocked (verified 404), missing file 404.
- `tests/factory/test_sense_linking_judge_webui_interface.py`: +`_css()` helper
  (reads the four files in link order); 12 tests' CSS-content assertions now
  read `_css()`, HTML/JS assertions unchanged. Same test count, same intent.

## Zero-edit proof

- 173/173 top-level CSS rule blocks byte-identical between HEAD `<style>` block
  and the four files (multiset-equal, verified on LF-normalized bytes;
  working copies are CRLF per repo convention).
- Order preserved within each file; 30015 style bytes fully accounted.
- Honest scope note: naive "concatenated diff empty" cannot hold by design
  (regrouping reorders blocks across files); per-rule identity is the proof.

## Validation (worktree)

- Baseline pre-change: 67 + 101 + 2 live = 170 passed.
- Post-change: 170 passed (`test_sense_linking_judge_webui*.py`,
  `test_factory_webui_host_port.py`, `test_webui_live_browser.py` incl. real
  Chromium geometry + preset caps round-trip against external CSS).
- `scripts/compile_all.py` clean; `git diff --check` clean.
- Boot verify: `python factory/webui/server.py --host 127.0.0.1 --port 5571`
  -> `/` 200 (4 links, no `<style>`), all four CSS 200 `text/css`.

## Known caveat (desktop parity exact; tablet only)

`@media (max-width:1024px)` lives in `layout.css` (2nd link) while three bases
it overrides now load later (`.preset-compact` grid, `.btn-select-candidate`
/ `.btn-reject-all` / `.btn-skip-next` min-heights). Desktop rendering is
bit-identical (media inactive; proven by live-Chromium test at 1280x900).
On <=1024px viewports those four rules resolve to base values. Flag for Phase 2.

## Eyeball checklist (reboot command above, then open http://127.0.0.1:5571/)

1. Linking cabin: queue list scrolls, run row -> sense card + candidate cards
   full text, select button in header. 2. Providers cabin: cards grid,
   preset form + model dialog. 3. Telemetry view: bounded tables.
4. Toggle day/night theme. 5. Narrow window (~900px) to see the caveat above.

## Next (NOT done)

No commit, no PR, no merge — changes sit uncommitted in the worktree.
Phase 2 (JS extraction) only after owner eyeballs parity and says proceed.

## Phase 2 — DONE UNCOMMITTED (locked R1/R2/R3 + cascade fix, 2026-09-27)

Same branch/worktree (`refactor/webui-static-phase1`), single future PR
for both phases (R1). Same `factory/webui` seam claim — no new seams,
claims file untouched.

Modules (all NEW under `factory/webui/static/js/`, no file headers):
`shell/api_client.js` 140, `shell/view_navigator.js` 82,
`shell/filterable_list_controller.js` 25,
`providers/provider_registry_controller.js` 419,
`arbitration_presets/preset_catalog_controller.js` 339,
`sense_linking/human_review_controller.js` 310,
`telemetry/telemetry_dashboard_controller.js` 81, `main.js` 25
(boot wiring only: theme block + 7 boot calls).

Move proof: line-multiset diff old-inline vs new-modules = exactly
5 removed lines (onclick-attribute sync ×2, renderPresetForm/
renderTelemetry/renderPaths direct calls) + 28 added lines
(11 imports, data-view-target sync ×1, two dispatches, three listeners).
All other lines byte-identical modulo the 2-space HTML-indent strip.

Event bus (R3): `refreshProviderCards` dispatches `hz:providers-refreshed`
`{rows, rateRows, info}` (preset re-renders form, telemetry re-renders
table); `refreshBadges` roots leg dispatches `hz:paths-refreshed`
`{roots}` (telemetry re-renders paths) — same mechanism, completes R3's
provider→telemetry decoupling (else a direct import would remain).
`index.html`: 0 inline `onclick` (8 nav buttons → `data-view-target`,
wired in `view_navigator.js` — the one wiring the split initially missed,
caught by live browser, fixed), exactly one script tag
(`<script type="module" src="/static/js/main.js">`), zero `window.*`
in all modules. No `server.py` change (existing `/static/<path>`
route serves nested modules as `text/javascript`).

Cascade fix (Phase-1 caveat closed): the 6 cabin-domain rules moved out
of `layout.css`'s `@media(max-width:1024px)` into a verbatim `@media`
block at the end of `cabins.css` (last link); layout-domain rules stay
at the end of `layout.css`. Tablet (≤1024px) cascade matches pre-split.

Validation (worktree): mandated set 165 passed (interface + judge_webui
+ host_port + 3 live incl. NEW `test_shell_chrome_no_console_errors`:
nav/tab/modal/preset-save/filter, pageerrors zero, console clean except
keyless-env 502/503 resource lines); `compile_all.py` clean;
`git diff --check` clean; boot smoke `/` 200 + modules/CSS 200.
Guards pass (wiring, dead-code, single-source-of-truth).

Known, withheld per contract (test-sync onclick-only + fix-forward
scope): `test_factory_webui_operator_keys.py::test_surfaces_names_only`
and `test_factory_webui_wake_sleep.py::test_wake_sleep_buttons_wired`
read `/api/supervisor/(token|wake)` from `index.html` — the strings now
live in `provider_registry_controller.js` (behavior identical, live
proven). One-line remedy each (read the module, same `_js()` pattern)
left for owner decision. Pre-existing Phase-1: noshrink ×2 still fail
on missing `<style>` (untouched, out of scope).

No commit, no PR — single future PR still holds both phases.

## W1+W2 backend — DONE UNCOMMITTED (locked R1+W2, 2026-09-27, serial same worker)

Backend only (`factory/webui/server.py` + `tests/`); frontend
JS/HTML/CSS untouched (parallel worker owns those).

- R1 (wake fix, `_ensure_supervisor_for_leased`): token resolves +
  down probe (`health_fn` when injected, else read-only local
  `supervisor_health_snapshot`) -> falls through to the
  `_wake_supervisor_background(health_fn=...)` branch, never a blind
  ready. Raising probe -> old assume-alive path (no blind wake).
  Direct-route and no-token paths byte-behavior-preserved.
- W2 (screening routes): POST `/api/screening/run` (optional words,
  default the export script's own `DEFAULT_WORDS`; optional out_dir,
  default `<data_root()>/proof-linker/screened`; Popen-spawns
  `python -m factory.linking.export_screened`, pump thread drains
  merged stdout+stderr into a 100-line ring, PID recorded, 201
  running / 409 when busy); GET `/api/screening/status`
  (idle/running/completed/failed + elapsed + exit code + tail +
  manifest summary kept_total/dropped_total/per_lemma on success);
  POST `/api/screening/abort` (SIGTERM recorded child, short wait,
  kill fallback via the shared `_terminate_child` leg; settles to
  failed + operator-abort note; 409 when idle).
- `factory/precard/prune.py` + `factory/linking/export_screened.py`
  untouched.
- Validation: NEW `tests/factory/test_factory_webui_screening_wake.py`
  (11 passed: token×probe matrix + tunnel-lease wake-first ordering +
  run/status/tail/manifest/failed/abort/kill-fallback); mandated set
  186 passed + 1 FAILED (`test_design_bounded_lists_with_themed_scroll`
  counts 2 bounded tables, markup now has 3 — parallel worker's
  uncommitted `index.html` delta, out of backend scope, left for them);
  wiring + dead-code + single-source guards 56 passed;
  `compile_all.py` clean; `git diff --check` clean.
- No commit, no push, no PR, no merge — all uncommitted in the worktree.
