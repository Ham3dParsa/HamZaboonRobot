---
name: plan-console-polish-bc
description: Console polish group B+C tickets (PUX-B1..B12) with locked owner answers — docs only, no code
created: 2026-09-28
base_commit: 0c8c57c
branch: docs/polish-bc-spec
status: locked
---

STATE: phase 0/6 — status: tickets-written — focus: await supervised-arbitration merge, then execute waves 1→3

# Console Polish B+C — Main Plan (docs only)

- Source: `.opencode/plans/factory/spec-console-polish-bc.md` (12 reqs PUX-B1..B12). Group A excluded (shipped in #831).
- LOCKED owner answers (do not re-ask):
  - L1 page size **50 with pager** (B11).
  - L2 Vazirmatn **SELF-HOSTED** — bundle font files in repo, serve locally, no CDN.
  - L3 command popover **PICKING-ONLY** — no action triggering from the popover.
  - L4 per-root facts **REPLACED** by centralized unified file/history management across cabins and cabin steps — preset options plus optional free-text input (operator picks a preset destination/root or types a custom path; one shared manager module owns it). B10's per-row facts display is consumed through this manager, not a parallel facts path.
- Gate: **ALL waves execute AFTER the supervised-arbitration branch merges.** A parallel session holds `factory/webui` until then. After that merge, rebase `docs/polish-bc-spec` (or the implementation branch) onto new `main` before starting Wave 1. REBASE-SENSITIVE tickets listed below.

## Waves & blocking edges

- **Wave 0 (gate, no code):** supervised-arbitration merges → rebase → start. Blocks everything.
- **Wave 1 (parallel-safe, no server.py):** Phase 01 (font) || Phase 02 (mono+BiDi) || Phase 03 (layout). No inter-edges; all blocked only on Wave 0.
- **Wave 2 (serial core):** Phase 04 (unified manager) after Wave 0 → Phase 05 (picking-only popover) after Phase 04.
- **Wave 3 (lists):** Phase 06 (paged-50 + titled empties) after Phase 04 (manager contract for facts/empties); parallel-safe vs Phase 05.

## Parallel/serial matrix

| Phase | Topic | Wave | Blocking edges | Parallel with | Serial after |
|---|---|---|---|---|---|
| 01 | font self-hosted (B7) | 1 | Wave 0 | 02, 03 | — |
| 02 | mono scope + BiDi single-owner (B8+B9) | 1 | Wave 0 | 01, 03 | — |
| 03 | sticky control + inner scroll (B5+B6) | 1 | Wave 0 | 01, 02 | — |
| 04 | unified file/history manager (replaces B10) | 2 | Wave 0 | — | — (then 05, 06) |
| 05 | anchored picking-only popover (B1–B4) | 2 | 04 + Wave 0 | 06 | 04 |
| 06 | shared paged list p50 + titled empties (B11+B12) | 3 | 04 + Wave 0 | 05 | 04 |

## Wiring map (phase → contract rows)

| Phase | Wiring rows (producer → consumer) |
|---|---|
| 01 | `static/fonts/* → @font-face → body --sans` |
| 02 | `shell/api_client.js (faNum/ltrCode) → all consumers; local ltr/faCell deleted` |
| 03 | `layout.css/cabins.css caps (260/320/380) → cabin control column + workspace scroll` |
| 04 | `GET /api/files/roots (+files map) → unified manager → dest/root pickers + history + paths table` |
| 05 | `invoke button → anchored popover (pins/recents/paths) → pick → fills input, focus returns` |
| 06 | `paged-list module (p50) → queue / per-lemma / history; shared titled-empty strings` |

## Rebase-sensitive flags (vs supervised-arbitration branch)

- Phase 03, 04, 05: **REBASE-SENSITIVE** (touch `server.py` routes and/or `index.html` cabins and/or `view_navigator.js` scoping).
- Phase 06: **PARTIALLY SENSITIVE** (touches `human_review_controller.js` queue + `index.html` list regions the other branch likely touched; paged module itself is new-file safe).
- Phases 01, 02: CSS/leaf-JS only; low rebase risk.

## What changes / not changed / uncertain

- Changed (planned): console layout, font hosting, BiDi ownership, file/history picking UX, list paging/empties. No arbitration scoring/logic change.
- Deliberately NOT changed: group A (shipped #831), arbitration verdict logic, AI cost paths, Telegram bot code.
- Uncertain: exact file-level drift the supervised-arbitration merge will introduce in `server.py`/`index.html`/`view_navigator.js` — resolved by the Wave-0 rebase, never by silent gap-filling.
