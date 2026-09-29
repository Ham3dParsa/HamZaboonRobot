# Phase 05 — P4 real arbiter tab panel (tab 2)

Gates: spec §2 tab-2 contract + G2 (arbiter→supervised jump). Blocking:
P1/P3 (runner + endpoint exist). No new backend (endpoint frozen).

## Content contract (exactly this, nothing bolted elsewhere)

New `#linking-tabpanel-2` (only the active tab's panel is visible —
tabs switch views; the P07 scroll hack is deleted with its code):
- Contract strip: entry (queued N senses + candidates) → exit
  (verdicts M + needs-review K), live counts.
- Preset selector: COMPACT READONLY list from the judge-preset store
  + link to the providers view. No duplicate preset form ever.
- Run / abort (busy-state, 3-part errors), progress
  `aria-live="polite"` (done/total/abstained).
- Verdict list via `paginated_list_controller` (shared 50-row pager).
- One jump button to tab 3 carrying the needs-review set.

## Files

- `index.html`: tabpanel markup inside `#view-linking` (ids stable
  elsewhere; tab buttons keep `data-tab-index`).
- NEW `static/js/sense_linking/arbiter_run_controller.js`, side-effect
  import in `main.js` (single-script-tag rule).
- Styles: existing `cabins.css`/`components.css` classes only unless a
  token is missing (then extend tokens, never one-off px).

## Req-1 anti-stack rules (owner-locked)

Bounded panel heights + `themed-scroll` inner lists; no page-level
stacking; `#833` card/pager/error/focus patterns inherited, never
reinvented; Persian copy via `persian-formatting`, BiDi via `api_client`
owners (`ltrCode`), Latin isolated per node.

## Req-2 live verification (owner-locked)

New live-browser test: tab-2 renders (preset list loads, empty states
honest), unknown-preset run surfaces the 404 in the 3-part box, abort
is unreachable pre-run; zero console errors. Desktop screenshot
recorded next to the T-shots (`.opencode/plans/factory/shots/`).

## Acceptance

Tab 2 acts end-to-end against stub-preset runs in tests and real runs
by the owner; no dead control; mobile stacks per existing breakpoints.
