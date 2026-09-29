---
name: plan-console-polish-bc-phase-01-font
description: PUX-B7 Vazirmatn self-hosted (bundle in repo, serve locally)
created: 2026-09-28
base_commit: 0c8c57c
branch: docs/polish-bc-spec
status: locked
---

STATE: phase 1/6 — status: implemented-verified — focus: done, no commit (static 8/8 + live IT-BC01-01/02/03 green 2026-09-29)

# Phase 01 — Font self-hosted (PUX-B7)

- **Blocking edges:** Wave 0 only (supervised-arbitration merge + rebase). Parallel-safe vs 02, 03.
- **Scope (files):** `factory/webui/index.html` (`:7-10` head — local font CSS link, no external URL); new `factory/webui/static/fonts/` (bundled `woff2` files + `@font-face` with `font-display: swap`); `factory/webui/static/tokens.css` (`:24` `--sans` stays first, no family rename). No server.py change (static served by existing route). No new endpoint.
- **Locked rules:** L2 self-hosted bundle (no CDN/outbound font request); body family stays `--sans`; if font missing → system fallback with no layout break; offline-external Network still renders Vazirmatn.
- **Tests:** add/extend `tests/factory/test_webui_static.py` (or live-browser head audit): no `http(s)://` font URL in head/CSS; `woff2` files exist under `static/fonts/`; computed body font includes Vazirmatn with fallback stack.
- **Wiring rows:** `static/fonts/*.woff2 → @font-face → body { font-family: var(--sans) }`.

## Acceptance criteria

- **Interaction tests (named, keyboard-level where applicable):** IT-BC01-01 block external network → reload console → Persian text renders Vazirmatn (no tofu, no layout shift); IT-BC01-02 audit head/CSS → zero outbound font requests (devtools network `font` filter empty for remote); IT-BC01-03 remove/rename one `woff2` → page still lays out on system fallback, no console error break.
- **Screenshots:** `shot-bc-p01-font-desktop.png` + `shot-bc-p01-font-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_static.py -n 8`
- Rebase risk: LOW (new font dir + head/CSS leaves only).
