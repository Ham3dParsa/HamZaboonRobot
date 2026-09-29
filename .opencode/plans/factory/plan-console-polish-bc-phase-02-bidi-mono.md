---
name: plan-console-polish-bc-phase-02-bidi-mono
description: PUX-B8 mono scope + PUX-B9 BiDi/number single-owner
created: 2026-09-28
base_commit: 0c8c57c
branch: docs/polish-bc-spec
status: locked
---

STATE: phase 2/6 — status: implemented-verified — focus: static suite green (8 passed), live BiDi audits green, genuine p02 shots captured; no commit per ticket

# Phase 02 — Mono scope + BiDi single-owner (PUX-B8 + B9)

- **Blocking edges:** Wave 0 only. Parallel-safe vs 01, 03.
- **Scope (files):** `factory/webui/static/js/shell/api_client.js` (`:3-13` — sole owner `faNum`/`ltrCode` + LTR containers); `factory/webui/static/js/shell/data_dialog_controller.js` (`:31-43` — DELETE local `ltr`/`faCell`, consume owner); `factory/webui/static/tokens.css` (`:60-70`), `factory/webui/static/cabins.css` (`:138-143, :171-175, :237-246`), `factory/webui/static/layout.css` (`:100, :190`), `factory/webui/static/components.css` (`:35, :137-147`) — mono back to body font for `.mini-val`/log/word-input, mono kept only on `.code-token`/`.model-id`/`.error-code`; physical `text-align: left/right` → logical `inline-start/end`.
- **Locked rules:** single owner — no second `function ltr(`/`function faCell` definition anywhere; every Latin identifier in its own isolated node; no Persian number/text in `var(--mono)`; zero physical `text-align: left/right` left in console CSS.
- **Tests:** extend `tests/factory/test_webui_static.py`: grep-assertion no `function ltr\(|function faCell` outside `api_client.js`; grep-assertion no `text-align: left/right` in `factory/webui/static/*.css`; DOM spot-check Persian numerals in body font + model-id in isolated mono node.
- **Wiring rows:** `api_client(faNum/ltrCode) → data_dialog + queue + per-lemma + history + telemetry renderers`; `tokens --mono → .code-token/.model-id/.error-code only`.

## Acceptance criteria

- **Interaction tests (named):** IT-BC02-01 keyboard-tab through queue + per-lemma rows → identifiers read LTR-isolated, Persian counts in body font (visual + DOM class audit); IT-BC02-02 grep audit → zero duplicate `ltr`/`faCell` defs, zero physical `text-align`; IT-BC02-03 log box with mixed fa/en → identifiers mono-isolated, surrounding Persian in body font.
- **Screenshots:** `shot-bc-p02-bidi-desktop.png` + `shot-bc-p02-bidi-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_static.py -n 8`
- Rebase risk: LOW (CSS + leaf-JS; flag only if other branch touched the same renderers).
