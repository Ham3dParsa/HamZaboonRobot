# Phase 06 — P5 R2 A2 overhaul on working tabs

Gates: D3 (A2 language), §2 five-tab contracts, G1–G3. Blocking: P4
(real tab-2) + polish #833 merged (patterns to inherit).

## Structure (one visible step at a time)

`#view-linking` keeps ONE handoff strip on top, then the tab bar, then
exactly one visible `#linking-tabpanel-N`. `selectLinkingTab` shows /
hides panels (view memory kept); the scroll-to-section hack is deleted.

- Tab 0 Intake: screened picker via cmd popover (`openCmdPopover`
  input) + sense queue + filter + counts (existing queue block,
  reframed — not rebuilt).
- Tab 1 Mechanical: input picker (popover) + run/abort via
  `/api/runs` + method-distribution stats readout + candidates
  preview (existing `candidates-stack` component reused).
- Tab 2 Arbiter: the P4 panel, relocated unchanged.
- Tab 3 Supervised: direct voting column + batch card SIDE BY SIDE in
  the `dense-workspace-grid` pattern (control + workspace, sticky
  control, inner scroll) — never stacked full-page. Queue gains a
  "needs-review only" filter preset; batch issuance pre-fills from the
  unjudged set (G2).
- Tab 4 Export & gallery (LAST step): TSV download + gallery
  build/view + UNIFIED history table (G1): linking runs + arbiter runs
  + batches in one table (existing endpoints only), per-row gallery
  action + reuse-as-input, paginated (shared 50-row pager).

## Req-1 anti-stack rules (owner-locked)

Sticky control columns + `themed-scroll` inner lists + bounded table
heights + shared pager everywhere; zero full-page stacking below the
tab bar; `#833` layout/manager/popover/pager/font/BiDi patterns
inherited verbatim; NOTHING stretched without a ceiling.

## Req-2 live verification (owner-locked)

Live-browser tests per tab (render + primary action + honest empties,
zero console errors) + desktop screenshots beside the T-shots.

## Closing

DESIGN.md v1.1 ratification (A2 standard) + static A2 prototype
worktree/branch deletion + plan STATE to complete.

## Acceptance

Owner eyeballs all five tabs desktop + mobile and says proceed; every
control acts or is honestly disabled with reason.
