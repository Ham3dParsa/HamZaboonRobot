---
name: plan-console-polish-bc-phase-06-paged-empties
description: PUX-B11 shared paged list (p50) + PUX-B12 titled empties
created: 2026-09-28
base_commit: 0c8c57c
branch: docs/polish-bc-spec
status: locked
---

STATE: phase 6/6 — status: implemented-uncommitted — focus: review + PR (no commit/push/PR/merge performed by agent)

- Implemented 2026-09-29 in worktree feat/console-polish-bc (base 364d690): shared `paginated_list_controller.js` (PAGED_LIST_SIZE=50, pager, EMPTY_FA six states, moveAcrossPages) adopted by queue + per-lemma + history + files; 4 pager mounts in index.html; hermetic `test_webui_paged_list.py` 8/8 green; live IT-BC06-01..04 + desktop/tablet shots green (see return notes for suite evidence incl. t04_02 environmental classification).

# Phase 06 — Shared paged list + titled empties (PUX-B11 + B12) — PARTIALLY SENSITIVE

- **Blocking edges:** Phase 04 (facts/empty strings come through manager) + Wave 0. Parallel-safe vs 05.
- **Scope (files):** new shared module next to `factory/webui/static/js/shell/filterable_list_controller.js` (`:1-25` — paging companion, NOT a fork): default page size 50, prev/next pager, `N نمایان از M` counter, filter preserved across pages; adopters (no per-cabin copies): `factory/webui/static/js/sense_linking/human_review_controller.js` (`renderQueue :61-106`, row `tabIndex :73`, `keydown :98-103`), `factory/webui/static/js/screening/screening_cabin_controller.js` (`renderPerLemma :247-324`, `tr.tabIndex :282`, `keydown :316-321`), `factory/webui/static/js/shell/cabin_history_controller.js` (`render :84-146`); empty-state strings from spec §3 glossary (fa + `title` cause; six states: no-roots / no-rows / no-filter-match / no-history + popover-group-empty + missing-fact).
- **Locked rules:** L1 page-50 with pager; 500-row list never mounts more than one page in DOM; filtering + paging counter stays exact; titled empties everywhere (fa text + `title` cause, zero bare `…`/bare `—`); row keyboard contract from spec §1.7 preserved inside paging (single-stop layer for popover lists; queue/per-lemma rows keep Enter/Space activation with directional cycling where the pager owns the page).
- **Tests:** new or extended `tests/factory/test_webui_paged_list.py` (preferred) else extend live-browser: 500-row fixture → DOM rows ≤ 50; pager next/prev updates counter; filter applies across all pages with correct count; all six empty states render fa text + `title`.
- **Wiring rows:** `paged-list module (p50) → queue + per-lemma + history (shared, no copies)`; `manager empty causes → titled empty strings (§3 glossary)`; route-delete: delete any per-cabin paging copy in the same PR.

## Acceptance criteria

- **Interaction tests (named):** IT-BC06-01 500-row queue → first page ≤ 50 rows, pager next/prev + counter exact; IT-BC06-02 filter → count spans pages, paging keeps filter; IT-BC06-03 keyboard: tab into list → arrows move across page boundary via pager; IT-BC06-04 each of six empty states → fa sentence + `title` cause in DOM.
- **Screenshots:** `shot-bc-p06-paged-desktop.png` + `shot-bc-p06-paged-tablet.png`.
- **pytest:** `python -m pytest tests/factory/test_webui_paged_list.py tests/factory/test_webui_live_browser.py -n 8`
- Rebase risk: **PARTIALLY SENSITIVE** — `human_review_controller.js` queue + list regions of `index.html` likely touched by supervised-arbitration; the new paged module file itself is rebase-safe.
