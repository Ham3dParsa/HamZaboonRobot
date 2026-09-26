---
name: plan-console
description: Locked console work broken into tickets plus wave ordering to PR (docs only)
created: 2026-09-24
base_commit: 79d6763
branch: feat/webui-v5
status: in-progress
---

STATE: phase 0/6 — status: planned — focus: ticket + wave plans written, awaiting implementation

## 1. Locked scope (owner-confirmed contract, verbatim)

- Defect fixes: all-interfaces default bind with explicit override plus
  LAN-visibility note; tidy script output (status line, per-address URL lines,
  example line, pid-only safety untouched); queue rows slimmed to exactly three
  things (kaikki identifier, gloss slice, status) while the named detail
  section («جزئیات سنس») alone shows candidates, examples, and full text —
  never mix the two; row no-shrink rule plus browser regression test with
  real-shaped rows.
- New: candidates must render from REAL runs carrying human-review lists
  (diagnose why the current feed shows none and fix the join); view memory
  restoring the last cabin and tab on load (persisted locally, default
  unchanged on first run).
- Lifecycle: wake-on-demand gate that truly closes the loop, idle sleep with
  owner number pending, one-time token paste in the panel with encrypted
  storage, primary factory env resolution, state surface with wake and sleep
  buttons.
- Finish line: local commit, push, open pull request (no merge), review loop
  to APPROVED.

## 2. Grounding (worktree `feat/webui-v5`, HEAD `79d6763`)

- Console: `factory/webui/server.py` (bind fns, candidates endpoint
  `/api/candidates`, wake fns, token/env fns), `factory/webui/index.html`
  (queue, `candidates-stack`, human-review tab, `hz-theme` localStorage),
  `factory/webui/server_ctl.ps1` (bind/output/pid-only stop); shim mirror
  `factory/linking/webui/`.
- Tests: `tests/factory/test_factory_webui_host_port.py`,
  `tests/factory/test_sense_linking_judge_webui_interface.py` (static
  HTML-string style), plus `test_sense_linking_judge_webui.py`,
  `test_sense_linking_judge_webui_review810.py`.
- Uncommitted work already in flight in the worktree (stat: 6 files, +1357/−100)
  — tickets build on top of it; T9 commits everything as one logical PR.
- Secrets names-only everywhere: `AI_MASTER_KEY`, `EGRESS_SUP_TOKEN`,
  `HAMZABAN_WEBUI_HOST`, `HAMZABAN_WEBUI_PORT`.

## 3. Tickets

See `TICKETS.md`: T1–T9 with priorities and blocking edges. Per-ticket files:
`plan-console-phase-01-bind.md` (T1), `-02-queue-slim.md` (T3),
`-03-ctl-output.md` (T2), `-04-view-memory.md` (T6), `-05-noshrink.md` (T4),
`-06-token-env.md` (T8), `-07-candidates-join.md` (T5),
`-08-wake-sleep.md` (T7), `-09-ship.md` (T9).

## 4. Wave plan (max 2 parallel workers)

| Wave | Workers | Tickets | Parallel-safe? / serial justification |
|------|---------|---------|----------------------------------------|
| 1 | 2 | T1 + T3 | Parallel: disjoint seams (py/ps1 bind vs `index.html` queue render). Both are foundation. |
| 2 | 2 | T2 + T6 | Parallel: disjoint files (ps1 output vs `index.html` cabin/tab JS). T2 serial-after T1 (same `server_ctl.ps1`); T6 independent of T3's queue region (T3 done). |
| 3 | 2 | T4 + T8 | Parallel with region guard: T4 is CSS rows + new test; T8 is providers-panel HTML + `server.py` token/env region (untouched by T4). T4 serial-after T3 (needs final queue markup). |
| 4 | 1 | T5 | Solo: serial-after T3+T4; touches `server.py` candidates region AND `index.html` render — exclusive to avoid same-file collision. |
| 5 | 1 | T7 | Solo: serial-after T1+T5; touches `server.py` wake region AND `index.html` state buttons — exclusive. Idle-minutes constant stays parked. |
| 6 | 1 | T9 | Final: serial-after all; commit + push + `gh pr create --base main` + review loop to APPROVED, NO merge. |

## 5. Finish line (T9)

Local commit (explicit staging, Conventional Commits), push, open PR
(no merge), `oc-merge-loop` review cycle until APPROVED. Full validation
(`pytest`, `compile_all.py`, `ruff F821/F811`, `git diff --check`) + reviewer
gate inside T9, not in this docs task.

## 6. Parked ambiguities

1. **Idle-sleep minutes** — awaiting owner number (T7 ships a named constant +
   injected-minutes tests; default parked, never invented).
2. **Browser regression harness** — Playwright vs static DOM-shape test
   (recommendation: Playwright with real-shaped row fixture; parked for
   implementer; see phase-05).
3. **Token-paste panel placement** — presumed providers panel; confirm in T8.
