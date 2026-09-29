---
name: plan-console-polish-bc-phase-04-unified-manager
description: Centralized unified file/history manager (REPLACES per-root facts) — presets + free-text
created: 2026-09-28
base_commit: 0c8c57c
branch: docs/polish-bc-spec
status: locked
---

STATE: phase 4/6 — status: implemented-verified — focus: done, no commit (hermetic 21/21 + live IT-BC04-01..04/T08/T09/T10 green 42/42 in one run 2026-09-29; shots shot-bc-p04-manager-desktop/tablet.png)

# Phase 04 — Unified file/history manager (replaces B10) — REBASE-SENSITIVE

- **Blocking edges:** Wave 0. Downstream: Phase 05 + Phase 06. Serial core — nothing in Wave 2/3 starts before this contract lands.
- **Scope (files):** `factory/webui/server.py` (`_data_file_facts :1810-1841`, `_FILE_FACTS_TTL :1844-1848`, `/api/files/roots :4577-4580` — extend same endpoint with per-root `files` map `{exists,size,lines,mtime}`; NO new endpoint per spec Q2 recommended option); new or consolidated shared manager module (owns destinations/roots/history across cabins + cabin steps; absorbs `pinned_paths.py` pin store + `run_status.py` history reader + `cabin_history_controller.js` handoff; single owner of preset-destination list + custom-path validation); `factory/webui/index.html` (dest/root picker hooks); `factory/webui/static/js/shell/data_dialog_controller.js` + `shell/cabin_history_controller.js` (consume manager, delete parallel facts paths); `factory/webui/static/js/telemetry/telemetry_dashboard_controller.js` (`pickFacts :69-76`, rows `:104-154` — consume per-root facts from manager, never repeat one global facts object).
- **Locked rules:** L4 — ONE shared manager owns file/history picks across cabins and steps; operator picks a preset destination/root OR types a custom path (free-text validated against allowlist, lands under data root); per-row values come only from that row's root (global-repeat bug gone); missing → titled `—` with cause (file-missing / unregistered / over-cap), never bare dash; count badge equals visible rows; no fabricated numbers.
- **Tests:** extend `tests/factory/test_webui_data_root.py`: two roots with different files → cols 3–4 differ per row; missing-file root → titled empty with cause; custom path outside allowlist → 400; preset pick + custom-type pick both resolve through manager.
- **Wiring rows:** `GET /api/files/roots.files{exists,size,lines,mtime} → unified manager → dest/root pickers + history + paths table cols 3–4`; `pinned_paths + run_status → manager (single owner)`; route-delete: remove old global-facts repeat path in same PR.

## Acceptance criteria

- **Interaction tests (named):** IT-BC04-01 paths table with two differing roots → each row shows its own size/lines/mtime (from live response); IT-BC04-02 root without file → titled `—` with cause tooltip; IT-BC04-03 pick preset dest → input fills; type custom path → validated + fills; invalid path → fa error, no pick; IT-BC04-04 history handoff in second cabin reuses same manager (no second picker dialect).
- **Screenshots:** `shot-bc-p04-manager-desktop.png` + `shot-bc-p04-manager-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_data_root.py tests/factory/test_webui_live_browser.py -n 8`
- Rebase risk: **REBASE-SENSITIVE** — touches `server.py` routes + `index.html` cabins + history/picker modules the supervised-arbitration branch likely touched.
