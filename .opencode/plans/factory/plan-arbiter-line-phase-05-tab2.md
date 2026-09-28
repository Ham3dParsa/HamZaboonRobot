# Phase 05 — P4 real tab-2 UI

Gates: spec stage 3 WUI + R5 conventions. Blocking: P3.
Scope: linking tab 2 becomes a working panel — preset picker (existing
judge-preset store), run/abort buttons (busy-state, 3-part errors),
live progress (aria-live counts), verdict list, jump-to-supervised for
disagreements. Persian copy via `persian-formatting`; BiDi isolation;
single-script-tag rule (side-effect import in main.js).
Tests: click checklist (recorded) + route-backed flows already in P3.
Acceptance: owner can pick a preset and run a real model from the tab.
