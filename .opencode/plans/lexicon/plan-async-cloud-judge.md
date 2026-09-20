---
name: plan-async-cloud-judge
description: Async cloud judging provider (flexible direct/tunnel route) + CLI flags on the real precard line, zero behavior change to sync path
created: 2026-09-20
base_commit: aaf3627
branch: feat/async-cloud-judge
status: in-progress
---
STATE: phase 1/4 — status: in-progress — focus: RED tests for async transport + route modes

## Locked contract (owner chose each, "proceed" 2026-09-20)

- R1 new module `factory/precard/transport_async.py` (+ thin engine), sync path untouched.
- R2 flexible per-provider route: direct OR tunnel-lease (mirrors net.py TARGETS); start order: direct Groq/OpenRouter 5-call probe, tunnel-Google fallback.
- R3 preset ROWS only (group_label), zero schema change.
- R4 extend pipeline.py flags (`--judge-provider`, `--concurrency`, `--dry-run`); single entry.
- R5 WebUI separate contract after engine gates (this plan: engine+CLI only).
- R6 mocked-AI default (0 tokens); real probes ≤25 calls only on explicit owner order.
- Callback impact NONE. Blast-radius: no structural trigger (new files, no symbol edits) — no graphify.
- Seams claimed: `AI/LLM Provider` (branch feat/async-cloud-judge, R1-R6).

## Phases & evidence

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 1 RED | failing tests: async transport route modes, envelope validation, CLI flags, mocked integration | `complete` (19 collected, collection-error red) |
| 2 GREEN | minimal implementation to pass | `complete` (19/19: transport_async.py + --concurrency; 1 test-authored bug fixed, classified test-bug) |
| 3 VALIDATE | pytest -n 14, compile_all, ruff F821/F811, diff-check | `complete` (3487 passed; 2 parallel-load flakes classified pre-existing — both pass solo, neither imports changed code; compile 0; ruff clean; diff-check clean) |
| 4 REVIEW+PR | hamzaban-reviewer gate → commit → push → PR | `complete` (round5: GATE PASS, 0 confirmed findings; full suite 3506 green; open by design: F2-probes deferred, groq-TARGETS needs amended contract) |

## Notes

- Worktree `.worktrees/feat-async-judge` @ aaf3627; primary stays on main (1 sibling untracked file, read-only).
- Sibling branch `feat/precard-linker-f3` exists with NO file claim; seams differ (no STOP).
- Module-change guard on new module: assess AGENTS table + test_wiring scan + SEAMS.md updates in Phase 3.
- Real-probe budget: 0 spent; ≤25 calls only on explicit owner order.
