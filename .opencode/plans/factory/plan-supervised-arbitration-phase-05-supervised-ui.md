# Phase 05 — Supervised-arbitration UI (P05)

Gates: R4 (progress + history visible), R5 (renamed section, guided batches), R6 (gallery button), R1/R3 (review screen).
Blocking: P01/P04/P02 API shapes (frozen — build against main-plan contracts, W2).

## Scope

- `index.html`: rename human-review heading to «داوری تحت نظارت اپراتور» (keep element ids — no JS breakage); batch panel: issue-batch controls (size 10–50, default 25), batch list with status chips + counts, per-batch actions (copy MD / download JSON / import-paste / review / repair-copy / cancel); review screen: per-item checkbox rows (sense + candidates summary) + select-all + approve-selected; gallery button in TSV tab + per-history-row gallery button (old runs).
- New `static/js/sense_linking/supervised_batch_controller.js`: all batch API calls, busy-state, 3-part errors, `aria-live` counts, focus retention on filter; follows existing console language (A2 contract-header pattern where it fits, no new design system).
- Persian copy: load `persian-formatting`; every dynamic value escaped before interpolation.

## Tests

- Manual click checklist (recorded): issue→copy→import→review→approve→history shows progress; prohibited paths (re-export active, approve empty) refuse honestly.

## Wiring rows

| Type | Item | Disposition |
|---|---|---|
| Existing UI | linking view sections | extend (additive panels; ids kept) |
| New JS | `supervised_batch_controller.js` | create |
| Consumed APIs | `/api/batches*`, `/api/gallery` | keep (no change) |

## Acceptance

Full batch lifecycle clickable end-to-end against mock server responses; no dead button in the batch panel; mobile stacking per existing breakpoints.
